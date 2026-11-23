"""Repo, finding, audit and outbox routes (docs/dpdp-evolve master section 9). Built by `create_router(store, core)`.
`core` is what api.py shares with the legacy routes: the scans dict (so /scan/{id}, /report/{id} and the SARIF route work for
repo scans), the state files, the S-NNN counter and the fix settings. Mutating routes need the X-DPDP-Token header."""
import hmac
import html
import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import audit, github_app, ingest, repo_scan
from .models import ScanResult
from .store import Store

Actor = Field(min_length=1, max_length=100)


def require_token(x_dpdp_token: Optional[str] = Header(None)):
    expected = os.environ.get("DPDP_API_TOKEN", "")
    if not expected:
        raise HTTPException(403, "DPDP_API_TOKEN is not set on the engine, so mutating calls are refused")
    if not x_dpdp_token or not hmac.compare_digest(x_dpdp_token.encode(), expected.encode()):
        raise HTTPException(401, "missing or wrong X-DPDP-Token header")


class RepoIn(BaseModel):
    full_name: str
    branch: str = Field("", max_length=200)
    slack_channel: str = Field("", max_length=100)
    actor: str = Field("api", min_length=1, max_length=100)
    installation_id: Optional[int] = Field(None, ge=1)  # the GitHub App installation that shares this repo (block 08)


class ScanIn(BaseModel):
    mode: Literal["static"] = "static"
    actor: str = Field("api", min_length=1, max_length=100)


class BaselineIn(BaseModel):
    scan_id: Optional[str] = None
    actor: str = Actor


class WatchIn(BaseModel):
    minutes: Optional[int] = Field(None, ge=1, le=10080)
    actor: str = Actor


class StatusIn(BaseModel):
    status: str
    reason: str = ""
    actor: str = Actor


class SlackIn(BaseModel):
    channel: str = Field(min_length=1, max_length=100)
    ts: str = Field(min_length=1, max_length=50)


def _repo_error(e: repo_scan.RepoError) -> HTTPException:
    return HTTPException({"invalid": 422, "refused": 403, "timeout": 504}.get(e.kind, 502), str(e))


def _status_error(e: ingest.StatusError) -> HTTPException:
    return HTTPException(e.status, e.detail)


def _page(title: str, text: str, status: int = 200) -> HTMLResponse:
    """A small plain page for the browser steps of the GitHub install. Everything is escaped, nothing is echoed from the query."""
    body = (f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
            f"<body style='font:16px system-ui;max-width:32em;margin:4em auto'><h1>{html.escape(title)}</h1><p>{html.escape(text)}</p></body>")
    return HTMLResponse(body, status_code=status, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
                                                          "X-Content-Type-Options": "nosniff"})


def _github_error(e: github_app.GitHubAppError) -> HTTPException:
    return HTTPException({"config": 503, "notfound": 404}.get(e.kind, 502), str(e))


def create_router(store: Store, core) -> APIRouter:
    router = APIRouter()
    guard = [Depends(require_token)]
    running: set = set()  # repo ids with a scan in progress: one at a time per repo
    running_lock = threading.Lock()
    scan_slot = threading.Lock()  # one clone and scan at a time, whoever asked (API call or monitor)

    def repo_out(row) -> dict:
        h = ingest.health(store, row["id"])
        return {"id": row["id"], "full_name": row["full_name"], "branch": row["branch"], "slack_channel": row["slack_channel"],
                "health": h["status"], "reasons": h["reasons"], "last_scan_at": h["last_complete_scan_at"],
                "next_run_at": row["next_run_at"], "watch_minutes": row["watch_minutes"], "baseline_scan_id": row["baseline_scan_id"]}

    gh_cache: dict = {}

    def github():
        """The GitHub App: core.github when a test injects one, else built from the environment. It is rebuilt only when the
        settings change, so its installation token cache lives as long as they do. None when the app is not configured."""
        if getattr(core, "github", None) is not None:
            return core.github
        sig = tuple(os.environ.get(n, "") for n in ("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH", "GITHUB_APP_SLUG"))
        if gh_cache.get("sig") != sig:
            gh_cache.update(sig=sig, app=github_app.GitHubApp.from_env())
        return gh_cache["app"]

    def need_github():
        app = github()
        if app is None:
            raise HTTPException(503, "the GitHub App is not configured on the engine (GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH, GITHUB_APP_SLUG)")
        return app

    def repo_token(repo) -> Optional[str]:
        """The token git gets for this repo: a fresh installation token when it was connected through the app, else GITHUB_TOKEN."""
        if repo["installation_id"] is None:
            return os.environ.get("GITHUB_TOKEN")
        return need_github().token(repo["installation_id"])

    def authorise_repo(body: "RepoIn") -> Optional[int]:
        """The env allowlist as before, or a repo the named installation shares right now (asked from GitHub, not remembered).
        Returns the installation id to store, or None for a repo that goes through GITHUB_TOKEN. Raises 422 or 403."""
        try:
            repo_scan.check_name(body.full_name)
            listed = True
        except repo_scan.RepoError as e:
            if e.kind != "refused" or body.installation_id is None:
                raise _repo_error(e)
            listed = False
        if body.installation_id is None:
            return None
        iid, shared = body.installation_id, False
        try:
            if store.one("SELECT 1 FROM installations WHERE installation_id=?", (iid,)) is not None:
                shared = body.full_name.lower() in {r["full_name"].lower() for r in need_github().repos(iid)}
        except (github_app.GitHubAppError, HTTPException) as e:
            if not listed:  # an allowlisted repo still connects through GITHUB_TOKEN when GitHub cannot be asked
                raise _github_error(e) if isinstance(e, github_app.GitHubAppError) else e
        if shared:
            return iid
        if listed:
            return None
        raise HTTPException(403, f"{body.full_name} is not in DPDP_ALLOWED_REPOS and installation {iid} does not share it")

    def need_repo(repo_id: int):
        try:
            return ingest.repo_row(store, repo_id)
        except ingest.StatusError as e:
            raise _status_error(e)

    # ---- repos

    @router.post("/repos", status_code=201, dependencies=guard)
    def connect_repo(body: RepoIn):
        installation_id = authorise_repo(body)
        with store.tx():
            row = store.one("SELECT * FROM repos WHERE full_name=? COLLATE NOCASE", (body.full_name,))
            if row is not None:  # connecting twice is harmless: same repo back, no new event
                return repo_out(row)
            cur = store.run("INSERT INTO repos(full_name, branch, slack_channel, created_at, installation_id) VALUES (?,?,?,?,?)",
                            (body.full_name, body.branch, body.slack_channel, audit.now(), installation_id))
            audit.record(store, "repo_connected", body.actor, cur.lastrowid, result=body.full_name)
            return repo_out(store.one("SELECT * FROM repos WHERE id=?", (cur.lastrowid,)))

    @router.get("/repos")
    def list_repos():
        return [repo_out(r) for r in store.all("SELECT * FROM repos ORDER BY id")]

    @router.post("/repos/{repo_id}/scan", status_code=202, dependencies=guard)
    def scan_repo(repo_id: int, body: ScanIn, background: BackgroundTasks):
        repo = need_repo(repo_id)
        with running_lock:
            if repo_id in running:
                raise HTTPException(409, f"a scan of {repo['full_name']} is already running")
            running.add(repo_id)
        scan_id = core.new_scan_id((f"repo:{repo['full_name']}", ""))
        background.add_task(run_repo_scan, repo, scan_id, "bot", body.actor, body.mode)
        return {"scan_id": scan_id}

    def run_repo_scan(repo, scan_id: str, trigger: str, actor: str, mode: str):
        """Clone, scan, store, ingest. Any failure is stored as a failed scan, so health turns unknown."""
        started = audit.now()
        try:
            with scan_slot:
                audit.record(store, "scan_started", actor, repo["id"], scan_id, meta={"mode": mode, "trigger": trigger})
                with repo_scan.checkout(repo["full_name"], repo["branch"] or None, repo_token(repo),
                                                       via_app=repo["installation_id"] is not None) as path:
                    result = repo_scan.scan_checkout(path, scan_id, mode, repo["full_name"], repo["branch"])
                core.scans[scan_id] = result
                core.save(scan_id)
                ingest.ingest_scan(store, repo["id"], result, trigger, actor, started)
        except Exception as e:  # clone, scan or storage failed: nothing is shown as healthy
            message = audit.redact(f"{type(e).__name__}: {e}")[:300]
            core.scans[scan_id] = {"status": "error", "detail": message}
            try:
                ingest.record_scan_failed(store, repo["id"], scan_id, trigger, actor, message, started)
            except Exception:  # the store itself is broken: nothing more to do than leave the error in the scan dict
                pass
        finally:
            with running_lock:
                running.discard(repo["id"])

    def scan_repo_now(repo, trigger: str = "schedule", actor: str = "monitor", mode: str = "static"):
        """Run one scan to the end in the calling thread (the monitor's). Returns the scan id, or None when a scan of this
        repo is already running, so the monitor tries again at its next tick."""
        with running_lock:
            if repo["id"] in running:
                return None
            running.add(repo["id"])
        scan_id = core.new_scan_id((f"repo:{repo['full_name']}", ""))
        run_repo_scan(repo, scan_id, trigger, actor, mode)
        return scan_id

    core.scan_repo_now = scan_repo_now

    @router.get("/scans/{scan_id}/delta")
    def scan_delta(scan_id: str):
        try:
            return ingest.delta_of(store, scan_id)
        except ingest.StatusError as e:
            raise _status_error(e)

    @router.get("/repos/{repo_id}/health")
    def repo_health(repo_id: int):
        need_repo(repo_id)
        return ingest.health(store, repo_id)

    @router.get("/repos/{repo_id}/history")
    def repo_history(repo_id: int, limit: int = 20):
        need_repo(repo_id)
        rows = store.all("SELECT * FROM scans WHERE repo_id=? ORDER BY rowid DESC LIMIT ?", (repo_id, max(1, min(limit, 200))))
        out = []
        for r in rows:
            m = ingest.scan_summary(store, r["scan_id"])
            out.append({"scan_id": r["scan_id"], "trigger": r["trigger_kind"], "commit": r["commit_sha"], "status": r["status"],
                        "mode": r["mode"], "started_at": r["started_at"], "finished_at": r["finished_at"],
                        "findings": m.get("findings", 0), "new": m.get("new", 0), "resolved": m.get("resolved", 0),
                        "errors": json.loads(r["errors_json"] or "[]")})  # scanner, kind, message of a failed or incomplete scan
        return out

    @router.get("/repos/{repo_id}/diff")
    def repo_diff(repo_id: int, scan_id: Optional[str] = None):
        """A scan (default: the latest) against the repo's baseline, as human ids. `resolved` only holds findings whose check the
        scan covered, the same rule ingest uses, so an incomplete, failed or static scan never reports what it could not look at
        as resolved. Read `complete` before trusting the lists."""
        repo = need_repo(repo_id)
        base = repo["baseline_scan_id"]
        if base is None:
            raise HTTPException(404, f"{repo['full_name']} has no baseline yet: the first complete scan sets one, or POST /repos/{repo_id}/baseline")
        sql = "SELECT * FROM scans WHERE repo_id=?"
        scan = store.one(sql + " AND scan_id=?", (repo_id, scan_id)) if scan_id else store.one(sql + " ORDER BY rowid DESC LIMIT 1", (repo_id,))
        if scan is None:
            raise HTTPException(404, f"no scan {scan_id} for {repo['full_name']}" if scan_id else f"{repo['full_name']} has no scan yet")
        ids = lambda sid: {r["human_id"] for r in store.all("SELECT human_id FROM scan_findings WHERE scan_id=?", (sid,))}  # noqa: E731
        before, now = ids(base), ids(scan["scan_id"])
        covered = set(json.loads(scan["coverage_json"] or "{}").get("checks_run", []))
        checks = {r["human_id"]: r["check_id"] for r in store.all("SELECT human_id, check_id FROM findings WHERE repo_id=?", (repo_id,))}
        return {"repo": repo["full_name"], "baseline_scan_id": base, "scan_id": scan["scan_id"], "complete": scan["status"] == "complete",
                "new": sorted(now - before), "resolved": sorted(h for h in before - now if checks.get(h) in covered),
                "persistent": sorted(now & before)}

    @router.post("/repos/{repo_id}/baseline", dependencies=guard)
    def set_baseline(repo_id: int, body: BaselineIn):
        need_repo(repo_id)
        with store.tx():
            sql, args = "SELECT scan_id, status FROM scans WHERE repo_id=?", [repo_id]
            scan = store.one(sql + " AND scan_id=?", (*args, body.scan_id)) if body.scan_id else \
                store.one(sql + " AND status='complete' ORDER BY rowid DESC LIMIT 1", args)
            if scan is None:
                raise HTTPException(404 if body.scan_id else 409, "no such scan for this repo" if body.scan_id else "no complete scan yet")
            if scan["status"] != "complete":
                raise HTTPException(422, f"{scan['scan_id']} is {scan['status']}: only a complete scan can be a baseline")
            store.run("UPDATE repos SET baseline_scan_id=? WHERE id=?", (scan["scan_id"], repo_id))
            audit.record(store, "baseline_set", body.actor, repo_id, scan["scan_id"], result="explicit")
        return {"baseline_scan_id": scan["scan_id"]}

    @router.post("/repos/{repo_id}/watch", dependencies=guard)
    def set_watch(repo_id: int, body: WatchIn):
        need_repo(repo_id)
        due = (datetime.now(timezone.utc) + timedelta(minutes=body.minutes)).isoformat(timespec="seconds") if body.minutes else None
        with store.tx():
            store.run("UPDATE repos SET watch_minutes=?, next_run_at=? WHERE id=?", (body.minutes, due, repo_id))
            audit.record(store, "watch_changed", body.actor, repo_id, result=str(body.minutes), meta={"minutes": body.minutes})
        return {"watch_minutes": body.minutes, "next_run_at": due}

    # ---- GitHub App (block 08)

    @router.get("/github/install-url", dependencies=guard)
    def install_url():
        return {"url": need_github().install_url(github_app.sign_state(os.environ["DPDP_API_TOKEN"])), "expires_in": github_app.STATE_TTL}

    @router.get("/github/connect")  # not token guarded: a browser opens it from the Slack button, so the signed state never appears in Slack
    def github_connect():
        app, secret = github(), os.environ.get("DPDP_API_TOKEN", "")
        if app is None or not secret:
            return _page("GitHub is not set up", "The engine has no GitHub App settings or no DPDP_API_TOKEN.", 503)
        return RedirectResponse(app.install_url(github_app.sign_state(secret)), status_code=302)

    @router.get("/github/setup")  # GitHub redirects the browser here after the install (the app's Setup URL). The state is the check.
    def github_setup(installation_id: Optional[int] = None, setup_action: str = "", state: str = ""):
        app = github()
        if app is None:
            return _page("GitHub is not set up", "The engine has no GitHub App settings.", 503)
        if not github_app.check_state(os.environ.get("DPDP_API_TOKEN", ""), state):
            return _page("Link expired", "This link is invalid or expired. Run /dpdp connect in Slack again.", 400)
        if installation_id is None:
            return _page("Not installed yet", "GitHub did not return an installation. If an owner has to approve it, wait for that, then run /dpdp connect again.", 400)
        try:
            info = app.installation(installation_id)
        except github_app.GitHubAppError as e:
            return _page("GitHub did not confirm the install", str(e), 404 if e.kind == "notfound" else 502)
        with store.tx():
            store.run("INSERT INTO installations(installation_id, account_login, account_type, created_at) VALUES (?,?,?,?) "
                      "ON CONFLICT(installation_id) DO UPDATE SET account_login=excluded.account_login, account_type=excluded.account_type",
                      (info["installation_id"], info["account_login"], info["account_type"], audit.now()))
            audit.record(store, "github_installed", "github", result=info["account_login"],
                         meta={"installation_id": info["installation_id"], "account_type": info["account_type"], "setup_action": setup_action[:20]})
            ingest._outbox(store, "github_installed", str(info["installation_id"]))  # the installation id rides in human_id
        return _page("GitHub connected, return to Slack", f"The app is installed for {info['account_login']}. Run /dpdp connect in Slack to pick a repository.")

    @router.get("/github/installations", dependencies=guard)  # guarded read: it shows who installed the app
    def list_installations():
        need_github()
        return [dict(r) for r in store.all("SELECT * FROM installations ORDER BY installation_id")]

    @router.get("/github/installations/{installation_id}/repos", dependencies=guard)  # guarded read: private repo names
    def installation_repos(installation_id: int):
        app = need_github()
        if store.one("SELECT 1 FROM installations WHERE installation_id=?", (installation_id,)) is None:
            raise HTTPException(404, f"installation {installation_id} is not registered: install the app from the link in Slack first")
        try:
            repos = app.repos(installation_id)
        except github_app.GitHubAppError as e:
            raise _github_error(e)
        connected = {r["full_name"].lower() for r in store.all("SELECT full_name FROM repos")}
        return [{**r, "connected": r["full_name"].lower() in connected} for r in repos]

    # ---- findings

    @router.get("/findings")
    def list_findings(repo_id: Optional[int] = None, status: Optional[str] = None, severity: Optional[str] = None,
                      q: Optional[str] = None, limit: int = 50, offset: int = 0):
        if status and status not in ingest.STATUSES:
            raise HTTPException(422, f"status must be one of {', '.join(ingest.STATUSES)}")
        return ingest.list_records(store, repo_id, status, severity, q, max(1, min(limit, 500)), max(0, offset))

    @router.get("/findings/{human_id}")
    def get_finding(human_id: str):
        record = ingest.get_record(store, human_id)
        if record is None:
            raise HTTPException(404, f"Unknown finding {human_id}")
        events = [{"id": e["id"], "ts": e["ts"], "type": e["type"], "actor": e["actor"], "result": e["result"],
                   "scan_id": e["scan_id"]} for e in store.all("SELECT * FROM events WHERE human_id=? ORDER BY id", (human_id,))]
        last = json.loads(store.one("SELECT last_finding_json FROM findings WHERE human_id=?", (human_id,))["last_finding_json"])
        return {**record, "events": events, "finding": last}

    @router.patch("/findings/{human_id}/status", dependencies=guard)
    def patch_status(human_id: str, body: StatusIn):
        try:
            ingest.set_status(store, human_id, body.status, body.reason, body.actor)
        except ingest.StatusError as e:
            raise _status_error(e)
        return ingest.get_record(store, human_id)

    @router.put("/findings/{human_id}/slack", dependencies=guard)
    def put_slack(human_id: str, body: SlackIn):
        with store.tx():
            if store.one("SELECT 1 FROM findings WHERE human_id=?", (human_id,)) is None:
                raise HTTPException(404, f"Unknown finding {human_id}")
            store.run("UPDATE findings SET slack_channel=?, slack_ts=? WHERE human_id=?", (body.channel, body.ts, human_id))
        return ingest.get_record(store, human_id)

    # ---- fix

    def seed_db(backend: Path, db: Path):
        """The repo's own seed script, with TUTORNEST_DB pointing at a temp file. This runs repo code, so only repos in
        DPDP_FIX_REPOS get here."""
        proc = subprocess.run([sys.executable, "seed.py"], cwd=backend, capture_output=True, text=True, timeout=60,
                              env={**os.environ, "TUTORNEST_DB": str(db)})
        if proc.returncode or not db.exists():
            raise RuntimeError(f"the repo's seed.py did not create a database: {' '.join(proc.stderr.split())[-200:]}")

    def fix_human(human_id: str, mode: str, actor: str):
        """POST /findings/{human_id}/fix. The stored scan JSON is never changed: the result goes to events and last_finding_json."""
        from .api import FixError, apply_fix  # late import: api.py imports this module
        row = store.one("SELECT f.*, r.full_name, r.installation_id FROM findings f JOIN repos r ON r.id=f.repo_id WHERE f.human_id=?", (human_id,))
        if row is None:
            raise HTTPException(404, f"Unknown finding {human_id}")
        try:
            repo_scan.check_name(row["full_name"], "DPDP_FIX_REPOS")
        except repo_scan.RepoError:
            raise HTTPException(403, f"{row['full_name']} is not in DPDP_FIX_REPOS, so its code is never run")
        scan = core.scans.get(row["last_seen_scan"])
        finding = next((f for f in getattr(scan, "findings", []) if f.fingerprint == row["fingerprint"]), None)
        if not isinstance(scan, ScanResult) or finding is None:
            raise HTTPException(409, f"the scan {row['last_seen_scan']} that last saw {human_id} is not available, scan the repo again")
        if row["status"] == "fixed":
            raise HTTPException(409, f"{human_id} is already fixed")
        with core.fix_lock:
            audit.record(store, "fix_started", actor, row["repo_id"], scan.scan_id, human_id, result=mode)
            try:
                out, fallback = None, None
                if mode == "live":
                    try:
                        with repo_scan.checkout(row["full_name"], scan.commit or None, repo_token(row), "DPDP_FIX_REPOS") as d, \
                                tempfile.TemporaryDirectory(prefix="dpdp-fixdb-") as tmp:
                            backend = d / "backend" if (d / "backend").is_dir() else d
                            db = Path(tmp) / "fix.db"
                            seed_db(backend, db)
                            out = apply_fix(scan, finding.id, str(backend), str(db), mode="live", fix_fn=core.fix_fn, golden_dir=core.golden_dir)
                    except FixError:
                        raise
                    except Exception as e:  # checkout, seed or sandbox trouble: replay the saved golden result, labelled
                        fallback = f"{type(e).__name__}: {audit.redact(str(e))[:200]}"
                if out is None:
                    out = apply_fix(scan, finding.id, "", "", mode="cached", fix_fn=core.fix_fn, golden_dir=core.golden_dir)
                fixed, _, used, reason, vlog = out
                reason = fallback or reason
            except FixError as e:
                audit.record(store, "fix_failed", actor, row["repo_id"], scan.scan_id, human_id, result=str(e.status), meta={"detail": e.detail})
                raise HTTPException(e.status, e.detail)
            meta = {"mode": used, "fallback_reason": reason, "rescan_passed": fixed.fix.rescan_passed, "tests_passed": fixed.fix.tests_passed}
            if fixed.status == "verified_fixed":
                ingest.mark_fixed(store, human_id, actor, fixed, meta)
            else:
                audit.record(store, "fix_failed", actor, row["repo_id"], scan.scan_id, human_id, result="not verified", meta=meta)
        return {"finding": fixed, "mode": used, "fallback_reason": reason, "verification": vlog, "record": ingest.get_record(store, human_id)}

    core.fix_human = fix_human

    # POST /findings/{human_id}/fix is served by the legacy route in api.py (same path, FastAPI matches the first one
    # registered). It calls require_token and core.fix_human for DPDP- ids.

    # ---- outbox and audit

    @router.get("/outbox")
    def get_outbox(after: int = 0):
        # status_changed rows have a human_id. scan_delta and health_changed rows have repo_id and scan_id instead.
        return [{"id": r["id"], "kind": r["kind"], "human_id": r["human_id"], "repo_id": r["repo_id"], "scan_id": r["scan_id"]}
                for r in store.all("SELECT * FROM outbox WHERE id>? ORDER BY id LIMIT 500", (after,))]

    @router.get("/audit/events")
    def audit_events(repo_id: Optional[int] = None, type: Optional[str] = None, limit: int = 100):
        where, params = [], []
        if repo_id is not None:
            where.append("repo_id=?"), params.append(repo_id)
        if type:
            where.append("type=?"), params.append(type)
        sql = "SELECT * FROM events" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
        return [{"id": e["id"], "ts": e["ts"], "type": e["type"], "actor": e["actor"], "repo_id": e["repo_id"], "scan_id": e["scan_id"],
                 "human_id": e["human_id"], "policy_version": e["policy_version"], "result": e["result"], "meta": json.loads(e["meta_json"]),
                 "hash": e["hash"]} for e in store.all(sql, (*params, max(1, min(limit, 1000))))]

    @router.get("/audit/verify")
    def audit_verify():
        return audit.verify_chain(store)

    return router
