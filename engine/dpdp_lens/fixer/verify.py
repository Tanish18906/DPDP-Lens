"""Fix and verify: patch a sandbox copy, re-scan it, run the app's tests, build the diff.
`verified` is computed here from the re-scan and the pytest exit code. Nothing sets it by hand."""
import difflib
import json
import os
import py_compile
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from ..models import Finding, Fix, NoticeDrift, ScanResult
from ..runner import SCANNER_TIMEOUT, SCANNER_CHECKS, STATIC_CHECKS, STATIC_SCANNERS, run_scan
from ..scanners import notice_drift as drift_scan
from .notice_align import NOTICE_ALIGN, align_notice, pending_inputs
from .sandbox import START_TIMEOUT, Sandbox
from .templates import TEMPLATES, PatchError, Template, apply_template

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "data" / "golden"
FIX_TIMEOUT = 60  # seconds for the whole live run


class FixTimeout(Exception):
    pass


@dataclass
class Verification:
    fix: Fix
    rescan: ScanResult | None  # None for the notice fix, which re-runs one scanner only
    tests_output: str
    log: dict = field(default_factory=dict)  # real timings and facts of this run, for the dashboard's verification log


def _key(f: Finding):
    """Same problem in a re-scan: same check at the same URL path, file, table and column."""
    loc = f.evidence.location
    file_name = Path(loc.file).name if (loc.file and not loc.url) else ""
    return (f.check, urlparse(loc.url).path if loc.url else "", file_name, loc.table, loc.column)


def _left(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise FixTimeout(f"fix and verify took longer than {FIX_TIMEOUT} seconds")
    return left


def _run_pytest(tests_dir: Path, url: str, deadline: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", str(tests_dir), "-q", "-p", "no:cacheprovider"],
            cwd=tests_dir, capture_output=True, text=True, timeout=_left(deadline),
            env={**os.environ, "TUTORNEST_BASE_URL": url, "PYTHONDONTWRITEBYTECODE": "1"})  # original folder stays untouched
    except subprocess.TimeoutExpired as e:
        raise FixTimeout("the app's tests did not finish in time") from e


def verify_fix(finding: Finding, repo_path, db_path, *, tests_dir=None, frontend_dir=None, template: Template | None = None,
               score_before: int | None = None, golden_dir=GOLDEN_DIR, timeout: float = FIX_TIMEOUT,
               drift: NoticeDrift | None = None) -> Verification:
    if finding.check == "notice_drift":  # generated patch, not a fixed snippet
        return verify_notice_align(finding, repo_path, db_path, drift=drift, tests_dir=tests_dir,
                                   score_before=score_before, golden_dir=golden_dir, timeout=timeout)
    template = template or TEMPLATES.get(finding) or TEMPLATES.get(finding.check)
    if template is None:
        raise PatchError(f"no fix template for {finding.check}")
    tests_dir = Path(tests_dir or Path(repo_path).parent / "tests")
    frontend_dir = Path(frontend_dir or Path(repo_path).parent / "frontend") if template.needs_frontend else None
    deadline = time.monotonic() + timeout
    started = last = time.monotonic()
    steps: list[dict] = []

    def mark(step: str) -> None:  # measured wall time of each phase, in the order the dashboard lists them
        nonlocal last
        now = time.monotonic()
        steps.append({"step": step, "ms": round((now - last) * 1000)})
        last = now

    with Sandbox(repo_path, db_path, start_timeout=min(START_TIMEOUT, timeout), frontend_path=frontend_dir) as sb:
        mark("copy")
        initial_checks = set()
        if template.scanner in ("config_scan", "frontend_scan", "consent_scan"):
            initial_scan = run_scan("", str(sb.repo), "", mode="static")
            initial_checks = {f.check for f in initial_scan.findings}

        roots = {"backend": sb.repo, "frontend": sb.frontend, "app_root": sb.root}
        changes = apply_template(template, roots)
        changes_second = apply_template(template, roots, allow_idempotent=True)
        idempotent = len(changes_second) == 0

        for change in changes:
            if change.label.endswith(".py"):
                try:
                    py_compile.compile(str(sb.repo / change.label), doraise=True)
                except py_compile.PyCompileError as e:
                    raise PatchError(f"patched {change.label} does not compile: {e.msg}") from e
        extra = {}
        if template.needs_frontend:
            sb.build_frontend()  # PatchError if the patched frontend does not build
            _left(deadline)
        mark("patch")  # includes the frontend build for a frontend patch
        url = sb.start()
        if template.needs_frontend:
            extra["frontend_url"] = sb.start_frontend()  # the re-scan looks at the patched page, not the original
        _left(deadline)
        mark("start")
        # Re-scan first: pytest signs users up and deletes them, which would change the sandbox DB and the score.
        errors: list[str] = []
        rescan = run_scan(url, str(sb.repo), str(sb.db), timeout=min(SCANNER_TIMEOUT, _left(deadline)), errors=errors, **extra)
        broken = [e for e in errors if e.startswith(f"{template.scanner}:")]
        if broken:  # a scanner that could not run must never read as "the finding is gone"
            raise RuntimeError(f"the re-scan could not run {template.scanner}: {broken[0]}")
        mark("rescan")
        proc = _run_pytest(tests_dir, url, deadline)
        mark("tests")
        sandbox_root = str(sb.root)

    gone = all(_key(f) != _key(finding) for f in rescan.findings)
    tests_ok = proc.returncode == 0  # for a frontend patch this also means the patched frontend built
    rescan_checks = {f.check for f in rescan.findings}
    static_checks = {c for s in STATIC_SCANNERS for c in (STATIC_CHECKS.get(s) or SCANNER_CHECKS.get(s, []))}
    new_checks = [c for c in rescan_checks if c in static_checks and c not in initial_checks and c != finding.check] if initial_checks else []
    no_new = len(new_checks) == 0

    diff = "".join(line for c in changes for line in difflib.unified_diff(
        c.original.splitlines(True), c.patched.splitlines(True), f"a/{c.label}", f"b/{c.label}"))
    verified = bool(gone and no_new and tests_ok and idempotent)
    fix = Fix(available=True, diff=diff, verified=verified, rescan_passed=gone, tests_passed=tests_ok,
              score_before=score_before, score_after=rescan.score)
    if fix.verified:
        save_golden(template, fix, golden_dir)
    out = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    is_config = template.scanner in ("config_scan", "frontend_scan", "consent_scan")
    statement = "re-scan clean, tests pass, config-only change (not booted)" if is_config else "re-scan clean, tests pass, verified"
    log = {"steps": steps, "total_ms": round((time.monotonic() - started) * 1000),
           "sandbox": sandbox_root, "port": urlparse(url).port,  # the sandbox folder is deleted when the run ends
           "rescan_check": template.scanner, "rescan_findings": len(rescan.findings), "rescan_result": "gone" if gone else "still found",
           "pytest_summary": out[-1] if out else f"pytest exit code {proc.returncode}",
           "statement": statement, "idempotent": idempotent, "no_new_findings": no_new}
    return Verification(fix=fix, rescan=rescan, tests_output="\n".join(proc.stdout.splitlines()[-15:]), log=log)


def verify_notice_align(finding: Finding, repo_path, db_path, *, drift: NoticeDrift | None, tests_dir=None,
                        score_before: int | None = None, golden_dir=GOLDEN_DIR, timeout: float = FIX_TIMEOUT) -> Verification:
    """Add the notice section on a sandbox copy, re-run ONLY notice_drift against it, run the app's tests.
    Verified = nothing undeclared any more AND the tests pass. The purposes stay pending, so that is said in the fix."""
    if drift is None or not drift.undeclared:
        raise PatchError("this scan has no notice drift to align")
    tests_dir = Path(tests_dir or Path(repo_path).parent / "tests")
    deadline = time.monotonic() + timeout
    started = last = time.monotonic()
    steps: list[dict] = []

    def mark(step: str) -> None:
        nonlocal last
        now = time.monotonic()
        steps.append({"step": step, "ms": round((now - last) * 1000)})
        last = now

    with Sandbox(repo_path, db_path, start_timeout=min(START_TIMEOUT, timeout)) as sb:  # the finally in __exit__ kills the process group
        mark("copy")
        notice = sb.repo / "static" / "notice.html"
        try:
            original = notice.read_text()
        except OSError as e:
            raise PatchError(f"cannot read static/notice.html: {e}") from e
        patched = align_notice(original, drift)
        if patched == original:
            raise PatchError("static/notice.html already has the notice-align section")
        notice.write_text(patched)
        mark("patch")
        url = sb.start()
        _left(deadline)
        mark("start")
        after = drift_scan.build(url, str(sb.db))  # only this scanner, the rest of the scan does not matter here
        mark("rescan")
        proc = _run_pytest(tests_dir, url, deadline)
        mark("tests")
        sandbox_root = str(sb.root)

    gone = not after.undeclared
    tests_ok = proc.returncode == 0
    diff = "".join(difflib.unified_diff(original.splitlines(True), patched.splitlines(True),
                                        "a/static/notice.html", "b/static/notice.html"))
    fix = Fix(available=True, diff=diff, verified=gone and tests_ok, rescan_passed=gone, tests_passed=tests_ok,
              score_before=score_before, kind="notice_align", pending_inputs=pending_inputs(drift))
    if fix.verified:
        save_golden(NOTICE_ALIGN, fix, golden_dir)
    out = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    log = {"steps": steps, "total_ms": round((time.monotonic() - started) * 1000),
           "sandbox": sandbox_root, "port": urlparse(url).port,
           "rescan_check": "notice_drift", "rescan_findings": len(after.undeclared),
           "rescan_result": "gone" if gone else "still found",
           "pytest_summary": out[-1] if out else f"pytest exit code {proc.returncode}"}
    return Verification(fix=fix, rescan=None, tests_output="\n".join(proc.stdout.splitlines()[-15:]), log=log)


def save_golden(template: Template, fix: Fix, golden_dir=GOLDEN_DIR) -> None:
    """Only a verified live run is saved. The cached demo mode replays it."""
    Path(golden_dir).mkdir(parents=True, exist_ok=True)
    (Path(golden_dir) / f"{template.golden_id}.json").write_text(json.dumps({
        "golden_id": template.golden_id, "check": template.check, "source": "live",
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "diff": fix.diff, "verified": fix.verified, "rescan_passed": fix.rescan_passed,
        "tests_passed": fix.tests_passed, "kind": fix.kind, "pending_inputs": fix.pending_inputs}, indent=2) + "\n")


def load_golden(golden_id: str, golden_dir=GOLDEN_DIR) -> dict | None:
    try:
        return json.loads((Path(golden_dir) / f"{golden_id}.json").read_text())
    except (OSError, ValueError):
        return None
