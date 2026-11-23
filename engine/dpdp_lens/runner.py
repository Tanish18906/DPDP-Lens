"""Runs the scanners in a fixed order and builds the ScanResult (docs/05 Runner)."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as ScannerTimeout
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import config
from .checks import CHECKS
from .locator import find_column, find_route, find_text
from .models import Clause, Finding, ScanResult, compute_counts, compute_score
from .scanners import api_scan, browser_scan, children_scan, config_scan, contact_scan, frontend_scan, db_scan, erasure_scan, idor_probe, log_scan, notice_drift

log = logging.getLogger("dpdp_lens")
CLAUSES = Path(__file__).resolve().parents[2] / "contract" / "clauses.json"
SCANNER_TIMEOUT = 30  # seconds, docs/02 rule 5

# (name, fn(target_url, repo_path, db_path, frontend_url) -> list[Finding]). Order matters: it fixes the finding ids.
SCANNERS = [
    ("api_scan", lambda target, repo, db, frontend: api_scan.scan(target)),
    ("idor_probe", lambda target, repo, db, frontend: idor_probe.scan(target)),
    ("db_scan", lambda target, repo, db, frontend: db_scan.scan(db)),
    ("log_scan", lambda target, repo, db, frontend: log_scan.scan(repo)),
    ("erasure_scan", lambda target, repo, db, frontend: erasure_scan.scan(target, db)),  # writes a synthetic user, then removes it
    ("children_scan", lambda target, repo, db, frontend: children_scan.scan(target, db)),  # signs up a synthetic minor, then removes it
    ("contact_scan", lambda target, repo, db, frontend: contact_scan.scan(target, frontend)),
    ("browser_scan", lambda target, repo, db, frontend: browser_scan.scan(frontend)),  # opens the frontend in a headless browser
]

# Run after notice_drift, so the ids F-001 to F-010 of the first ten findings do not move (docs/15 D5). Full scans only.
LATE_SCANNERS = [
    ("config_scan", lambda target, repo, db, frontend: config_scan.scan(app_root_of(repo))),  # static, reads files only
    ("frontend_scan", lambda target, repo, db, frontend: frontend_scan.scan(app_root_of(repo))),  # static, reads the front end source
]


def _run(fn, args, timeout):
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn, *args).result(timeout=timeout)
    finally:
        # shortcut: a hung scanner thread cannot be killed, it is only abandoned. Upgrade to subprocess if it matters.
        pool.shutdown(wait=False)


FRONTEND_GLOBS = ["frontend/*.html", "frontend/src/*.jsx", "frontend/src/*.tsx", "frontend/src/*.js"]
ROUTES = {"erasure_incomplete": ("DELETE", "/api/students/{id}"), "children_no_parental_consent": ("POST", "/api/signup")}


def app_root_of(repo_path) -> Path:
    """docs/15 D6: the parent of repo_path when it has a frontend folder, else repo_path."""
    repo = Path(repo_path).resolve()
    return repo.parent if (repo.parent / "frontend").is_dir() else repo


def _where(f: Finding, root: Path) -> tuple[str, int]:
    loc, check = f.evidence.location, f.check
    if check in ("api_pii_exposure", "api_idor"):
        return find_route(root, "GET", urlparse(loc.url).path)
    if check in ROUTES:
        return find_route(root, *ROUTES[check])
    if check == "db_plaintext_pii":
        return find_column(root, loc.table, loc.column.split(",")[0].strip())
    if check == "tracker_before_consent":
        return find_text(root, urlparse(f.evidence.masked_sample).hostname or "", FRONTEND_GLOBS)
    if check == "consent_bundled":
        return find_text(root, 'type="checkbox"', FRONTEND_GLOBS)
    if check == "missing_contact":
        return find_text(root, "<h1", ["*notice.html"])
    if check == "notice_drift":
        return find_text(root, "<li", ["*notice.html"])
    return "", 0


def locate(findings: list[Finding], repo_path) -> list[Finding]:
    """Fill evidence.location.file and .line when the scanner left them empty. A scanner's own file (log_pii) is
    only rebased from repo_path to app_root so every path in a report has the same base."""
    repo, root = Path(repo_path).resolve(), app_root_of(repo_path)
    out = []
    for f in findings:
        loc = f.evidence.location
        if loc.file:
            # shortcut: a file that exists under repo_path is treated as relative to it (log_pii), else as relative to app_root (config_scan)
            file, line = ((repo / loc.file).relative_to(root).as_posix() if (repo / loc.file).exists() else loc.file), loc.line
        else:
            file, line = _where(f, root)
        out.append(f.model_copy(update={"evidence": f.evidence.model_copy(
            update={"location": loc.model_copy(update={"file": file, "line": line})})}))
    return out


_CONFIG = object()  # frontend_url default: use config.FRONTEND_URL


def run_scan(target_url: str, repo_path: str, db_path: str, scanners=None, timeout: float = SCANNER_TIMEOUT,
             scan_id: str = "S-001", frontend_url=_CONFIG, errors: list | None = None, progress=None) -> ScanResult:
    """errors, if given, collects "scanner: message" for every scanner that failed or timed out.
    progress, if given, is called as progress(step_name, steps_done, steps_total) before each step."""
    frontend = config.FRONTEND_URL if frontend_url is _CONFIG else frontend_url
    clauses = json.loads(CLAUSES.read_text())
    findings = []
    todo = SCANNERS if scanners is None else scanners
    late = LATE_SCANNERS if scanners is None else []
    total = len(todo) + (scanners is None) + len(late)  # the full scan has notice_drift and the late scanners on top

    def step(name, fn, i):
        progress and progress(name, i, total)
        try:
            findings.extend(_run(fn, (target_url, str(repo_path), str(db_path), frontend), timeout))
        except ScannerTimeout:
            log.warning("scanner_error: %s timed out after %ss", name, timeout)
            errors is None or errors.append(f"{name}: timed out after {timeout}s")
        except Exception as e:  # one scanner must not kill the scan
            log.warning("scanner_error: %s failed: %s: %s", name, type(e).__name__, e)
            errors is None or errors.append(f"{name}: {type(e).__name__}: {e}")

    for i, (name, fn) in enumerate(todo):
        step(name, fn, i)
    drift = None
    if scanners is None:  # the full scan also compares the privacy notice with what the app handles
        progress and progress("notice_drift", len(todo), total)
        try:
            drift = _run(notice_drift.build, (target_url, str(db_path), app_root_of(repo_path)), timeout)
            if drift.undeclared:
                findings.append(notice_drift.finding(drift, f"{target_url.rstrip('/')}/notice"))
        except ScannerTimeout:
            log.warning("scanner_error: notice_drift timed out after %ss", timeout)
        except Exception as e:
            log.warning("scanner_error: notice_drift failed: %s: %s", type(e).__name__, e)
    for j, (name, fn) in enumerate(late):
        step(name, fn, len(todo) + 1 + j)
    findings = [
        f.model_copy(update={"id": f"F-{i:03d}", "clauses": [Clause(**c) for c in clauses.get(f.check, [])],
                             "recommendation": CHECKS[f.check].recommendation if f.check in CHECKS else ""})
        for i, f in enumerate(locate(findings, repo_path), 1)]
    return ScanResult(
        scan_id=scan_id, target=target_url, scanned_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        score=compute_score(findings), counts=compute_counts(findings), findings=findings, notice_drift=drift)
