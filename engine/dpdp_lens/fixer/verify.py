"""Fix and verify: patch a sandbox copy, re-scan it, run the app's tests, build the diff.
`verified` is computed here from the re-scan and the pytest exit code. Nothing sets it by hand."""
import difflib
import json
import os
import py_compile
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from ..models import Finding, Fix, ScanResult
from ..runner import SCANNER_TIMEOUT, run_scan
from .sandbox import START_TIMEOUT, Sandbox
from .templates import TEMPLATES, PatchError, Template, apply_template

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "data" / "golden"
FIX_TIMEOUT = 60  # seconds for the whole live run


class FixTimeout(Exception):
    pass


@dataclass
class Verification:
    fix: Fix
    rescan: ScanResult
    tests_output: str


def _key(f: Finding):
    """Same problem in a re-scan: same check at the same URL path, file, table and column."""
    loc = f.evidence.location
    return (f.check, urlparse(loc.url).path, loc.file, loc.table, loc.column)


def _left(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise FixTimeout(f"fix and verify took longer than {FIX_TIMEOUT} seconds")
    return left


def verify_fix(finding: Finding, repo_path, db_path, *, tests_dir=None, frontend_dir=None, template: Template | None = None,
               score_before: int | None = None, golden_dir=GOLDEN_DIR, timeout: float = FIX_TIMEOUT) -> Verification:
    template = template or TEMPLATES.get(finding.check)
    if template is None:
        raise PatchError(f"no fix template for {finding.check}")
    tests_dir = Path(tests_dir or Path(repo_path).parent / "tests")
    frontend_dir = Path(frontend_dir or Path(repo_path).parent / "frontend") if template.needs_frontend else None
    deadline = time.monotonic() + timeout

    with Sandbox(repo_path, db_path, start_timeout=min(START_TIMEOUT, timeout), frontend_path=frontend_dir) as sb:
        changes = apply_template(template, {"backend": sb.repo, "frontend": sb.frontend})
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
        url = sb.start()
        if template.needs_frontend:
            extra["frontend_url"] = sb.start_frontend()  # the re-scan looks at the patched page, not the original
        _left(deadline)
        # Re-scan first: pytest signs users up and deletes them, which would change the sandbox DB and the score.
        errors: list[str] = []
        rescan = run_scan(url, str(sb.repo), str(sb.db), timeout=min(SCANNER_TIMEOUT, _left(deadline)), errors=errors, **extra)
        broken = [e for e in errors if e.startswith(f"{template.scanner}:")]
        if broken:  # a scanner that could not run must never read as "the finding is gone"
            raise RuntimeError(f"the re-scan could not run {template.scanner}: {broken[0]}")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", str(tests_dir), "-q", "-p", "no:cacheprovider"],
                cwd=tests_dir, capture_output=True, text=True, timeout=_left(deadline),
                env={**os.environ, "TUTORNEST_BASE_URL": url, "PYTHONDONTWRITEBYTECODE": "1"})  # original folder stays untouched
        except subprocess.TimeoutExpired as e:
            raise FixTimeout("the app's tests did not finish in time") from e

    gone = all(_key(f) != _key(finding) for f in rescan.findings)
    tests_ok = proc.returncode == 0  # for a frontend patch this also means the patched frontend built
    diff = "".join(line for c in changes for line in difflib.unified_diff(
        c.original.splitlines(True), c.patched.splitlines(True), f"a/{c.label}", f"b/{c.label}"))
    fix = Fix(available=True, diff=diff, verified=gone and tests_ok, rescan_passed=gone, tests_passed=tests_ok,
              score_before=score_before, score_after=rescan.score)
    if fix.verified:
        save_golden(template, fix, golden_dir)
    return Verification(fix=fix, rescan=rescan, tests_output="\n".join(proc.stdout.splitlines()[-15:]))


def save_golden(template: Template, fix: Fix, golden_dir=GOLDEN_DIR) -> None:
    """Only a verified live run is saved. The cached demo mode replays it."""
    Path(golden_dir).mkdir(parents=True, exist_ok=True)
    (Path(golden_dir) / f"{template.golden_id}.json").write_text(json.dumps({
        "golden_id": template.golden_id, "check": template.check, "source": "live",
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "diff": fix.diff, "verified": fix.verified, "rescan_passed": fix.rescan_passed,
        "tests_passed": fix.tests_passed}, indent=2) + "\n")


def load_golden(golden_id: str, golden_dir=GOLDEN_DIR) -> dict | None:
    try:
        return json.loads((Path(golden_dir) / f"{golden_id}.json").read_text())
    except (OSError, ValueError):
        return None
