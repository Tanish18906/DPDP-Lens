"""Engine API on :8100. Start: uvicorn dpdp_lens.api:app --host 127.0.0.1 --port 8100 (docs/03)."""
import inspect
import json
import logging
import os
import threading
import time
from http import HTTPStatus
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .fixer.templates import TEMPLATES, PatchError
from .fixer.verify import GOLDEN_DIR, load_golden, verify_fix
from .netutil import is_local as _is_local
from .models import Fix, ScanResult, compute_counts, compute_score
from .report import render_report
from .sarif import to_sarif
from .runner import run_scan

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


def create_app(scan_fn=run_scan, repo_root=None, fix_fn=verify_fix, golden_dir=GOLDEN_DIR, state_dir=None) -> FastAPI:
    """state_dir=None keeps everything in memory only (the tests). The real app below passes default_state_dir()."""
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
        with lock:
            scan_id = f"S-{next_n[0]:03d}"
            next_n[0] += 1
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

    @app.get("/report/{scan_id}")
    def get_report(scan_id: str):
        scan = scans.get(scan_id)
        if scan is None:
            raise HTTPException(404, f"Unknown scan {scan_id}")
        if not isinstance(scan, ScanResult):
            if scan["status"] == "running":
                raise HTTPException(409, f"Scan {scan_id} is not finished")
            raise HTTPException(500, scan["detail"])
        return HTMLResponse(render_report(scan, fix_modes.get(scan_id, {})), headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",  # no scripts, nothing external
            "X-Content-Type-Options": "nosniff"})

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
            reason, vlog = None, None  # vlog: the live run's verification log, never set for a cached result
            if mode == "cached":
                golden = load_golden(template.golden_id, golden_dir)
                if golden is None:
                    raise HTTPException(404, f"No cached golden result for {template.golden_id}")
                fix, used = _golden_fix(golden, scan.score), "cached_golden"
            else:
                try:
                    run = fix_fn(finding, *inputs[scan_id], score_before=scan.score, golden_dir=golden_dir)
                    fix, used, vlog = run.fix, "live", run.log or None
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
            fix_modes.setdefault(scan_id, {})[finding_id] = {"mode": used, "fallback_reason": reason}
            save(scan_id)
        return {"finding": fixed, "score_before": scan.score, "score_after": updated.score,
                "mode": used, "fallback_reason": reason, "verification": vlog}

    return app


def _golden_fix(golden: dict, score_before: int) -> Fix:
    """Replay of a saved verified live run. Scores are filled in by the caller's scan, not copied."""
    return Fix(available=True, diff=golden["diff"], verified=golden["verified"], rescan_passed=golden["rescan_passed"],
               tests_passed=golden["tests_passed"], score_before=score_before)


app = create_app(state_dir=default_state_dir())
