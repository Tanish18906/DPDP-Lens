"""Runs the scanners in a fixed order and builds the ScanResult (docs/05 Runner)."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as ScannerTimeout
from datetime import datetime, timezone
from pathlib import Path

from .models import Clause, ScanResult, compute_counts, compute_score
from .scanners import api_scan, db_scan, idor_probe, log_scan

log = logging.getLogger("dpdp_lens")
CLAUSES = Path(__file__).resolve().parents[2] / "contract" / "clauses.json"
SCANNER_TIMEOUT = 30  # seconds, docs/02 rule 5

# (name, fn(target_url, repo_path, db_path) -> list[Finding]). Order matters: it fixes the finding ids.
SCANNERS = [
    ("api_scan", lambda target, repo, db: api_scan.scan(target)),
    ("idor_probe", lambda target, repo, db: idor_probe.scan(target)),
    ("db_scan", lambda target, repo, db: db_scan.scan(db)),
    ("log_scan", lambda target, repo, db: log_scan.scan(repo)),
]


def _run(fn, args, timeout):
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn, *args).result(timeout=timeout)
    finally:
        # shortcut: a hung scanner thread cannot be killed, it is only abandoned. Upgrade to subprocess if it matters.
        pool.shutdown(wait=False)


def run_scan(target_url: str, repo_path: str, db_path: str, scanners=None, timeout: float = SCANNER_TIMEOUT,
             scan_id: str = "S-001") -> ScanResult:
    clauses = json.loads(CLAUSES.read_text())
    findings = []
    for name, fn in SCANNERS if scanners is None else scanners:
        try:
            findings += _run(fn, (target_url, str(repo_path), str(db_path)), timeout)
        except ScannerTimeout:
            log.warning("scanner_error: %s timed out after %ss", name, timeout)
        except Exception as e:  # one scanner must not kill the scan
            log.warning("scanner_error: %s failed: %s: %s", name, type(e).__name__, e)
    findings = [
        f.model_copy(update={"id": f"F-{i:03d}", "clauses": [Clause(**c) for c in clauses.get(f.check, [])]})
        for i, f in enumerate(findings, 1)]
    return ScanResult(
        scan_id=scan_id, target=target_url, scanned_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        score=compute_score(findings), counts=compute_counts(findings), findings=findings)
