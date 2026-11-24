"""GET /repos/{id}/diff: a scan against the repo's baseline. A hand-built store, no network and no clone."""
import pytest
from fastapi.testclient import TestClient

from dpdp_lens import ingest
from dpdp_lens.api import create_app
from dpdp_lens.models import Coverage, ScanError, ScanResult
from dpdp_lens.store import Store
from test_contract import load_sample

STATIC, LIVE = "log_pii", "api_pii_exposure"
SAMPLE = {f.check: f for f in load_sample().findings}


def finding(check, fp):
    return SAMPLE[check].model_copy(update={"check": check, "fingerprint": fp})


def scan(sid, findings, run=(STATIC,), mode="static", errors=()):
    return ScanResult(scan_id=sid, target="", scanned_at="2026-11-23T00:00:00+00:00", score=100, counts={}, findings=list(findings),
                      scan_errors=list(errors), complete=not errors, repo="acme/app", commit="c" * 40,
                      coverage=Coverage(mode=mode, checks_run=list(run)))


@pytest.fixture
def api(tmp_path):
    store = Store(":memory:")
    store.run("INSERT INTO repos(full_name, created_at) VALUES ('acme/app', '2026-11-23T00:00:00+00:00')")
    client = TestClient(create_app(repo_root=tmp_path, state_dir=tmp_path / "state", store=store))
    client.store = store
    return client


def put(api, s, trigger="manual"):
    ingest.ingest_scan(api.store, 1, s, trigger, "test")


def diff(api, **params):
    r = api.get("/repos/1/diff", params=params)
    assert r.status_code == 200, r.text
    return r.json()


A, B, C = (finding(STATIC, f"{x}" * 16) for x in "abc")
X = finding(LIVE, "x" * 16)


def test_new_resolved_and_persistent_against_the_baseline(api):
    put(api, scan("S-001", [A, B]))  # first complete scan: the baseline. A is DPDP-001, B is DPDP-002
    put(api, scan("S-002", [A, C]))
    d = diff(api)  # default: the latest scan
    assert d == {"repo": "acme/app", "baseline_scan_id": "S-001", "scan_id": "S-002", "complete": True,
                 "new": ["DPDP-003"], "resolved": ["DPDP-002"], "persistent": ["DPDP-001"]}
    assert diff(api, scan_id="S-001") == {**d, "scan_id": "S-001", "new": [], "resolved": [], "persistent": ["DPDP-001", "DPDP-002"]}


def test_diff_is_against_the_baseline_not_the_previous_scan(api):
    put(api, scan("S-001", [A]))
    put(api, scan("S-002", [A, B]))
    put(api, scan("S-003", [A, B]))
    assert diff(api)["new"] == ["DPDP-002"]  # still new: the baseline is S-001, and S-003 saw nothing new since S-002
    assert api.get("/scans/S-003/delta").json()["new"] == []  # the per scan delta says nothing new


def test_a_check_the_scan_did_not_run_is_not_resolved(api):
    put(api, scan("S-001", [A, X], run=(STATIC, LIVE), mode="full"))
    put(api, scan("S-002", [A], run=(STATIC,)))  # static scan: the live check was not looked at
    d = diff(api)
    assert d["resolved"] == [] and d["persistent"] == ["DPDP-001"] and d["complete"] is True


def test_an_incomplete_scan_is_marked_and_resolves_nothing(api):
    put(api, scan("S-001", [A, B]))
    put(api, scan("S-002", [A], run=(), errors=[ScanError(scanner="log_scan", kind="timeout", message="slow")]))
    d = diff(api)
    assert d["complete"] is False and d["resolved"] == [] and d["persistent"] == ["DPDP-001"]


def test_a_failed_scan_has_empty_lists_and_complete_false(api):
    put(api, scan("S-001", [A]))
    ingest.record_scan_failed(api.store, 1, "S-002", "manual", "test", "clone failed")
    d = diff(api)
    assert d["scan_id"] == "S-002" and d["complete"] is False and d["new"] == d["resolved"] == d["persistent"] == []


def test_no_baseline_is_a_clear_404(api):
    r = api.get("/repos/1/diff")
    assert r.status_code == 404 and set(r.json()) == {"error", "detail"} and "no baseline" in r.json()["detail"]
    ingest.record_scan_failed(api.store, 1, "S-001", "manual", "test", "clone failed")  # a failed scan is not a baseline either
    assert "no baseline" in api.get("/repos/1/diff").json()["detail"]


def test_unknown_repo_and_unknown_scan_are_404(api):
    assert api.get("/repos/99/diff").status_code == 404
    put(api, scan("S-001", [A]))
    r = api.get("/repos/1/diff", params={"scan_id": "S-099"})
    assert r.status_code == 404 and "S-099" in r.json()["detail"]
    api.store.run("INSERT INTO repos(full_name, created_at) VALUES ('acme/other', '2026-11-23T00:00:00+00:00')")
    ingest.ingest_scan(api.store, 2, scan("S-002", [A]).model_copy(update={"repo": "acme/other"}), "manual", "test")
    assert api.get("/repos/1/diff", params={"scan_id": "S-002"}).status_code == 404  # another repo's scan


def test_the_route_is_a_read_so_it_needs_no_token_and_follows_an_explicit_baseline(api, monkeypatch):
    put(api, scan("S-001", [A]))
    put(api, scan("S-002", [A, B]))
    monkeypatch.setenv("DPDP_API_TOKEN", "t")
    assert api.post("/repos/1/baseline", json={"scan_id": "S-002", "actor": "u"}, headers={"X-DPDP-Token": "t"}).status_code == 200
    d = diff(api)
    assert d["baseline_scan_id"] == "S-002" and d["new"] == [] and d["persistent"] == ["DPDP-001", "DPDP-002"]
