#!/usr/bin/env python3
"""Demo preflight: one line per check, PASS, WARN, FAIL or SKIP, and a one-line fix for everything that is not a PASS.

    python scripts/preflight.py [--stage env|services|all] [--env-file scripts/demo_env] [--offline]

--stage env       checks that need no running server (variables, tokens, GitHub, Slack, database path). Run before the stack starts.
--stage services  checks the running engine and dashboard. Run after the stack started.
--offline         network checks (GitHub, Slack) are SKIPPED, not failed.

Exit code 1 if any check FAILED. It never prints a secret: every line goes through redact(), which removes the exact values of the
token variables and anything shaped like a Slack or GitHub token. A check that cannot reach the network says "no network"."""
import argparse
import hmac
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SECRET_VARS = ("DPDP_API_TOKEN", "VITE_DPDP_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "GITHUB_TOKEN")
REQUIRED = ("DPDP_API_TOKEN", "VITE_DPDP_TOKEN", "DPDP_ALLOWED_REPOS", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_CHANNEL")
RECOMMENDED = {"DPDP_FIX_REPOS": "without it no Fix and verify button works", "SLACK_APPROVERS": "without it nobody can approve a fix in Slack",
               "GITHUB_TOKEN": "only needed for a private repo"}
SHAPES = re.compile(r"xox[a-zA-Z]-[\w-]+|xapp-[\w-]+|gh[pousr]_\w+|github_pat_\w+")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
DEMO_REPO = "Tanish18906/acme-tutornest"
PLACEHOLDER = re.compile(r"replace|placeholder|changeme|your[-_]|example|xxxx", re.I)
NO_NETWORK = re.compile(r"could not resolve|temporary failure in name resolution|network is unreachable|connection timed out|"
                        r"failed to connect|unable to access .* (?:resolve|connect)|name or service not known", re.I)


@dataclass
class Result:
    name: str
    status: str  # PASS, WARN, FAIL, SKIP
    detail: str
    fix: str = ""


# ---- env

def parse_env_file(text: str) -> dict:
    """KEY=VALUE lines like the shell reads them: `export` allowed, # comments, one pair of surrounding quotes removed."""
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.strip()):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        out[key.strip()] = value
    return out


def redact(text, env: dict) -> str:
    """Remove the exact value of every token variable, then anything shaped like a Slack or GitHub token."""
    out = str(text)
    for name in SECRET_VARS:
        value = env.get(name, "")
        if len(value) >= 4:
            out = out.replace(value, "[redacted]")
    return SHAPES.sub("[redacted]", out)


def csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def demo_repo(env: dict) -> str:
    return env.get("DPDP_DEMO_REPO") or DEMO_REPO


def engine_url(env: dict) -> str:
    return env.get("ENGINE_URL", "http://127.0.0.1:8100").rstrip("/")


def dashboard_url(env: dict) -> str:
    return env.get("DASHBOARD_URL", "http://localhost:5174").rstrip("/")


# ---- checks that need no running server

def check_vars(env):
    missing = [n for n in REQUIRED if not env.get(n)]
    if missing:
        return Result("variables", "FAIL", "missing: " + ", ".join(missing), "fill them in scripts/demo_env (copy scripts/demo_env.example)")
    soft = [f"{n} ({why})" for n, why in RECOMMENDED.items() if not env.get(n)]
    return Result("variables", "WARN" if soft else "PASS", "all required variables are set" + (f"; not set: {', '.join(soft)}" if soft else ""),
                  "set them in scripts/demo_env if the demo needs them" if soft else "")


def check_token_formats(env):
    bad = []
    for name in SECRET_VARS:
        value = env.get(name, "")
        if not value:
            continue
        if re.search(r"\s|['\"]", value):
            bad.append(f"{name} has a space or a quote in it")
        elif PLACEHOLDER.search(value):
            bad.append(f"{name} is still the placeholder")
    for name, prefix in (("SLACK_BOT_TOKEN", "xoxb-"), ("SLACK_APP_TOKEN", "xapp-")):
        if env.get(name) and not env[name].startswith(prefix):
            bad.append(f"{name} must start with {prefix}")
    for name in ("DPDP_API_TOKEN", "VITE_DPDP_TOKEN"):
        if env.get(name) and len(env[name]) < 12:
            bad.append(f"{name} is shorter than 12 characters")
    if env.get("GITHUB_TOKEN") and not re.match(r"(gh[pousr]_|github_pat_)", env["GITHUB_TOKEN"]):
        bad.append("GITHUB_TOKEN must start with ghp_, gho_, ghu_, ghs_, ghr_ or github_pat_")
    if bad:
        return Result("token formats", "FAIL", "; ".join(bad), "copy the token again, without quotes or spaces. A new API token: python -c \"import secrets; print(secrets.token_urlsafe(24))\"")
    return Result("token formats", "PASS", "no spaces or quotes, prefixes look right")


def check_slack_ids(env):
    bad = []
    channel = env.get("SLACK_CHANNEL", "")
    if channel and not re.fullmatch(r"[CG][A-Z0-9]{6,}", channel):
        bad.append("SLACK_CHANNEL should be a channel ID like C0123ABCD, not a name")
    for user in csv(env.get("SLACK_APPROVERS", "")):
        if not re.fullmatch(r"[UW][A-Z0-9]{6,}", user):
            bad.append("SLACK_APPROVERS holds something that is not a member ID like U0123ABCD")
            break
    if bad:
        return Result("slack ids", "WARN", "; ".join(bad), "in Slack: open the channel or profile, More, Copy ID")
    return Result("slack ids", "PASS", "channel and approver IDs look right")


def check_vite_matches(env):
    a, b = env.get("DPDP_API_TOKEN", ""), env.get("VITE_DPDP_TOKEN", "")
    if not a or not b:
        return Result("dashboard token", "SKIP", "one of the two tokens is not set")
    if hmac.compare_digest(a.encode(), b.encode()):
        return Result("dashboard token", "PASS", "VITE_DPDP_TOKEN equals DPDP_API_TOKEN")
    return Result("dashboard token", "FAIL", "VITE_DPDP_TOKEN differs from DPDP_API_TOKEN, so the dashboard's status changes will get 401",
                  "set both to the same value, then restart the dashboard (Vite reads it at start)")


def check_allowlist(env):
    allowed = csv(env.get("DPDP_ALLOWED_REPOS", ""))
    bad = [r for r in allowed if not REPO.fullmatch(r)]
    repo = demo_repo(env)
    if not allowed:
        return Result("allowlist", "FAIL", "DPDP_ALLOWED_REPOS is empty, so no repository can be connected", f"set DPDP_ALLOWED_REPOS={repo}")
    if bad:
        return Result("allowlist", "FAIL", "not owner/name: " + ", ".join(bad), "use owner/name, comma separated")
    if repo.lower() not in [r.lower() for r in allowed]:
        return Result("allowlist", "FAIL", f"the demo repo {repo} is not in DPDP_ALLOWED_REPOS", f"add {repo} to DPDP_ALLOWED_REPOS")
    fix = csv(env.get("DPDP_FIX_REPOS", ""))
    stray = [r for r in fix if r.lower() not in [a.lower() for a in allowed]]
    if stray:
        return Result("allowlist", "WARN", "DPDP_FIX_REPOS has repos that cannot be connected: " + ", ".join(stray), "add them to DPDP_ALLOWED_REPOS")
    return Result("allowlist", "PASS", f"{repo} is allowlisted" + (" and may be fixed" if repo.lower() in [f.lower() for f in fix] else ", but is not in DPDP_FIX_REPOS (no live fix)"))


def check_monitor(env):
    if env.get("DPDP_MONITOR") == "0":
        return Result("monitor", "WARN", "scheduled re-scan is OFF (DPDP_MONITOR=0), so /dpdp watch will not scan", "unset DPDP_MONITOR if you want to demo /dpdp watch")
    return Result("monitor", "PASS", "scheduled re-scan is ON (the engine starts it)")


def check_db(env):
    state = Path(env.get("DPDP_STATE_DIR") or ROOT / ".dpdp-state")
    path = Path(env.get("DPDP_DB") or state / "dpdp.db")
    if path.exists():
        ok = os.access(path, os.W_OK)
    else:
        parent = path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        ok = os.access(parent, os.W_OK | os.X_OK)
    if ok:
        return Result("database", "PASS", f"{path} can be written" + ("" if path.exists() else " (it will be created)"))
    return Result("database", "FAIL", f"{path} cannot be written", "fix the folder permissions or point DPDP_DB at a folder you own")


def check_git(env, base="https://github.com", run=subprocess.run):
    """git ls-remote on the demo repo. The GitHub token reaches git through GIT_ASKPASS and the environment, never argv or a URL."""
    repo, token = demo_repo(env), env.get("GITHUB_TOKEN", "")
    with tempfile.TemporaryDirectory(prefix="dpdp-preflight-") as tmp:
        child = {k: v for k, v in os.environ.items() if k not in SECRET_VARS}
        child.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
        if token:
            helper = Path(tmp) / "askpass.sh"
            helper.write_text('#!/bin/sh\ncase "$1" in Username*) echo x-access-token ;; *) echo "$DPDP_GIT_TOKEN" ;; esac\n')
            helper.chmod(stat.S_IRWXU)
            child.update(GIT_ASKPASS=str(helper), DPDP_GIT_TOKEN=token)
        try:
            proc = run(["git", "ls-remote", "--heads", f"{base}/{repo}.git"], env=child, capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired:
            return Result("github repo", "FAIL", "no network: git took longer than 15 seconds", "connect to Wi-Fi or a phone hotspot. The cached fix mode works offline")
        except FileNotFoundError:
            return Result("github repo", "FAIL", "git is not installed", "install git")
    err = " ".join((proc.stderr or "").split())
    if proc.returncode == 0:
        return Result("github repo", "PASS", f"{repo} answers ({len((proc.stdout or '').splitlines())} branches)")
    if NO_NETWORK.search(err):
        return Result("github repo", "FAIL", "no network: " + redact(err[:160], env), "connect to Wi-Fi or a phone hotspot. The cached fix mode works offline")
    return Result("github repo", "FAIL", f"cannot read {repo}: " + redact(err[:160], env),
                  "check the repo name, and that GITHUB_TOKEN can read it (a private repo needs the token)")


def check_slack(env, post=httpx.post):
    token = env.get("SLACK_BOT_TOKEN", "")
    if not token:
        return Result("slack bot token", "SKIP", "SLACK_BOT_TOKEN is not set")
    try:
        data = post("https://slack.com/api/auth.test", headers={"Authorization": f"Bearer {token}"}, timeout=5).json()
    except (httpx.TransportError, ValueError) as e:
        text = redact(f"{type(e).__name__}", env)
        return Result("slack bot token", "FAIL", f"no network: cannot reach slack.com ({text})", "connect to Wi-Fi or a phone hotspot")
    if data.get("ok"):
        return Result("slack bot token", "PASS", f"auth.test ok (workspace {data.get('team', '?')}, bot {data.get('user', '?')})")
    error = re.sub(r"[^a-z_]", "", str(data.get("error", "unknown")))[:40]
    return Result("slack bot token", "FAIL", f"Slack says {error}", "copy the Bot User OAuth Token (xoxb-) again from the app's OAuth page, or reinstall the app")


# ---- checks on the running stack

def check_engine(env, get=httpx.get):
    url = engine_url(env)
    try:
        health = get(f"{url}/health", timeout=3)
        repos = get(f"{url}/repos", timeout=3)
    except httpx.TransportError:
        return Result("engine", "FAIL", f"nothing answers at {url}", "start it: scripts/demo_up.sh (log in /tmp, see the demo runbook)")
    if health.status_code != 200 or repos.status_code != 200:
        return Result("engine", "FAIL", f"{url} answered {health.status_code} on /health and {repos.status_code} on /repos",
                      "the engine is up but its store failed: read its log, or run scripts/demo_reset.sh")
    return Result("engine", "PASS", f"/health and GET /repos work ({len(repos.json())} repos)")


def check_engine_auth(env, post=httpx.post):
    """POST /repos/0/baseline needs the token, then answers 404 for the unknown repo: so 404 means the token was accepted."""
    url, token = engine_url(env), env.get("DPDP_API_TOKEN", "")

    def call(value):
        return post(f"{url}/repos/0/baseline", headers={"X-DPDP-Token": value}, json={"actor": "preflight"}, timeout=3).status_code

    try:
        good, bad = call(token), call("wrong-" + secrets.token_hex(6))
    except httpx.TransportError:
        return Result("engine token", "SKIP", "the engine is not reachable")
    if good in (401, 403):
        why = "the engine has no DPDP_API_TOKEN" if good == 403 else "the engine was started with a different DPDP_API_TOKEN"
        return Result("engine token", "FAIL", f"the engine refuses our token ({good}): {why}", "restart the engine from the same scripts/demo_env: scripts/demo_down.sh then scripts/demo_up.sh")
    if bad not in (401, 403):
        return Result("engine token", "FAIL", f"a wrong token was not refused (got {bad})", "the engine is not checking X-DPDP-Token: update the engine code")
    return Result("engine token", "PASS", f"our token is accepted, a wrong one gets {bad}")


def check_dashboard(env, get=httpx.get):
    url = dashboard_url(env)
    try:
        status = get(url, timeout=3).status_code
    except httpx.TransportError:
        return Result("dashboard", "FAIL", f"nothing answers at {url}", "start it: scripts/demo_up.sh")
    return Result("dashboard", "PASS" if status == 200 else "FAIL", f"{url} answered {status}", "" if status == 200 else "read the dashboard log")


ENV_CHECKS = (check_vars, check_token_formats, check_slack_ids, check_vite_matches, check_allowlist, check_monitor, check_db)
NETWORK_CHECKS = ((check_git, "github repo"), (check_slack, "slack bot token"))
SERVICE_CHECKS = (check_engine, check_engine_auth, check_dashboard)


def run_checks(env: dict, stage: str = "all", offline: bool = False) -> list[Result]:
    results = []
    if stage in ("env", "all"):
        results += [c(env) for c in ENV_CHECKS]
        for check, name in NETWORK_CHECKS:
            results.append(Result(name, "SKIP", "--offline: not checked") if offline else check(env))
    if stage in ("services", "all"):
        results += [c(env) for c in SERVICE_CHECKS]
    return results


def render(results: list[Result], env: dict) -> str:
    lines = []
    for r in results:
        lines.append(redact(f"{r.status:<5} {r.name:<16} {r.detail}", env))
        if r.status in ("FAIL", "WARN") and r.fix:
            lines.append(redact(f"      fix: {r.fix}", env))
    failed, warned = sum(r.status == "FAIL" for r in results), sum(r.status == "WARN" for r in results)
    lines.append(f"{len(results) - failed - warned - sum(r.status == 'SKIP' for r in results)} passed, {failed} failed, {warned} warnings, "
                 f"{sum(r.status == 'SKIP' for r in results)} skipped")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stage", choices=("env", "services", "all"), default="all")
    ap.add_argument("--env-file", help="read KEY=VALUE lines from this file (they win over the environment)")
    ap.add_argument("--offline", action="store_true", help="skip the checks that need the internet")
    args = ap.parse_args(argv)
    env = dict(os.environ)
    if args.env_file:
        try:
            env.update(parse_env_file(Path(args.env_file).read_text()))
        except OSError as e:
            print(f"FAIL  env file         cannot read {args.env_file}: {e.strerror}\n      fix: copy scripts/demo_env.example to scripts/demo_env")
            return 1
    results = run_checks(env, args.stage, args.offline)
    print(render(results, env))
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
