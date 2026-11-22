"""Engine API on :8100. Start: uvicorn dpdp_lens.api:app --host 127.0.0.1 --port 8100 (docs/03)."""
import ipaddress
import threading
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .models import ScanResult
from .runner import run_scan

LOCAL_ORIGIN = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"


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


def create_app(scan_fn=run_scan) -> FastAPI:
    app = FastAPI(title="DPDP Lens engine")
    app.add_middleware(CORSMiddleware, allow_origin_regex=LOCAL_ORIGIN, allow_methods=["*"], allow_headers=["*"])
    scans: dict = {}  # scan_id -> {"status": "running"} | ScanResult | {"status": "error", "detail": ...}
    app.state.scans = scans
    lock = threading.Lock()

    def error(status: int, detail: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": HTTPStatus(status).phrase, "detail": detail})

    @app.exception_handler(HTTPException)
    async def _http_error(_, e: HTTPException):
        return error(e.status_code, str(e.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_, e: RequestValidationError):
        return error(422, "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))

    def _run(scan_id: str, req: ScanRequest):
        try:
            scans[scan_id] = scan_fn(req.target_url, req.repo_path, req.db_path, scan_id=scan_id)
        except Exception as e:
            scans[scan_id] = {"status": "error", "detail": f"{type(e).__name__}: {e}"}

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/scan")
    def start_scan(req: ScanRequest, background: BackgroundTasks):
        if not _is_local(req.target_url):
            raise HTTPException(400, "target_url must be http(s) on localhost or a private address")
        if not Path(req.repo_path).is_dir():
            raise HTTPException(400, f"repo_path is not a folder: {req.repo_path}")
        if not Path(req.db_path).is_file():
            raise HTTPException(400, f"db_path is not a file: {req.db_path}")
        with lock:
            scan_id = f"S-{len(scans) + 1:03d}"
            scans[scan_id] = {"status": "running"}
        background.add_task(_run, scan_id, req)
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
    def fix_finding(finding_id: str, scan_id: str):
        raise HTTPException(501, "Fix and verify is not built yet (phase T10)")

    return app


app = create_app()
