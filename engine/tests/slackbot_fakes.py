"""Test doubles for the Slack bot: a fake Slack client and a small fake engine API that returns the master section 9 shapes."""
import re
import socket
import threading
import time
from types import SimpleNamespace

import uvicorn
from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from dpdp_lens.slackbot.api import Engine
from dpdp_lens.slackbot.config import Config
from dpdp_lens.slackbot.flow import Ctx
from dpdp_lens.slackbot.poster import Poster

TOKEN = "t0k-engine-secret"
CHANNEL = "C100"
APPROVER, OTHER = "U_APPROVER", "U_OTHER"
# raw PII shapes that must never appear in any Slack payload: Aadhaar (12 digits), PAN, 10 digit phone
PII = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b|\b[A-Z]{5}\d{4}[A-Z]\b|(?<![\d.])[6-9]\d{9}(?!\d)")


class FakeSlack:
    """Records every call. `fail_next` holds exceptions to raise from the next chat_postMessage calls."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.fail_next: list[Exception] = []
        self.fail_webhook: list[int] = []
        self.n = 0

    def _rec(self, name, kw):
        self.calls.append((name, kw))

    def chat_postMessage(self, **kw):
        if self.fail_next:
            raise self.fail_next.pop(0)
        self.n += 1
        self._rec("post", kw)
        return {"ok": True, "ts": f"1700000000.{self.n:06d}"}

    def chat_update(self, **kw):
        self._rec("update", kw)
        return {"ok": True}

    def chat_postEphemeral(self, **kw):
        self._rec("ephemeral", kw)
        return {"ok": True}

    def views_open(self, **kw):
        self._rec("view", kw)
        return {"ok": True}

    def webhook(self, url):
        """Stands in for a response_url: records what was sent to it. `fail_webhook` holds status codes to answer first (429 retry tests)."""
        fake = self

        class Hook:
            def send(self, **kw):
                if fake.fail_webhook:
                    return SimpleNamespace(status_code=fake.fail_webhook.pop(0), headers={"Retry-After": "1"})
                fake._rec("respond", {"url": url, **kw})
                return SimpleNamespace(status_code=200, headers={})

        return Hook()

    def of(self, name):
        return [kw for n, kw in self.calls if n == name]

    def texts(self):
        """All text a person could read in any call, blocks included."""
        import json
        return json.dumps(self.calls, default=str)


TEMPLATES = [  # what a static scan of TutorNest looks like, trimmed. Everything masked, as the engine returns it.
    dict(check="log_pii", severity="high", proof="static", layer="code", title="Personal data written to a log", fix=True,
         file="backend/app/main.py", line=87, explanation="Signup logs the email and Aadhaar. Logs are rarely protected.",
         sample="aadhaar XXXX XXXX 1234, email a***@x.com"),
    dict(check="config_secret_committed", severity="medium", proof="static", layer="config", title="Secret committed to the repo", fix=False,
         file="backend/.env", line=2, explanation="A signing key sits in a committed file.", sample="SECRET_KEY=sk***"),
    dict(check="api_pii_exposure", severity="critical", proof="probed", layer="api", title="Personal data open to anyone", fix=True,
         file="", line=0, url="/api/students", explanation="The list route needs no login.", sample="phone 98XXXXXX10, pan ABXXXXXX4F"),
]


def make_engine_app():
    """Returns (app, state). `state` can be changed by a test: complete, scan_fails, fix_response, health, repos_slack."""
    st = SimpleNamespace(repos=[], findings={}, scans={}, outbox=[], complete=True, scan_fails=False, health=None, fix_calls=[], status_calls=[],
                         fix_response=None, fix_error=None, diff_response=None, diff_calls=0, watch_calls=[], baseline_calls=[], scan_errors=[],
                         installs=None, gh_repos={}, connect_calls=[], report_calls=[], report_response=None, pr_allowed=False, pr_calls=[], pr_error=None)  # installs None: the engine has no GitHub App (503)
    app = FastAPI()

    @app.exception_handler(HTTPException)
    async def _err(request: Request, exc: HTTPException):
        return JSONResponse({"error": "x", "detail": exc.detail}, status_code=exc.status_code)

    def need(token):
        if token != TOKEN:
            raise HTTPException(401, "missing or wrong X-DPDP-Token header")

    def repo_out(r):
        return {"id": r["id"], "full_name": r["full_name"], "branch": r["branch"], "slack_channel": r["slack_channel"], "health": "at_risk",
                "reasons": [], "last_scan_at": None, "next_run_at": None, "watch_minutes": None, "baseline_scan_id": r.get("baseline")}

    def record(f):
        return {"human_id": f["human_id"], "repo": "acme/tutornest", "branch": "main", "fingerprint": f["human_id"].lower(), "check": f["check"],
                "severity": f["severity"], "title": f["title"], "layer": f["layer"], "proof": f["proof"], "status": f["status"],
                "status_reason": f["reason"], "status_by": f["by"], "status_at": "t", "first_seen_at": "t", "last_seen_at": "t",
                "location": {"file": f["file"], "line": f["line"], "url": f.get("url", "")}, "fix_available": f["fix"], "slack": f["slack"],
                "pr_url": f.get("pr_url", ""), "pr_available": bool(st.pr_allowed and f["status"] == "fixed" and not f.get("pr_url"))}

    st.record = record

    @app.post("/repos", status_code=201)
    def connect(body: dict = Body(...), x_dpdp_token: str | None = Header(None)):
        need(x_dpdp_token)
        st.connect_calls.append(body)
        for r in st.repos:
            if r["full_name"].lower() == body["full_name"].lower():
                return repo_out(r)
        if body["full_name"] != "acme/tutornest" and not body.get("installation_id"):
            raise HTTPException(403, f"{body['full_name']} is not in DPDP_ALLOWED_REPOS")
        r = {"id": len(st.repos) + 1, "full_name": body["full_name"], "branch": body["branch"], "slack_channel": body["slack_channel"]}
        st.repos.append(r)
        return repo_out(r)

    @app.get("/github/installations")
    def github_installations(x_dpdp_token: str | None = Header(None)):
        need(x_dpdp_token)
        if st.installs is None:
            raise HTTPException(503, "the GitHub App is not configured on the engine")
        return st.installs

    @app.get("/github/installations/{iid}/repos")
    def github_repos(iid: int, x_dpdp_token: str | None = Header(None)):
        need(x_dpdp_token)
        known = {r["full_name"].lower() for r in st.repos}
        return [{**r, "connected": r["full_name"].lower() in known} for r in st.gh_repos.get(iid, [])]

    @app.get("/repos")
    def repos():
        return [repo_out(r) for r in st.repos]

    @app.post("/repos/{rid}/scan", status_code=202)
    def scan(rid: int, body: dict = Body(...), x_dpdp_token: str | None = Header(None)):
        need(x_dpdp_token)
        sid = f"S-{len(st.scans) + 1:03d}"
        new, persistent = [], 0
        if not st.scan_fails:
            for t in TEMPLATES:
                found = next((f for f in st.findings.values() if f["check"] == t["check"]), None)
                if found is None:
                    hid = f"DPDP-{len(st.findings) + 1:03d}"
                    st.findings[hid] = {**t, "human_id": hid, "status": "open", "reason": "", "by": "system", "slack": None, "url": t.get("url", "")}
                    new.append(hid)
                else:
                    persistent += 1
        st.scans[sid] = {"id": sid, "repo": rid, "failed": st.scan_fails, "new": new, "persistent": persistent, "complete": st.complete and not st.scan_fails}
        return {"scan_id": sid}

    @app.get("/scan/{sid}")
    def get_scan(sid: str):
        s = st.scans.get(sid)
        if s is None:
            raise HTTPException(404, f"Unknown scan {sid}")
        if s["failed"]:
            raise HTTPException(500, "RepoError: clone failed")
        return {"scan_id": sid, "complete": s["complete"], "scan_errors": st.scan_errors, "findings": []}

    @app.get("/scans/{sid}/delta")
    def delta(sid: str):
        s = st.scans.get(sid)
        if s is None:
            raise HTTPException(404, f"Unknown stored scan {sid}")
        return {"scan_id": sid, "repo": "acme/tutornest", "commit": "abcdef1234567890", "complete": s["complete"], "new": s["new"], "reopened": [],
                "resolved": [], "persistent": s["persistent"], "suppressed": 0, "health": get_health(1)}

    @app.get("/repos/{rid}/health")
    def get_health(rid: int):
        return st.health or {"status": "at_risk" if st.complete else "unknown", "reasons": ["1 blocking finding(s) open", "static checks only (11 of 19)"],
                             "last_complete_scan_at": "t", "last_scan_status": "complete" if st.complete else "incomplete",
                             "counts": {"open": 3, "in_progress": 0, "fixed": 0, "false_positive": 0, "wont_fix": 0}}

    @app.get("/repos/{rid}/history")
    def history(rid: int, limit: int = 20):
        return [{"scan_id": sid, "status": "complete"} for sid in list(st.scans)[-limit:][::-1]]

    @app.get("/repos/{rid}/diff")
    def diff(rid: int):
        st.diff_calls += 1
        if st.diff_response is None:
            raise HTTPException(404, "acme/tutornest has no baseline yet: the first complete scan sets one, or POST /repos/1/baseline")
        return st.diff_response

    @app.get("/findings")
    def list_findings(repo_id: int | None = None, status: str | None = None, limit: int = 50, offset: int = 0):
        items = sorted((f for f in st.findings.values() if status in (None, f["status"])), key=lambda f: f["human_id"])
        counts = {k: sum(f["status"] == k for f in st.findings.values()) for k in ("open", "in_progress", "fixed", "false_positive", "wont_fix")}
        return {"total": len(items), "counts_by_status": counts, "items": [record(f) for f in items[offset: offset + limit]]}

    @app.get("/findings/{hid}")
    def get_finding(hid: str):
        f = st.findings.get(hid)
        if f is None:
            raise HTTPException(404, f"Unknown finding {hid}")
        return {**record(f), "events": [], "finding": {
            "title": f["title"], "explanation": f["explanation"], "severity_reason": "built from scan facts",
            "clauses": [{"ref": "Act s8(5)", "note": "reasonable security safeguards"}], "recommendation": "Remove the personal data from the log call.",
            "evidence": {"summary": "seen in code", "masked_sample": f["sample"]}}}

    @app.patch("/findings/{hid}/status")
    def patch_status(hid: str, body: dict = Body(...), x_dpdp_token: str | None = Header(None)):
        need(x_dpdp_token)
        f = st.findings.get(hid)
        if f is None:
            raise HTTPException(404, f"Unknown finding {hid}")
        if body["status"] == "fixed":
            raise HTTPException(422, "Fixed is set by a scan or a verified fix")
        if body["status"] in ("false_positive", "wont_fix") and not body.get("reason"):
            raise HTTPException(422, f"{body['status']} needs a reason of 1 to 300 characters")
        if PII.search(body.get("reason", "")):
            raise HTTPException(422, "the reason must not contain personal data")
        st.status_calls.append(body)
        f.update(status=body["status"], reason=body.get("reason", ""), by=body["actor"])
        st.outbox.append({"id": len(st.outbox) + 1, "kind": "status_changed", "human_id": hid, "repo_id": None, "scan_id": ""})
        return record(f)

    @app.put("/findings/{hid}/slack")
    def put_slack(hid: str, body: dict = Body(...), x_dpdp_token: str | None = Header(None)):
        need(x_dpdp_token)
        st.findings[hid]["slack"] = {"channel": body["channel"], "ts": body["ts"]}
        return record(st.findings[hid])

    @app.post("/findings/{hid}/fix")
    def fix(hid: str, mode: str = "live", body: dict = Body(None), x_dpdp_token: str | None = Header(None)):
        need(x_dpdp_token)
        st.fix_calls.append((hid, mode, body))
        if st.fix_error:
            raise HTTPException(*st.fix_error)
        out = st.fix_response
        if out["finding"]["status"] == "verified_fixed":
            st.findings[hid].update(status="fixed", reason="verified fix", by=body["actor"])
        out["record"] = record(st.findings[hid])
        return out

    @app.get("/outbox")
    def outbox(after: int = 0):
        return [r for r in st.outbox if r["id"] > after]

    @app.post("/repos/{rid}/baseline")
    def baseline(rid: int, body: dict = Body(...), x_dpdp_token: str | None = Header(None)):
        need(x_dpdp_token)
        st.baseline_calls.append(body)
        return {"baseline_scan_id": "S-001"}

    @app.post("/findings/{hid}/pr")
    def open_pr(hid: str, body: dict = Body(...), x_dpdp_token: str | None = Header(None)):
        need(x_dpdp_token)
        st.pr_calls.append((hid, body))
        if st.pr_error:
            raise HTTPException(*st.pr_error)
        f = st.findings[hid]
        f["pr_url"] = "https://github.com/acme/tutornest/pull/9"
        return {"pr_url": f["pr_url"], "branch": f"dpdp-lens/fix-{hid}-abc1234", "reused": False, "number": 9, "base": "main", "record": record(f)}

    @app.post("/repos/{rid}/report-link")
    def report_link(rid: int, body: dict = Body(...), x_dpdp_token: str | None = Header(None)):
        need(x_dpdp_token)
        st.report_calls.append((rid, body))
        return st.report_response or {"url": f"/repos/{rid}/report?scan_id=S-001&sig=PAYLOAD.MAC", "scan_id": "S-001", "expires_in": 900,
                                      "summary": {"findings": 3, "open_by_severity": {"critical": 1, "high": 1, "medium": 1, "low": 0}, "health": "at_risk",
                                                  "coverage": "static checks only (9 of 19)", "complete": True, "warnings": []}}

    @app.post("/repos/{rid}/watch")
    def watch(rid: int, body: dict = Body(...), x_dpdp_token: str | None = Header(None)):
        need(x_dpdp_token)
        st.watch_calls.append(body)
        return {"watch_minutes": body["minutes"], "next_run_at": None}

    st.fix_response = verified_fix()
    return app, st


def verified_fix(verified=True, mode="live", rescan=True, tests=True, fallback=None):
    return {"finding": {"id": "F-1", "status": "verified_fixed" if verified else "open",
                        "fix": {"available": True, "verified": verified, "rescan_passed": rescan, "tests_passed": tests, "score_before": 13,
                                "score_after": 31, "diff": "--- a/main.py\n+++ b/main.py\n-    logger.info(aadhaar)\n+    logger.info('signup')"}},
            "mode": mode, "fallback_reason": fallback, "verification": []}


_servers: list = []


def serve(app, port: int = 0) -> str:
    """Run an ASGI app on a real local port in a thread (so the bot's real httpx client is what the tests use). Returns its URL."""
    if not port:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError(f"server on {port} did not start")
    _servers.append((server, thread))
    return f"http://127.0.0.1:{port}"


def stop_servers():
    while _servers:
        server, thread = _servers.pop()
        server.should_exit = True
        thread.join(5)


def make_ctx(approvers=(APPROVER,), fix_repos=("acme/tutornest",), channels=(CHANNEL,), engine_app=None, engine_url=None, token=TOKEN):
    """A Ctx wired to the fake Slack and an engine (the fake one unless `engine_url` is given). Returns (ctx, slack, fake_engine_state)."""
    st = None
    if engine_url is None:
        app, st = engine_app or make_engine_app()
        engine_url = serve(app)
    cfg = Config(engine_url=engine_url, dashboard_url="http://dash.test", api_token=token, channel=channels[0],
                 allowed_channels=frozenset(channels), approvers=frozenset(approvers), fix_repos=frozenset(fix_repos))
    slack = FakeSlack()
    ctx = Ctx(cfg, Engine(cfg.engine_url, cfg.api_token), slack, Poster(slack, interval=0, sleep=lambda s: None, webhook=slack.webhook), sleep=lambda s: None)
    return ctx, slack, st
