"""scripts/preflight.py and the demo launcher scripts, offline: a fake engine, fake Slack answers, a local bare repo. No secret is ever printed."""
import importlib.util
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from dpdp_lens.api import create_app
from dpdp_lens.store import Store
from remote import git, make_remote

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("preflight", ROOT / "scripts" / "preflight.py")
pf = importlib.util.module_from_spec(spec)
sys.modules["preflight"] = pf
spec.loader.exec_module(pf)

BOT = "xo" + "xb-" + "1234567890-abcdefghijklmnop"
APP = "xa" + "pp-" + "1-A0123456789-abcdefghijklmnopqrstuvwxyz"
GH = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
API = "api-token-for-tests-1234567890"
GOOD = {"DPDP_API_TOKEN": API, "VITE_DPDP_TOKEN": API, "DPDP_ALLOWED_REPOS": pf.DEMO_REPO, "DPDP_FIX_REPOS": pf.DEMO_REPO, "GITHUB_TOKEN": GH,
        "SLACK_BOT_TOKEN": BOT, "SLACK_APP_TOKEN": APP, "SLACK_CHANNEL": "C0123ABCD", "SLACK_APPROVERS": "U0123ABCD,U0456EFGH"}
SECRETS = (API, GH, BOT, APP)


def status(result):
    return result.status


# ---- env file and redaction

def test_parse_env_file_reads_what_the_shell_would():
    env = pf.parse_env_file("# c\n\nexport A=1\nB='two words'\nC=\"x\"\nD=val # trailing\nnot a line\n1BAD=x\nE=\nF=a=b\n")
    assert env == {"A": "1", "B": "two words", "C": "x", "D": "val", "E": "", "F": "a=b"}


def test_example_env_file_parses_and_holds_only_placeholders():
    env = pf.parse_env_file((ROOT / "scripts" / "demo_env.example").read_text())
    assert {"DPDP_API_TOKEN", "VITE_DPDP_TOKEN", "DPDP_ALLOWED_REPOS", "DPDP_FIX_REPOS", "GITHUB_TOKEN", "DPDP_DB", "DPDP_MONITOR", "SLACK_BOT_TOKEN",
            "SLACK_APP_TOKEN", "SLACK_CHANNEL", "SLACK_APPROVERS", "ENGINE_URL", "DASHBOARD_URL"} <= set(env)
    assert all(pf.PLACEHOLDER.search(env[n]) for n in pf.SECRET_VARS) and not pf.SHAPES.search("".join(env.values()).replace("xoxb-REPLACE_ME", "").replace("xapp-REPLACE_ME", ""))


def test_redact_removes_exact_values_and_token_shapes():
    text = f"boom {API} and {GH} and {BOT} and {APP} and xoxp-999-888-aaa"
    out = pf.redact(text, GOOD)
    assert not any(s in out for s in SECRETS) and "xoxp-999" not in out and out.count("[redacted]") == 5


def test_render_never_prints_a_secret_even_when_a_check_put_one_in_its_text():
    out = pf.render([pf.Result("x", "FAIL", f"token {API} {BOT}", f"use {GH}")], GOOD)
    assert not any(s in out for s in SECRETS) and "FAIL" in out and "fix:" in out


# ---- env checks

def test_good_environment_passes_every_env_check(tmp_path):
    env = {**GOOD, "DPDP_DB": str(tmp_path / "x.db")}
    assert [(c.__name__, c(env).status) for c in pf.ENV_CHECKS] == [(c.__name__, "PASS") for c in pf.ENV_CHECKS]


def test_missing_variables_are_named_without_values():
    r = pf.check_vars({"DPDP_API_TOKEN": API})
    assert r.status == "FAIL" and "SLACK_BOT_TOKEN" in r.detail and API not in r.detail and r.fix


def test_missing_recommended_variables_only_warn():
    r = pf.check_vars({k: v for k, v in GOOD.items() if k not in ("DPDP_FIX_REPOS", "SLACK_APPROVERS")})
    assert r.status == "WARN" and "DPDP_FIX_REPOS" in r.detail and "SLACK_APPROVERS" in r.detail


@pytest.mark.parametrize("name, value, words", [
    ("SLACK_BOT_TOKEN", "xo" + "xp-123", "must start with xoxb-"), ("SLACK_APP_TOKEN", "xo" + "xb-1", "must start with xapp-"),
    ("SLACK_BOT_TOKEN", f'"{BOT}"', "space or a quote"), ("DPDP_API_TOKEN", API + " ", "space or a quote"),
    ("DPDP_API_TOKEN", "short", "shorter than 12"), ("DPDP_API_TOKEN", "REPLACE_WITH_A_LONG_RANDOM_TOKEN", "placeholder"),
    ("GITHUB_TOKEN", "abc123abc123abc123", "must start with")])
def test_token_format_failures(name, value, words):
    r = pf.check_token_formats({**GOOD, name: value})
    assert r.status == "FAIL" and words in r.detail and API not in r.detail and BOT not in r.detail


def test_slack_ids_warn_for_a_channel_name_and_a_bad_approver():
    assert pf.check_slack_ids({**GOOD, "SLACK_CHANNEL": "#general"}).status == "WARN"
    assert pf.check_slack_ids({**GOOD, "SLACK_APPROVERS": "tanish"}).status == "WARN"


def test_dashboard_token_must_equal_the_api_token():
    assert pf.check_vite_matches(GOOD).status == "PASS"
    r = pf.check_vite_matches({**GOOD, "VITE_DPDP_TOKEN": "different-token-value-1"})
    assert r.status == "FAIL" and "different-token" not in r.detail


@pytest.mark.parametrize("allowed, fix, expect", [
    ("", "", "FAIL"), ("a b", "", "FAIL"), ("someone/else", "", "FAIL"), (pf.DEMO_REPO.upper(), pf.DEMO_REPO, "PASS"),
    (pf.DEMO_REPO, "other/repo", "WARN"), (pf.DEMO_REPO + ",x/y", "", "PASS")])
def test_allowlist_logic(allowed, fix, expect):
    assert pf.check_allowlist({"DPDP_ALLOWED_REPOS": allowed, "DPDP_FIX_REPOS": fix}).status == expect


def test_monitor_off_warns_and_on_passes():
    assert pf.check_monitor({"DPDP_MONITOR": "0"}).status == "WARN" and pf.check_monitor({}).status == "PASS" and pf.check_monitor({"DPDP_MONITOR": "1"}).status == "PASS"


def test_database_path_must_be_writable(tmp_path):
    assert pf.check_db({"DPDP_DB": str(tmp_path / "new" / "deep" / "x.db")}).status == "PASS"
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        r = pf.check_db({"DPDP_DB": str(ro / "x.db")})
    finally:
        ro.chmod(0o700)
    assert r.status == "FAIL" and "cannot be written" in r.detail


# ---- GitHub (local bare repo as the remote) and Slack (fake answers)

def test_git_check_reaches_a_repo_and_never_puts_the_token_in_argv_or_the_url(tmp_path):
    make_remote(tmp_path, pf.DEMO_REPO)
    calls, real = [], subprocess.run
    r = pf.check_git(GOOD, base=f"file://{tmp_path}", run=lambda cmd, **kw: (calls.append((cmd, kw["env"])), real(cmd, **kw))[1])
    assert r.status == "PASS" and GH not in r.detail
    (cmd, env), = calls
    assert GH not in " ".join(cmd) and cmd[:2] == ["git", "ls-remote"] and env["DPDP_GIT_TOKEN"] == GH and "GIT_ASKPASS" in env
    assert "SLACK_BOT_TOKEN" not in env and "DPDP_API_TOKEN" not in env  # other secrets are not passed to git


def test_git_check_fails_for_a_missing_repo_and_says_no_network_when_the_host_is_unreachable(tmp_path):
    missing = pf.check_git(GOOD, base=f"file://{tmp_path}")
    assert missing.status == "FAIL" and "cannot read" in missing.detail and GH not in missing.detail
    r = pf.check_git(GOOD, base="https://no-such-host.invalid")
    assert r.status == "FAIL" and "no network" in r.detail and GH not in r.detail


def test_git_check_timeout_says_no_network():
    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 15)

    assert "no network" in pf.check_git(GOOD, run=slow).detail


class Answer:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def test_slack_check_ok_bad_token_and_no_network():
    seen = {}

    def ok(url, headers, timeout):
        seen.update(url=url, headers=headers, timeout=timeout)
        return Answer({"ok": True, "team": "Demo", "user": "dpdp"})

    assert pf.check_slack(GOOD, post=ok).status == "PASS"
    assert BOT not in seen["url"] and seen["headers"]["Authorization"] == f"Bearer {BOT}" and seen["timeout"] <= 5
    bad = pf.check_slack(GOOD, post=lambda *a, **k: Answer({"ok": False, "error": "invalid_auth"}))
    assert bad.status == "FAIL" and "invalid_auth" in bad.detail and BOT not in bad.detail

    def down(*a, **k):
        raise httpx.ConnectError(f"cannot connect with {BOT}")

    r = pf.check_slack(GOOD, post=down)
    assert r.status == "FAIL" and "no network" in r.detail and BOT not in r.detail
    assert pf.check_slack({}, post=down).status == "SKIP"


# ---- running stack: the real engine app through TestClient, and a fake that gets the token wrong

class Quiet:
    """The TestClient does not take a timeout argument: the checks pass one, so drop it here."""

    def __init__(self, client):
        self.get = lambda url, timeout=None, **kw: client.get(url, **kw)
        self.post = lambda url, timeout=None, **kw: client.post(url, **kw)


def engine_env(monkeypatch, token=API):
    if token is None:
        monkeypatch.delenv("DPDP_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("DPDP_API_TOKEN", token)
    client = Quiet(TestClient(create_app(store=Store(":memory:"))))
    return {**GOOD, "ENGINE_URL": "http://testserver"}, client


def test_engine_checks_pass_against_the_real_engine_app(monkeypatch):
    env, c = engine_env(monkeypatch)
    assert pf.check_engine(env, get=c.get).status == "PASS"
    r = pf.check_engine_auth(env, post=c.post)
    assert r.status == "PASS" and "wrong one gets 401" in r.detail


def test_engine_started_with_another_token_is_a_fail_that_says_so(monkeypatch):
    env, c = engine_env(monkeypatch, token="some-other-engine-token-123")
    r = pf.check_engine_auth(env, post=c.post)
    assert r.status == "FAIL" and "different DPDP_API_TOKEN" in r.detail and "some-other" not in r.detail and API not in r.detail


def test_engine_without_a_token_is_a_fail_that_says_so(monkeypatch):
    env, c = engine_env(monkeypatch, token=None)
    r = pf.check_engine_auth(env, post=c.post)
    assert r.status == "FAIL" and "no DPDP_API_TOKEN" in r.detail


def test_an_engine_that_accepts_any_token_fails():
    post = lambda url, headers, json, timeout: type("R", (), {"status_code": 404})()  # noqa: E731
    r = pf.check_engine_auth(GOOD, post=post)
    assert r.status == "FAIL" and "wrong token was not refused" in r.detail


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_nothing_listening_is_a_fail_for_the_engine_and_the_dashboard_and_a_skip_for_the_token():
    env = {**GOOD, "ENGINE_URL": f"http://127.0.0.1:{free_port()}", "DASHBOARD_URL": f"http://127.0.0.1:{free_port()}"}
    assert [r.status for r in pf.run_checks(env, "services")] == ["FAIL", "SKIP", "FAIL"]


def test_dashboard_check_reads_the_status_code():
    resp = lambda code: (lambda url, timeout: type("R", (), {"status_code": code})())  # noqa: E731
    assert pf.check_dashboard(GOOD, get=resp(200)).status == "PASS" and pf.check_dashboard(GOOD, get=resp(500)).status == "FAIL"


# ---- command line

def test_main_offline_prints_no_secret_and_exits_1_on_a_fail(tmp_path, capsys):
    f = tmp_path / "env"
    f.write_text("".join(f"{k}={v}\n" for k, v in {**GOOD, "SLACK_APP_TOKEN": "xo" + "xb-wrong"}.items()))
    assert pf.main(["--stage", "env", "--offline", "--env-file", str(f)]) == 1
    out = capsys.readouterr().out
    assert not any(s in out for s in SECRETS) and "SKIP  github repo" in out and "SKIP  slack bot token" in out and "must start with xapp-" in out


def test_main_offline_passes_with_a_good_environment(tmp_path, capsys):
    f = tmp_path / "env"
    f.write_text("".join(f"{k}={v}\n" for k, v in {**GOOD, "DPDP_DB": str(tmp_path / "x.db")}.items()))
    assert pf.main(["--stage", "env", "--offline", "--env-file", str(f)]) == 0
    assert "0 failed" in capsys.readouterr().out


def test_main_with_a_missing_env_file_says_how_to_make_one(capsys):
    assert pf.main(["--env-file", "/no/such/demo_env"]) == 1
    assert "demo_env.example" in capsys.readouterr().out


# ---- scripts

@pytest.mark.parametrize("name", ["demo_up.sh", "demo_down.sh", "demo_reset.sh"])
def test_launcher_scripts_have_valid_shell_syntax_and_are_executable(name):
    path = ROOT / "scripts" / name
    assert os.access(path, os.X_OK) and subprocess.run(["bash", "-n", str(path)]).returncode == 0


def test_demo_up_stops_before_starting_anything_when_there_is_no_env_file():
    r = subprocess.run(["bash", str(ROOT / "scripts" / "demo_up.sh")], env={**os.environ, "DPDP_DEMO_ENV": "/no/such/file"}, capture_output=True, text=True)
    assert r.returncode == 2 and "demo_env.example" in r.stdout


def reset(tmp_path, answer):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    files = [state / n for n in ("dpdp.db", "dpdp.db-wal", "dpdp.db-shm", "S-001.json", "S-002.json.tmp")]
    keep = [state / "notes.txt", tmp_path / "demo.db"]
    for f in files + keep:
        f.write_text("x")
    env = {**os.environ, "DPDP_DEMO_ENV": "/no/such/file", "DPDP_STATE_DIR": str(state)}
    env.pop("DPDP_DB", None)
    r = subprocess.run(["bash", str(ROOT / "scripts" / "demo_reset.sh")], input=answer, env=env, capture_output=True, text=True)
    return r, files, keep


@pytest.mark.skipif(socket.socket().connect_ex(("127.0.0.1", 8100)) == 0, reason="something listens on :8100")
@pytest.mark.parametrize("answer", ["", "no\n", "y\n", "YES\n", "yes please\n"])
def test_demo_reset_deletes_nothing_unless_yes_is_typed(tmp_path, answer):
    r, files, keep = reset(tmp_path, answer)
    assert r.returncode == 1 and all(f.exists() for f in files + keep) and "Not deleted" in r.stdout


@pytest.mark.skipif(socket.socket().connect_ex(("127.0.0.1", 8100)) == 0, reason="something listens on :8100")
def test_demo_reset_deletes_the_database_and_saved_scans_only_after_yes(tmp_path):
    r, files, keep = reset(tmp_path, "yes\n")
    assert r.returncode == 0 and not any(f.exists() for f in files) and all(f.exists() for f in keep)
    assert str(tmp_path / "state" / "dpdp.db") in r.stdout
