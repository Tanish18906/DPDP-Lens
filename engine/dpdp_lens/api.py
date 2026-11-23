"""Engine API on :8100. Start: uvicorn dpdp_lens.api:app --host 127.0.0.1 --port 8100 (docs/03)."""
import inspect
import json
import logging
import os
import threading
import time
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from fastapi import BackgroundTasks, Body, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from .api_v2 import create_router, require_token
from .monitor import attach_monitor
from .fixer.notice_align import NOTICE_ALIGN
from .fixer.templates import TEMPLATES, PatchError
from .fixer.verify import GOLDEN_DIR, load_golden, verify_fix
from .netutil import is_local as _is_local
from .models import Fix, ScanResult, compute_counts, compute_score
from .report import render_pdf, render_report
from .sarif import to_sarif
from .runner import run_scan
from .store import Store

log = logging.getLogger("dpdp_lens")
LOCAL_ORIGIN = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"


def default_repo_root() -> Path:
    """Scans are limited to this folder. DPDP_REPO_ROOT overrides the repo root found from the package location."""
    return Path(os.environ.get("DPDP_REPO_ROOT") or Path(__file__).resolve().parents[2]).resolve()


class ScanRequest(BaseModel):
    target_url: str
    repo_path: str
    db_path: str


def default_state_dir() -> Path:
    """Finished scans are saved here so an engine restart keeps them. DPDP_STATE_DIR overrides it."""
    return Path(os.environ.get("DPDP_STATE_DIR") or default_repo_root() / ".dpdp-state")


def default_db_path() -> Path:
    """The finding store (repos, findings, audit events). DPDP_DB overrides it."""
    return Path(os.environ.get("DPDP_DB") or default_state_dir() / "dpdp.db")


def create_app(scan_fn=run_scan, repo_root=None, fix_fn=verify_fix, golden_dir=GOLDEN_DIR, state_dir=None,
               pdf_fn=render_pdf, store=None) -> FastAPI:
    """state_dir=None keeps everything in memory only (the tests). The real app below passes default_state_dir().
    store=None leaves out the repo, finding and audit routes (api_v2). Pass Store(":memory:") in tests that need them."""
    root = Path(repo_root).resolve() if repo_root else default_repo_root()
    app = FastAPI(title="DPDP Lens engine")
    app.add_middleware(CORSMiddleware, allow_origin_regex=LOCAL_ORIGIN, allow_methods=["*"], allow_headers=["*"])
    scans: dict = {}  # scan_id -> {"status": "running"} | ScanResult | {"status": "error", "detail": ...}
    inputs: dict = {}  # scan_id -> (repo_path, db_path), needed to fix a finding later
    app.state.scans = scans
    lock = threading.Lock()
    fix_lock = threading.Lock()
    fix_modes: dict = {}  # scan_id -> {finding_id: {mode, fallback_reason}}, so the report never shows a cached fix as live
    timings: dict = {}  # scan_id -> [{step, ms}], measured while the scan runs (memory only)
    state = Path(state_dir) if state_dir else None
    next_n = [1]
    takes_progress = "progress" in inspect.signature(scan_fn).parameters

    def save(scan_id: str):
        """Write a finished scan, its inputs and its fix modes to disk. A disk problem must never break a scan."""
        if state is None or not isinstance(scans.get(scan_id), ScanResult):
            return
        try:
            state.mkdir(parents=True, exist_ok=True)
            tmp = state / f"{scan_id}.json.tmp"
            tmp.write_text(json.dumps({"scan": scans[scan_id].model_dump(mode="json"), "inputs": list(inputs[scan_id]),
                                       "fix_modes": fix_modes.get(scan_id, {})}))
            tmp.replace(state / f"{scan_id}.json")  # atomic, no half-written file
        except OSError as e:
            log.warning("could not save %s: %s", scan_id, e)

    for f in sorted(state.glob("S-*.json")) if state and state.is_dir() else []:
        try:
            d = json.loads(f.read_text())
            scans[f.stem], inputs[f.stem], fix_modes[f.stem] = ScanResult.model_validate(d["scan"]), tuple(d["inputs"]), d["fix_modes"]
            next_n[0] = max(next_n[0], int(f.stem[2:]) + 1)
        except (OSError, ValueError, KeyError) as e:
            log.warning("skipped unreadable state file %s: %s", f.name, e)

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

    def new_scan_id(scan_inputs: tuple) -> str:
        """The next S-NNN. Legacy scans and repo scans (api_v2) share one counter, one dict and the state files."""
        with lock:
            scan_id = f"S-{next_n[0]:03d}"
            next_n[0] += 1
            scans[scan_id] = {"status": "running"}
            inputs[scan_id] = scan_inputs
        return scan_id

    def _run(scan_id: str, target_url: str, repo_path: str, db_path: str):
        steps = timings.setdefault(scan_id, [])  # finished steps with their measured ms
        current = {"step": None, "at": time.monotonic()}

        def finish_step():
            if current["step"]:
                steps.append({"step": current["step"], "ms": round((time.monotonic() - current["at"]) * 1000)})

        def progress(step, done, total):
            finish_step()
            current.update(step=step, at=time.monotonic())
            scans.update({scan_id: {"status": "running", "step": step, "done": done, "total": total, "steps_ms": list(steps)}})

        kw = {"progress": progress} if takes_progress else {}
        try:
            scans[scan_id] = scan_fn(target_url, repo_path, db_path, scan_id=scan_id, **kw)
            finish_step()
            save(scan_id)
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
        scan_id = new_scan_id((str(repo_path), str(db_path)))
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

    @app.get("/scan/{scan_id}/sarif")
    def get_sarif(scan_id: str):
        scan = scans.get(scan_id)
        if not isinstance(scan, ScanResult):
            raise HTTPException(404 if scan is None else 409, f"No finished scan {scan_id}")
        return to_sarif(scan)

    @app.get("/scan/{scan_id}/timings")
    def get_timings(scan_id: str):
        """Measured duration of each scan step (kept in memory only, so empty after an engine restart)."""
        if scan_id not in scans:
            raise HTTPException(404, f"Unknown scan {scan_id}")
        return {"steps": timings.get(scan_id, [])}

    def _finished(scan_id: str) -> ScanResult:
        scan = scans.get(scan_id)
        if scan is None:
            raise HTTPException(404, f"Unknown scan {scan_id}")
        if not isinstance(scan, ScanResult):
            if scan["status"] == "running":
                raise HTTPException(409, f"Scan {scan_id} is not finished")
            raise HTTPException(500, scan["detail"])
        return scan

    # Registered before /report/{scan_id}, which would otherwise take "S-001.pdf" as a scan id.
    @app.get("/report/{scan_id}.pdf")
    def get_report_pdf(scan_id: str):
        scan = _finished(scan_id)
        try:
            pdf = pdf_fn(render_report(scan, fix_modes.get(scan_id, {})), scan_id)
        except Exception as e:  # no Playwright or no browser on this machine
            log.warning("pdf_error %s: %s", scan_id, str(e).splitlines()[0][:200] if str(e) else type(e).__name__)
            raise HTTPException(503, "PDF needs Chromium or Chrome, use the HTML report")
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="dpdp-lens-{scan_id}.pdf"'})

    @app.get("/report/{scan_id}")
    def get_report(scan_id: str):
        scan = _finished(scan_id)
        return HTMLResponse(render_report(scan, fix_modes.get(scan_id, {})), headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",  # no scripts, nothing external
            "X-Content-Type-Options": "nosniff"})

    @app.post("/findings/{finding_id}/fix")
    def fix_finding(finding_id: str, scan_id: str | None = None, mode: Literal["live", "cached"] = "live", body: dict | None = Body(None),
                    x_dpdp_token: str | None = Header(None)):
        if finding_id.startswith("DPDP-") and store is not None:  # a stored finding: api_v2 owns it (FIX_REPOS, audit)
            require_token(x_dpdp_token)
            return core.fix_human(finding_id, mode, str((body or {}).get("actor") or "api")[:100])
        if scan_id is None:
            raise HTTPException(422, "query.scan_id: Field required")
        scan = scans.get(scan_id)
        if scan is None:
            raise HTTPException(404, f"Unknown scan {scan_id}")
        if not isinstance(scan, ScanResult):
            raise HTTPException(409, f"Scan {scan_id} is not finished")
        if inputs[scan_id][0].startswith("repo:"):
            raise HTTPException(409, "this is a connected repo scan: fix its findings with POST /findings/DPDP-NNN/fix")
        with fix_lock:
            try:
                fixed, updated, used, reason, vlog = apply_fix(
                    scan, finding_id, *inputs[scan_id], mode=mode, fix_fn=fix_fn, golden_dir=golden_dir)
            except FixError as e:
                raise HTTPException(e.status, e.detail)
            scans[scan_id] = updated
            fix_modes.setdefault(scan_id, {})[finding_id] = {"mode": used, "fallback_reason": reason}
            save(scan_id)
        return {"finding": fixed, "score_before": scan.score, "score_after": updated.score,
                "mode": used, "fallback_reason": reason, "verification": vlog}

    core = SimpleNamespace(scans=scans, inputs=inputs, save=save, new_scan_id=new_scan_id, fix_lock=fix_lock, fix_fn=fix_fn, golden_dir=golden_dir, store=store)
    app.state.core = core
    if store is not None:
        app.include_router(create_router(store, core))
    return app


class FixError(Exception):
    """A fix that cannot run. `status` is the HTTP status the API answers with, the shell only prints `detail`."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def apply_fix(scan: ScanResult, finding_id: str, repo_path, db_path, *, mode="live", fix_fn=verify_fix,
              golden_dir=GOLDEN_DIR):
    """Fix one finding of a finished scan. Returns (fixed finding, updated scan, "live"|"cached_golden", fallback
    reason, verification log). Raises FixError. Shared by POST /findings/{id}/fix and the shell."""
    finding = next((f for f in scan.findings if f.id == finding_id), None)
    if finding is None:
        raise FixError(404, f"Unknown finding {finding_id} in scan {scan.scan_id}")
    template = NOTICE_ALIGN if finding.check == "notice_drift" else TEMPLATES.get(finding.check)
    if not finding.fix.available or template is None:
        raise FixError(400, f"No automated fix for {finding.check}")
    if finding.status == "verified_fixed":
        raise FixError(409, f"{finding_id} is already fixed")

    reason, vlog = None, None  # vlog: the live run's verification log, never set for a cached result
    if mode == "cached":
        golden = load_golden(template.golden_id, golden_dir)
        if golden is None:
            raise FixError(404, f"No cached golden result for {template.golden_id}")
        fix, used = _golden_fix(golden, scan.score), "cached_golden"
    else:
        try:
            extra = {"drift": scan.notice_drift} if finding.check == "notice_drift" else {}
            run = fix_fn(finding, repo_path, db_path, score_before=scan.score, golden_dir=golden_dir, **extra)
            fix, used, vlog = run.fix, "live", run.log or None
        except PatchError as e:
            raise FixError(422, f"The patch does not apply: {e}")
        except Exception as e:  # sandbox, timeout or other trouble: the live run could not finish
            reason = f"{type(e).__name__}: {e}"
            golden = load_golden(template.golden_id, golden_dir)
            if golden is None:
                raise FixError(502, f"Live fix failed ({reason}) and no cached golden result exists")
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
    return fixed, updated, used, reason, vlog


def _golden_fix(golden: dict, score_before: int) -> Fix:
    """Replay of a saved verified live run. Scores are filled in by the caller's scan, not copied."""
    return Fix(available=True, diff=golden["diff"], verified=golden["verified"], rescan_passed=golden["rescan_passed"],
               tests_passed=golden["tests_passed"], score_before=score_before,
               kind=golden.get("kind"), pending_inputs=golden.get("pending_inputs"))


app = create_app(state_dir=default_state_dir(), store=Store(default_db_path()))
attach_monitor(app)  # starts when the server starts, never under pytest, never when DPDP_MONITOR=0
