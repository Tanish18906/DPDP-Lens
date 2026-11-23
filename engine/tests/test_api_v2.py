"""Block 01b: the repo, finding, audit and outbox routes, with a local bare repo of TutorNest as the "remote"."""
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from dpdp_lens import repo_scan
from dpdp_lens.api import create_app
from dpdp_lens.fixer.verify import GOLDEN_DIR
from dpdp_lens.store import Store
from remote import make_remote

TOKEN = {"X-DPDP-Token": "test-token"}


@pytest.fixture(scope="module")
def remote(tmp_path_factory):
    base = tmp_path_factory.mktemp("remote2")
    return base, make_remote(base)


@pytest.fixture
def api(remote, tmp_path, monkeypatch, with_late_scanners):
    base, sha = remote
    monkeypatch.setattr(repo_scan, "GIT_BASE", f"file://{base}")
    monkeypatch.setattr(repo_scan, "ALLOW_FILE", True)
    monkeypatch.setenv("DPDP_API_TOKEN", "test-token")
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", "acme/tutornest,acme/missing")
    monkeypatch.setenv("DPDP_FIX_REPOS", "acme/tutornest")
    shutil.copytree(GOLDEN_DIR, tmp_path / "golden")  # a live fix saves its golden file: never into the real data folder
    app = create_app(repo_root=tmp_path, state_dir=tmp_path / "state", store=Store(tmp_path / "dpdp.db"), golden_dir=tmp_path / "golden")
    client = TestClient(app)
    client.sha = sha
    client.state = tmp_path / "state"
    return client


def connect(c, name="acme/tutornest"):
    r = c.post("/repos", json={"full_name": name, "actor": "U1"}, headers=TOKEN)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def scan(c, repo_id):
    r = c.post(f"/repos/{repo_id}/scan", json={}, headers=TOKEN)
    assert r.status_code == 202, r.text
    return r.json()["scan_id"]


def test_mutating_routes_need_the_token(api, monkeypatch):
    body = {"full_name": "acme/tutornest"}
    assert api.post("/repos", json=body).status_code == 401
    assert api.post("/repos", json=body, headers={"X-DPDP-Token": "wrong"}).status_code == 401
    monkeypatch.delenv("DPDP_API_TOKEN")
    r = api.post("/repos", json=body, headers=TOKEN)
    assert r.status_code == 403 and set(r.json()) == {"error", "detail"}  # an unset token refuses every mutating call


@pytest.mark.parametrize("method, path, body", [
    ("post", "/repos/1/scan", {}), ("post", "/repos/1/baseline", {"actor": "u"}), ("post", "/repos/1/watch", {"minutes": 5, "actor": "u"}),
    ("patch", "/findings/DPDP-001/status", {"status": "open", "actor": "u"}), ("put", "/findings/DPDP-001/slack", {"channel": "C", "ts": "1"}),
    ("post", "/findings/DPDP-001/fix", None)])
def test_every_mutating_route_is_guarded_and_reads_are_not(api, method, path, body):
    assert getattr(api, method)(path, json=body).status_code == 401
    for read in ("/repos", "/findings", "/outbox", "/audit/events", "/audit/verify"):
        assert api.get(read).status_code == 200


def test_connect_checks_name_then_allowlist(api):
    assert api.post("/repos", json={"full_name": "nope"}, headers=TOKEN).status_code == 422
    r = api.post("/repos", json={"full_name": "evil/repo"}, headers=TOKEN)
    assert r.status_code == 403 and "DPDP_ALLOWED_REPOS" in r.json()["detail"]
    assert api.get("/repos").json() == []


def test_connecting_twice_returns_the_same_repo_and_one_event(api):
    assert connect(api) == connect(api)
    assert [e["type"] for e in api.get("/audit/events").json()] == ["repo_connected"]


def test_full_flow_connect_scan_ingest_patch_list_audit(api):
    rid = connect(api)
    sid = scan(api, rid)
    assert sid == "S-001"
    # the scan is in the legacy dict too, so the legacy routes work for it
    stored = api.get(f"/scan/{sid}").json()
    assert stored["complete"] is True and stored["coverage"]["mode"] == "static" and stored["repo"] == "acme/tutornest"
    assert stored["commit"] == api.sha
    assert api.get(f"/report/{sid}").status_code == 200 and api.get(f"/scan/{sid}/sarif").status_code == 200
    assert (api.state / f"{sid}.json").exists()

    found = api.get("/findings", params={"repo_id": rid}).json()
    assert found["total"] == len(stored["findings"]) >= 9 and found["counts_by_status"]["open"] == found["total"]
    assert [i["human_id"] for i in found["items"]][:2] == ["DPDP-001", "DPDP-002"]
    one = next(i for i in found["items"] if i["check"] == "log_pii")
    assert one["proof"] == "static" and one["location"]["file"].endswith("main.py") and one["fix_available"] is True
    assert api.get("/findings", params={"q": "main.py"}).json()["total"] >= 1
    assert api.get("/findings", params={"severity": "critical"}).json()["total"] == 0  # static checks have no critical in TutorNest
    assert api.get("/findings", params={"status": "bogus"}).status_code == 422

    r = api.patch(f"/findings/{one['human_id']}/status", json={"status": "false_positive", "reason": "test data", "actor": "U2"}, headers=TOKEN)
    assert r.status_code == 200 and r.json()["status"] == "false_positive" and r.json()["status_by"] == "U2"
    detail = api.get(f"/findings/{one['human_id']}").json()
    assert [e["type"] for e in detail["events"]] == ["finding_created", "status_changed"] and detail["finding"]["check"] == "log_pii"
    assert any(o["kind"] == "status_changed" and o["human_id"] == one["human_id"] for o in api.get("/outbox").json())
    assert api.get("/outbox", params={"after": 10**6}).json() == []

    assert api.get("/audit/verify").json() == {"ok": True, "checked": len(api.get("/audit/events", params={"limit": 1000}).json()), "first_bad": None}
    types = [e["type"] for e in api.get("/audit/events", params={"limit": 1000}).json()]
    assert {"repo_connected", "scan_started", "scan_completed", "finding_created", "status_changed", "baseline_set"} <= set(types)

    health = api.get(f"/repos/{rid}/health").json()
    assert health["status"] == "at_risk" and health["counts"]["false_positive"] == 1 and any("static checks only" in x for x in health["reasons"])
    listed = api.get("/repos").json()[0]
    assert listed["baseline_scan_id"] == sid and listed["health"] == "at_risk" and listed["branch"] == "main"
    delta = api.get(f"/scans/{sid}/delta").json()
    assert len(delta["new"]) == found["total"] and delta["complete"] is True and delta["commit"] == api.sha
    hist = api.get(f"/repos/{rid}/history").json()
    assert hist[0]["scan_id"] == sid and hist[0]["new"] == found["total"] and hist[0]["status"] == "complete" and hist[0]["errors"] == []
    assert "explanation" in one and one["explanation"]  # one line for the Feed list


def test_second_scan_has_no_new_findings_and_keeps_the_baseline(api):
    rid = connect(api)
    first, second = scan(api, rid), scan(api, rid)
    d = api.get(f"/scans/{second}/delta").json()
    assert d["new"] == [] and d["resolved"] == [] and d["persistent"] >= 9 and second == "S-002"
    assert api.get("/repos").json()[0]["baseline_scan_id"] == first
    r = api.post(f"/repos/{rid}/baseline", json={"scan_id": second, "actor": "U1"}, headers=TOKEN)
    assert r.status_code == 200 and api.get("/repos").json()[0]["baseline_scan_id"] == second  # only an explicit call replaces it
    assert api.post(f"/repos/{rid}/baseline", json={"scan_id": "S-099", "actor": "U1"}, headers=TOKEN).status_code == 404


def test_manual_fixed_and_missing_reason_are_422(api):
    scan(api, connect(api))
    for body in ({"status": "fixed", "actor": "u"}, {"status": "wont_fix", "actor": "u"}, {"status": "wont_fix", "reason": "x", "actor": ""}):
        r = api.patch("/findings/DPDP-001/status", json=body, headers=TOKEN)
        assert r.status_code == 422 and set(r.json()) == {"error", "detail"}
    assert api.patch("/findings/DPDP-999/status", json={"status": "open", "actor": "u"}, headers=TOKEN).status_code == 404
    assert api.get("/findings/DPDP-001").json()["status"] == "open"


def test_slack_link_is_stored_on_the_record(api):
    scan(api, connect(api))
    r = api.put("/findings/DPDP-001/slack", json={"channel": "C1", "ts": "1700000000.000100"}, headers=TOKEN)
    assert r.json()["slack"] == {"channel": "C1", "ts": "1700000000.000100"}
    assert api.put("/findings/DPDP-999/slack", json={"channel": "C1", "ts": "1"}, headers=TOKEN).status_code == 404


def test_watch_sets_and_clears_the_schedule(api):
    rid = connect(api)
    r = api.post(f"/repos/{rid}/watch", json={"minutes": 5, "actor": "U1"}, headers=TOKEN).json()
    assert r["watch_minutes"] == 5 and r["next_run_at"]
    for bad in (0, 10081):
        assert api.post(f"/repos/{rid}/watch", json={"minutes": bad, "actor": "U1"}, headers=TOKEN).status_code == 422
    assert api.post(f"/repos/{rid}/watch", json={"minutes": None, "actor": "U1"}, headers=TOKEN).json()["next_run_at"] is None
    assert api.get("/repos").json()[0]["watch_minutes"] is None


def test_a_failed_clone_is_stored_and_health_is_unknown(api):
    rid = connect(api, "acme/missing")  # allowlisted, but the remote has no such repo
    sid = scan(api, rid)
    r = api.get(f"/scan/{sid}")
    assert r.status_code == 500 and "RepoError" in r.json()["detail"]
    assert api.get(f"/repos/{rid}/health").json()["status"] == "unknown"
    hist = api.get(f"/repos/{rid}/history").json()[0]
    assert hist["status"] == "failed" and hist["errors"][0]["scanner"] == "scan" and "RepoError" in hist["errors"][0]["message"]
    assert "scan_failed" in [e["type"] for e in api.get("/audit/events").json()]
    assert api.get("/audit/verify").json()["ok"]


def test_a_second_scan_is_refused_while_one_runs(api):
    rid = connect(api)
    api.app.router.routes  # noqa: B018  (the route table is built)
    import threading
    started = threading.Event()
    real = repo_scan.checkout

    from contextlib import contextmanager

    @contextmanager
    def slow(*a, **k):
        started.set()
        release.wait(5)
        with real(*a, **k) as p:
            yield p

    release = threading.Event()
    repo_scan_checkout = repo_scan.checkout
    repo_scan.checkout = slow
    try:
        t = threading.Thread(target=lambda: scan(api, rid))
        t.start()
        assert started.wait(5)
        assert api.post(f"/repos/{rid}/scan", json={}, headers=TOKEN).status_code == 409
        release.set()
        t.join(10)
    finally:
        repo_scan.checkout = repo_scan_checkout


def test_only_static_mode_is_accepted_for_a_repo(api):
    rid = connect(api)
    assert api.post(f"/repos/{rid}/scan", json={"mode": "full"}, headers=TOKEN).status_code == 422


# ---- legacy routes next to the new ones

def test_legacy_fix_route_still_needs_scan_id_and_refuses_repo_scans(api):
    sid = scan(api, connect(api))
    assert api.post("/findings/F-001/fix").status_code == 422
    r = api.post(f"/findings/F-001/fix?scan_id={sid}")
    assert r.status_code == 409 and "DPDP" in r.json()["detail"]


# ---- fix

def log_finding(api):
    return next(i for i in api.get("/findings").json()["items"] if i["check"] == "log_pii")["human_id"]


def test_fix_is_refused_for_a_repo_outside_dpdp_fix_repos(api, monkeypatch):
    scan(api, connect(api))
    monkeypatch.setenv("DPDP_FIX_REPOS", "acme/other")
    r = api.post(f"/findings/{log_finding(api)}/fix?mode=cached", headers=TOKEN)
    assert r.status_code == 403 and "DPDP_FIX_REPOS" in r.json()["detail"]
    monkeypatch.delenv("DPDP_FIX_REPOS")
    assert api.post(f"/findings/{log_finding(api)}/fix?mode=cached", headers=TOKEN).status_code == 403


def test_cached_fix_sets_fixed_labels_it_and_leaves_the_stored_scan_alone(api):
    sid = scan(api, connect(api))
    before = api.get(f"/scan/{sid}").json()
    hid = log_finding(api)
    r = api.post(f"/findings/{hid}/fix?mode=cached", json={"actor": "U9"}, headers=TOKEN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "cached_golden" and body["verification"] is None and body["record"]["status"] == "fixed"
    assert body["record"]["status_by"] == "U9"
    assert api.get(f"/scan/{sid}").json() == before  # the stored scan JSON was not edited
    types = [e["type"] for e in api.get(f"/findings/{hid}").json()["events"]]
    assert types == ["finding_created", "fix_started", "fix_verified", "status_changed"]
    assert api.post(f"/findings/{hid}/fix?mode=cached", headers=TOKEN).status_code == 409
    again = scan(api, 1)  # the repo is unchanged, so the next scan sees it again and reopens it
    assert hid in api.get(f"/scans/{again}/delta").json()["reopened"]
    assert api.get(f"/findings/{hid}").json()["status"] == "open"


def test_cached_fix_for_a_finding_without_a_template_is_400(api):
    scan(api, connect(api))
    hid = next(i for i in api.get("/findings").json()["items"] if not i["fix_available"])["human_id"]
    r = api.post(f"/findings/{hid}/fix?mode=cached", headers=TOKEN)
    assert r.status_code == 400
    assert "fix_failed" in [e["type"] for e in api.get(f"/findings/{hid}").json()["events"]]


def test_live_fix_re_checks_out_the_commit_seeds_a_temp_db_and_verifies(api):
    sid = scan(api, connect(api))
    hid = log_finding(api)
    r = api.post(f"/findings/{hid}/fix?mode=live", json={"actor": "U9"}, headers=TOKEN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "live" and body["fallback_reason"] is None, body["fallback_reason"]
    assert body["finding"]["fix"]["verified"] is True and body["verification"]["rescan_result"] == "gone"
    assert body["record"]["status"] == "fixed" and "logger.info" in body["finding"]["fix"]["diff"]
    assert (api.state / f"{sid}.json").exists() and api.get(f"/scan/{sid}").json()["findings"][2]["status"] == "open"


def test_live_fix_falls_back_to_the_cached_result_when_the_checkout_fails(api, monkeypatch):
    scan(api, connect(api))
    hid = log_finding(api)
    monkeypatch.setattr(repo_scan, "GIT_BASE", "file:///does/not/exist")
    r = api.post(f"/findings/{hid}/fix?mode=live", headers=TOKEN)
    assert r.status_code == 200
    assert r.json()["mode"] == "cached_golden" and "RepoError" in r.json()["fallback_reason"]
    assert r.json()["record"]["status"] == "fixed"
    assert json.loads(api.get("/audit/events", params={"type": "fix_verified"}).text)[0]["meta"]["mode"] == "cached_golden"


# ---- monitor on the real scan path (block 05)

def due_now(api, repo_id, minutes=1):
    api.post(f"/repos/{repo_id}/watch", json={"minutes": minutes, "actor": "U1"}, headers=TOKEN)
    core = api.app.state.core
    core.store.run("UPDATE repos SET next_run_at='2000-01-01T00:00:00+00:00' WHERE id=?", (repo_id,))
    return core


def test_the_monitor_scans_a_real_repo_and_queues_scan_delta_and_health_changed(api):
    from dpdp_lens.monitor import Monitor
    rid = connect(api)
    core = due_now(api, rid)
    m = Monitor(core.store, core.scan_repo_now)
    assert m.tick() == [rid]
    outbox = api.get("/outbox").json()
    assert [o["kind"] for o in outbox if o["kind"] != "status_changed"] == ["scan_delta", "health_changed"]
    delta = next(o for o in outbox if o["kind"] == "scan_delta")
    assert (delta["repo_id"], delta["scan_id"], delta["human_id"]) == (rid, "S-001", "")
    assert api.get("/scan/S-001").json()["coverage"]["mode"] == "static"
    assert api.get(f"/repos/{rid}/history").json()[0]["trigger"] == "schedule"
    assert m.tick() == []  # next_run_at moved, nothing is due


def test_a_broken_remote_makes_the_repo_unknown_with_one_alert_and_a_visible_error(api):
    from dpdp_lens.monitor import Monitor
    rid = connect(api, "acme/missing")
    core = due_now(api, rid)
    m = Monitor(core.store, core.scan_repo_now)
    m.tick()
    core.store.run("UPDATE repos SET next_run_at='2000-01-01T00:00:00+00:00'")
    m.tick()
    h = api.get(f"/repos/{rid}/health").json()
    assert h["status"] == "unknown" and h["failed_streak"] == 2 and "RepoError" in h["last_error"]
    assert "the last 2 scans failed or were incomplete" in h["reasons"]
    assert [o["kind"] for o in api.get("/outbox").json()] == ["health_changed"]  # once, not once per failed scan
    assert api.get("/repos").json()[0]["health"] == "unknown"
