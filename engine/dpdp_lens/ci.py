"""`python -m dpdp_lens ci`: a static scan of a checkout, judged by the policy. Needs no running app and no database.
Exit codes: 0 pass or warn, 1 blocking findings, 2 incomplete scan, invalid config, invalid policy, invalid baseline or any
other error. It never exits 0 when the scan did not finish."""
import json
import os
import subprocess
import sys
from pathlib import Path

from .checks import CHECKS
from .models import ScanResult
from .policy import DEFAULT_POLICY, Evaluation, PolicyError, ProjectConfig, evaluate, load_baseline, load_config, load_policy
from .repo_scan import scan_checkout
from .runner import app_root_of
from .sarif import to_sarif

CONFIG_NAME = ".dpdp-lens.yml"
FOOTER = "Readiness report, not a compliance certificate."


def register(sub) -> None:
    p = sub.add_parser("ci", help="static scan of a checkout judged by the policy (exit 0 pass or warn, 1 fail, 2 incomplete or invalid)")
    p.add_argument("--repo-dir", default=".", help="the checkout to scan (default: the current folder)")
    p.add_argument("--config", help=f"project config (default: {CONFIG_NAME} in --repo-dir, if it exists)")
    p.add_argument("--baseline", help="baseline file (default: the config's baseline)")
    p.add_argument("--new-only", action="store_true", help="only findings that are not in the baseline can fail the run")
    p.add_argument("--write-baseline", action="store_true", help="write the baseline from this scan and exit 0 (2 if the scan is incomplete)")
    p.add_argument("--sarif", help="write SARIF 2.1.0 here")
    p.add_argument("--json", help="write the scan JSON, plus an `evaluation` object with the decision, here")
    p.add_argument("--summary", help="write a Markdown summary here (for $GITHUB_STEP_SUMMARY)")
    p.set_defaults(func=run)


def _md(text) -> str:
    """One safe table cell. Finding text can come from the scanned repo, and a step summary renders Markdown and HTML."""
    return " ".join(str(text).split()).replace("|", "\\|").replace("`", "'").replace("<", "&lt;").replace(">", "&gt;")


def _git_root(repo_dir: Path) -> Path:
    """The git top level (the base GitHub resolves SARIF paths against), else repo_dir itself."""
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repo_dir, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    return Path(out).resolve() if out else repo_dir.resolve()


def _repo_relative(scan: ScanResult, repo_dir: Path) -> ScanResult:
    """Finding paths are relative to the app root (backend/ and frontend/ side by side). Make them relative to the git
    top level, for SARIF, the summary and the baseline. Fingerprints are already computed and do not change."""
    backend = repo_dir / "backend"
    try:
        prefix = app_root_of(backend if backend.is_dir() else repo_dir).resolve().relative_to(_git_root(repo_dir)).as_posix()
    except ValueError:
        return scan  # the app root is above the git root: paths stay relative to the app root
    if prefix in ("", "."):
        return scan

    def move(f):
        loc = f.evidence.location
        if not loc.file:
            return f
        return f.model_copy(update={"evidence": f.evidence.model_copy(update={"location": loc.model_copy(update={"file": f"{prefix}/{loc.file}"})})})
    return scan.model_copy(update={"findings": [move(f) for f in scan.findings]})


def baseline_json(scan: ScanResult, ev: Evaluation) -> dict:
    by_fp = {f.fingerprint: f for f in scan.findings}
    return {"version": 1, "policy": f"{ev.policy_id}@{ev.policy_version}",
            "fingerprints": [{"fp": i.fingerprint, "check": i.check, "title": by_fp[i.fingerprint].title,
                              "file": by_fp[i.fingerprint].evidence.location.file} for i in ev.items]}


def summary_md(scan: ScanResult, ev: Evaluation) -> str:
    by_fp = {f.fingerprint: f for f in scan.findings}
    live = [i for i in ev.items if not i.suppressed]
    n = {a: sum(1 for i in live if i.action == a and (i.is_new or not ev.new_only)) for a in ("block", "warn", "info")}
    lines = [f"## DPDP Lens: {ev.decision.upper()}", "",
             f"{n['block']} blocking, {n['warn']} warning, {n['info']} info"
             + (f", {len(ev.items) - len(live)} suppressed" if len(live) != len(ev.items) else "")
             + f". Policy {ev.policy_id} {ev.policy_version}.", ""]
    if ev.decision == "incomplete":
        lines += ["**The scan did not finish, so this is not a pass.**", ""]
        lines += [f"- `{_md(e.scanner)}` {e.kind}: {_md(e.message)}" for e in scan.scan_errors] + [""]
    blocking = ev.blocking()
    if blocking:
        lines += [f"### {'New blocking findings' if ev.new_only else 'Blocking findings'}", "",
                  "| Finding | Check | File:line | Clause |", "|---|---|---|---|"]
        for i in blocking:
            f = by_fp[i.fingerprint]
            loc = f.evidence.location
            lines.append(f"| {_md(f.id)} | {_md(f.check)} | {_md(loc.file + (f':{loc.line}' if loc.line else '') or '-')} | {_md(', '.join(c.ref for c in f.clauses) or '-')} |")
        lines.append("")
    if ev.new_only:
        lines += [f"{sum(1 for i in ev.items if not i.is_new)} existing findings in baseline.", ""]
    cov = scan.coverage
    lines += [f"Coverage: static checks only, {len(cov.checks_run) if cov else 0} of {len(CHECKS)}.", "", f"_{FOOTER}_", ""]
    return "\n".join(lines)


def _setup(args) -> tuple[Path, ProjectConfig, Path, bool]:
    repo_dir = Path(args.repo_dir)
    if not repo_dir.is_dir():
        raise PolicyError(f"--repo-dir {repo_dir} is not a folder")
    config_path = Path(args.config) if args.config else repo_dir / CONFIG_NAME
    if args.config and not config_path.is_file():
        raise PolicyError(f"--config {config_path} does not exist")
    cfg = load_config(config_path if config_path.is_file() else None)
    return repo_dir, cfg, config_path.parent, args.new_only or cfg.new_only


def run(args) -> int:
    try:
        return _run(args)
    except PolicyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
    except Exception as e:  # an uncaught crash would exit 1, which reads as "findings": it is "could not judge" instead
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
    return 2


def _run(args) -> int:
    repo_dir, cfg, base_dir, new_only = _setup(args)
    policy_path = DEFAULT_POLICY if cfg.policy == "default" else base_dir / cfg.policy
    policy = load_policy(policy_path)
    baseline_path = Path(args.baseline) if args.baseline else base_dir / cfg.baseline
    baseline = load_baseline(baseline_path) if new_only and not args.write_baseline else None
    if args.write_baseline and not args.baseline:
        baseline_path = base_dir / cfg.baseline

    scan = scan_checkout(repo_dir, "S-CI", repo=os.environ.get("GITHUB_REPOSITORY", ""),
                         branch=os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", ""))
    scan = _repo_relative(scan, repo_dir)
    ev = evaluate(scan, policy, cfg, {s.fingerprint for s in cfg.suppress}, baseline, new_only and not args.write_baseline)

    if args.sarif:
        Path(args.sarif).write_text(json.dumps(to_sarif(scan), indent=2) + "\n")
    if args.json:
        Path(args.json).write_text(json.dumps({**scan.model_dump(), "evaluation": ev.model_dump()}, indent=2) + "\n")
    if args.summary:
        Path(args.summary).write_text(summary_md(scan, ev))
    if ev.decision == "incomplete":
        names = ", ".join(dict.fromkeys(e.scanner for e in scan.scan_errors))
        print(f"INCOMPLETE: {len(scan.scan_errors)} scanner errors ({names})", file=sys.stderr)
        return 2
    if args.write_baseline:
        baseline_path.write_text(json.dumps(baseline_json(scan, ev), indent=2) + "\n")
        print(f"baseline: {len(ev.items)} findings -> {baseline_path}")
        return 0
    print(f"{ev.decision}: {len(ev.blocking())} blocking of {len(ev.items)} findings (policy {ev.policy_id} {ev.policy_version})")
    return 1 if ev.decision == "fail" else 0
