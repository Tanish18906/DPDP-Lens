"""Runs the scanners in a fixed order and builds the ScanResult (docs/05 Runner)."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as ScannerTimeout
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .models import Clause, ScanResult, compute_counts, compute_score
from .scanners import api_scan, browser_scan, children_scan, contact_scan, db_scan, erasure_scan, idor_probe, log_scan, notice_drift

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


def _run(fn, args, timeout):
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn, *args).result(timeout=timeout)
    finally:
        # shortcut: a hung scanner thread cannot be killed, it is only abandoned. Upgrade to subprocess if it matters.
        pool.shutdown(wait=False)


_CONFIG = object()  # frontend_url default: use config.FRONTEND_URL


def run_scan(target_url: str, repo_path: str, db_path: str, scanners=None, timeout: float = SCANNER_TIMEOUT,
             scan_id: str = "S-001", frontend_url=_CONFIG, errors: list | None = None) -> ScanResult:
    """errors, if given, collects "scanner: message" for every scanner that failed or timed out."""
    frontend = config.FRONTEND_URL if frontend_url is _CONFIG else frontend_url
    clauses = json.loads(CLAUSES.read_text())
    findings = []
    for name, fn in SCANNERS if scanners is None else scanners:
        try:
            findings += _run(fn, (target_url, str(repo_path), str(db_path), frontend), timeout)
        except ScannerTimeout:
            log.warning("scanner_error: %s timed out after %ss", name, timeout)
            errors is None or errors.append(f"{name}: timed out after {timeout}s")
        except Exception as e:  # one scanner must not kill the scan
            log.warning("scanner_error: %s failed: %s: %s", name, type(e).__name__, e)
            errors is None or errors.append(f"{name}: {type(e).__name__}: {e}")
    drift = None
    if scanners is None:  # the full scan also compares the privacy notice with what the app handles
        try:
            drift = _run(notice_drift.build, (target_url, str(db_path)), timeout)
            if drift.undeclared:
                findings.append(notice_drift.finding(drift, f"{target_url.rstrip('/')}/notice"))
        except ScannerTimeout:
            log.warning("scanner_error: notice_drift timed out after %ss", timeout)
        except Exception as e:
            log.warning("scanner_error: notice_drift failed: %s: %s", type(e).__name__, e)
    findings = [
        f.model_copy(update={"id": f"F-{i:03d}", "clauses": [Clause(**c) for c in clauses.get(f.check, [])]})
        for i, f in enumerate(findings, 1)]
    return ScanResult(
        scan_id=scan_id, target=target_url, scanned_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        score=compute_score(findings), counts=compute_counts(findings), findings=findings, notice_drift=drift)
