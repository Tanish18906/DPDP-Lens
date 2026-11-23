"""Runs the scanners in a fixed order and builds the ScanResult (docs/05 Runner)."""
import json
import logging
from importlib import metadata
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as ScannerTimeout
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import config
from .checks import CHECKS
from .fingerprint import fingerprints
from .locator import Capped, find_column, find_route, find_text
from .models import Clause, Coverage, Finding, ScanError, ScanResult, compute_counts, compute_score
from .scanners import api_scan, browser_scan, children_scan, config_scan, consent_scan, contact_scan, frontend_scan, db_scan, erasure_scan, idor_probe, log_scan, notice_drift

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
    ("consent_scan", lambda target, repo, db, frontend: consent_scan.scan(target, app_root_of(repo))),  # schema and source, plus the OpenAPI spec
]

# scanner name -> the check ids it can produce. Coverage is built from this: a check is "run" when its scanner finished.
SCANNER_CHECKS = {
    "api_scan": ["api_pii_exposure"], "idor_probe": ["api_idor"], "db_scan": ["db_plaintext_pii"], "log_scan": ["log_pii"],
    "erasure_scan": ["erasure_incomplete"], "children_scan": ["children_no_parental_consent"], "contact_scan": ["missing_contact"],
    "browser_scan": ["tracker_before_consent", "consent_bundled"], "notice_drift": ["notice_drift"],
    "config_scan": ["config_secret_committed", "config_env_in_image", "config_container_root", "config_cors_wildcard",
                    "config_debug_enabled", "config_db_exposed"],
    "frontend_scan": ["fe_pii_in_storage"], "consent_scan": ["consent_not_recorded", "consent_no_withdrawal"]}
# Static mode: no live app, no database. Only these scanners run, and consent_scan only does its source half.
STATIC_SCANNERS = ["log_scan", "config_scan", "frontend_scan", "consent_scan"]
STATIC_CHECKS = {"consent_scan": ["consent_not_recorded"]}


def _run(fn, args, timeout):
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn, *args).result(timeout=timeout)
    finally:
        # shortcut: a hung scanner thread cannot be killed, it is only abandoned. Upgrade to subprocess if it matters.
        pool.shutdown(wait=False)


FRONTEND_GLOBS = ["frontend/*.html", "frontend/src/*.jsx", "frontend/src/*.tsx", "frontend/src/*.js"]
ROUTES = {"erasure_incomplete": ("DELETE", "/api/students/{id}"), "children_no_parental_consent": ("POST", "/api/signup"),
          "consent_not_recorded": ("POST", "/api/signup"), "consent_no_withdrawal": ("POST", "/api/signup")}  # the signup handler


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


def _version() -> str:
    try:
        return metadata.version("dpdp_lens")
    except metadata.PackageNotFoundError:
        return "0.1.0"


def run_scan(target_url: str, repo_path: str, db_path: str, scanners=None, timeout: float = SCANNER_TIMEOUT,
             scan_id: str = "S-001", frontend_url=_CONFIG, errors: list | None = None, progress=None, found=None,
             mode: str = "full") -> ScanResult:
    """errors, if given, also collects "scanner: message" for every scanner that failed, timed out or hit a cap
    (the same entries are always in ScanResult.scan_errors, and any of them sets complete=False).
    progress, if given, is called as progress(step_name, steps_done, steps_total) before each step.
    found, if given, is called as found(step_name, n) after each step: n findings, or None when the step failed.
    mode="static" runs only the scanners that read files (STATIC_SCANNERS), so target_url and db_path may be empty."""
    static = mode == "static" and scanners is None
    frontend = config.FRONTEND_URL if frontend_url is _CONFIG else frontend_url
    clauses = json.loads(CLAUSES.read_text())
    findings, scan_errors, finished = [], [], []
    if scanners is not None:
        todo, late, drift_step = scanners, [], False
    elif static:
        todo, late, drift_step = [s for s in SCANNERS + LATE_SCANNERS if s[0] in STATIC_SCANNERS], [], False
    else:
        todo, late, drift_step = SCANNERS, LATE_SCANNERS, True  # the full scan has notice_drift and the late scanners on top
    total = len(todo) + drift_step + len(late)

    def attempt(name, fn, args, i):
        """(result, True) or (None, False). A failure is recorded in scan_errors and never reads as "no findings"."""
        progress and progress(name, i, total)
        try:
            result = _run(fn, args, timeout)
            finished.append(name)
            return result, True
        except ScannerTimeout:
            kind, message = "timeout", f"timed out after {timeout}s"
            log.warning("scanner_error: %s timed out after %ss", name, timeout)
        except Capped as e:
            kind, message = "capped", str(e)
            log.warning("scanner_error: %s hit a scan limit: %s", name, e)
        except Exception as e:  # one scanner must not kill the scan
            kind, message = "failed", f"{type(e).__name__}: {e}"
            log.warning("scanner_error: %s failed: %s: %s", name, type(e).__name__, e)
        message = " ".join(message.split())[:300]
        scan_errors.append(ScanError(scanner=name, kind=kind, message=message))
        errors is None or errors.append(f"{name}: {message}")
        return None, False

    def step(name, fn, i):
        new, good = attempt(name, fn, (target_url, str(repo_path), str(db_path), frontend), i)
        good and findings.extend(new)
        found and found(name, len(new) if good else None)

    for i, (name, fn) in enumerate(todo):
        step(name, fn, i)
    drift = None
    if drift_step:  # the full scan also compares the privacy notice with what the app handles
        built, good = attempt("notice_drift", notice_drift.build, (target_url, str(db_path), app_root_of(repo_path)), len(todo))
        n = None
        if good:
            drift, n = built, 0
            if drift.undeclared:
                findings.append(notice_drift.finding(drift, f"{target_url.rstrip('/')}/notice"))
                n = 1
        found and found("notice_drift", n)
    for j, (name, fn) in enumerate(late):
        step(name, fn, len(todo) + 1 + j)
    located = locate(findings, repo_path)
    prints = fingerprints(located, app_root_of(repo_path))
    findings = [
        f.model_copy(update={"id": f"F-{i:03d}", "clauses": [Clause(**c) for c in clauses.get(f.check, [])],
                             "recommendation": CHECKS[f.check].recommendation if f.check in CHECKS else "",
                             "proof": CHECKS[f.check].proof if f.check in CHECKS else "static", "fingerprint": prints[i - 1]})
        for i, f in enumerate(located, 1)]
    return ScanResult(
        scan_id=scan_id, target=target_url, scanned_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        score=compute_score(findings), counts=compute_counts(findings), findings=findings, notice_drift=drift,
        scan_errors=scan_errors, complete=not scan_errors, scanner_version=_version(),
        coverage=_coverage(finished, scan_errors, "static" if static else "full"))


def _coverage(finished: list[str], scan_errors: list[ScanError], mode: str) -> Coverage:
    """checks_run: checks of scanners that finished. scanners_failed: their checks are neither run nor skipped.
    checks_skipped: every other check (not attempted, for example the live checks of a static scan)."""
    own = lambda name: (STATIC_CHECKS if mode == "static" else {}).get(name, SCANNER_CHECKS.get(name, []))  # noqa: E731
    failed = list(dict.fromkeys(e.scanner for e in scan_errors))
    run = {c for n in finished for c in own(n)}
    lost = {c for n in failed for c in own(n)}
    return Coverage(mode=mode, checks_run=[c for c in CHECKS if c in run], scanners_failed=failed,
                    checks_skipped=[c for c in CHECKS if c not in run and c not in lost])
