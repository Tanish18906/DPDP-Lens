"""Engine API on :8100. Start: uvicorn dpdp_lens.api:app --host 127.0.0.1 --port 8100 (docs/03)."""
import ipaddress
import os
import threading
from http import HTTPStatus
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .fixer.templates import TEMPLATES, PatchError
from .fixer.verify import GOLDEN_DIR, load_golden, verify_fix
from .models import Fix, ScanResult, compute_counts, compute_score
from .runner import run_scan

LOCAL_ORIGIN = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"


def default_repo_root() -> Path:
    """Scans are limited to this folder. DPDP_REPO_ROOT overrides the repo root found from the package location."""
    return Path(os.environ.get("DPDP_REPO_ROOT") or Path(__file__).resolve().parents[2]).resolve()


class ScanRequest(BaseModel):
    target_url: str
    repo_path: str
    db_path: str


def _is_local(url: str) -> bool:
    """Threat T3: only scan localhost or private addresses."""
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme not in ("http", "https") or not host:
        return False
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def create_app(scan_fn=run_scan, repo_root=None, fix_fn=verify_fix, golden_dir=GOLDEN_DIR) -> FastAPI:
    root = Path(repo_root).resolve() if repo_root else default_repo_root()
    app = FastAPI(title="DPDP Lens engine")
    app.add_middleware(CORSMiddleware, allow_origin_regex=LOCAL_ORIGIN, allow_methods=["*"], allow_headers=["*"])
    scans: dict = {}  # scan_id -> {"status": "running"} | ScanResult | {"status": "error", "detail": ...}
    inputs: dict = {}  # scan_id -> (repo_path, db_path), needed to fix a finding later
    app.state.scans = scans
    lock = threading.Lock()
    fix_lock = threading.Lock()

    def error(status: int, detail: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": HTTPStatus(status).phrase, "detail": detail})

    @app.exception_handler(HTTPException)
    async def _http_error(_, e: HTTPException):
        return error(e.status_code, str(e.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_, e: RequestValidationError):
        return error(422, "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))

    def _inside_root(name: str, given: str) -> Path:
        """Relative paths resolve against the repo root. '..' and symlinks are resolved before the check."""
        path = (root / given).resolve()
        if not path.is_relative_to(root):
            raise HTTPException(400, f"{name} must be inside the project folder ({root}): {given}")
        return path

    def _run(scan_id: str, target_url: str, repo_path: str, db_path: str):
        try:
            scans[scan_id] = scan_fn(target_url, repo_path, db_path, scan_id=scan_id)
        except Exception as e:
            scans[scan_id] = {"status": "error", "detail": f"{type(e).__name__}: {e}"}

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/scan")
    def start_scan(req: ScanRequest, background: BackgroundTasks):
        if not _is_local(req.target_url):
            raise HTTPException(400, "target_url must be http(s) on localhost or a private address")
        repo_path = _inside_root("repo_path", req.repo_path)
        db_path = _inside_root("db_path", req.db_path)
        if not repo_path.is_dir():
            raise HTTPException(400, f"repo_path is not a folder: {req.repo_path}")
        if not db_path.is_file():
            raise HTTPException(400, f"db_path is not a file: {req.db_path}")
        with lock:
            scan_id = f"S-{len(scans) + 1:03d}"
            scans[scan_id] = {"status": "running"}
            inputs[scan_id] = (str(repo_path), str(db_path))
        background.add_task(_run, scan_id, req.target_url, str(repo_path), str(db_path))
        return {"scan_id": scan_id}

    @app.get("/scan/{scan_id}")
    def get_scan(scan_id: str):
        scan = scans.get(scan_id)
        if scan is None:
            raise HTTPException(404, f"Unknown scan {scan_id}")
        if isinstance(scan, ScanResult) or scan["status"] == "running":
            return scan
        raise HTTPException(500, scan["detail"])

    @app.post("/findings/{finding_id}/fix")
    def fix_finding(finding_id: str, scan_id: str, mode: Literal["live", "cached"] = "live"):
        scan = scans.get(scan_id)
        if scan is None:
            raise HTTPException(404, f"Unknown scan {scan_id}")
        if not isinstance(scan, ScanResult):
            raise HTTPException(409, f"Scan {scan_id} is not finished")
        finding = next((f for f in scan.findings if f.id == finding_id), None)
        if finding is None:
            raise HTTPException(404, f"Unknown finding {finding_id} in scan {scan_id}")
        template = TEMPLATES.get(finding.check)
        if not finding.fix.available or template is None:
            raise HTTPException(400, f"No automated fix for {finding.check}")
        if finding.status == "verified_fixed":
            raise HTTPException(409, f"{finding_id} is already fixed")

        with fix_lock:
            reason = None
            if mode == "cached":
                golden = load_golden(template.golden_id, golden_dir)
                if golden is None:
                    raise HTTPException(404, f"No cached golden result for {template.golden_id}")
                fix, used = _golden_fix(golden, scan.score), "cached_golden"
            else:
                try:
                    fix, used = fix_fn(finding, *inputs[scan_id], score_before=scan.score, golden_dir=golden_dir).fix, "live"
                except PatchError as e:
                    raise HTTPException(422, f"The patch does not apply: {e}")
                except Exception as e:  # sandbox, timeout or other trouble: the live run could not finish
                    reason = f"{type(e).__name__}: {e}"
                    golden = load_golden(template.golden_id, golden_dir)
                    if golden is None:
                        raise HTTPException(502, f"Live fix failed ({reason}) and no cached golden result exists")
                    fix, used = _golden_fix(golden, scan.score), "cached_golden"

            status = "verified_fixed" if fix.verified else "open"
            if fix.verified or fix.score_after is None:
                # Score the stored scan (open findings only). Each fix is verified on its own copy of the original app,
                # so a re-scan alone would not include fixes verified earlier. A cached replay has no score of its own.
                fix = fix.model_copy(update={"score_after": compute_score(
                    [f.model_copy(update={"status": status}) if f.id == finding_id else f for f in scan.findings])})
            fixed = finding.model_copy(update={"status": status, "fix": fix})
            findings = [fixed if f.id == finding_id else f for f in scan.findings]
            updated = scan.model_copy(update={
                "findings": findings, "score": compute_score(findings), "counts": compute_counts(findings)})
            scans[scan_id] = updated
        return {"finding": fixed, "score_before": scan.score, "score_after": updated.score,
                "mode": used, "fallback_reason": reason}

    return app


def _golden_fix(golden: dict, score_before: int) -> Fix:
    """Replay of a saved verified live run. Scores are filled in by the caller's scan, not copied."""
    return Fix(available=True, diff=golden["diff"], verified=golden["verified"], rescan_passed=golden["rescan_passed"],
               tests_passed=golden["tests_passed"], score_before=score_before)


app = create_app()
