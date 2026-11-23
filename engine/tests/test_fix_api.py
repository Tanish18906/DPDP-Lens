import json

import pytest
from fastapi.testclient import TestClient

from conftest import BACKEND
from dpdp_lens.api import create_app
from dpdp_lens.fixer.templates import PatchError
from dpdp_lens.fixer.verify import FixTimeout, Verification
from dpdp_lens.models import (Counts, Evidence, Finding, Fix, Location, ScanResult, compute_counts, compute_score)


def finding(fid, check, severity, available):
    return Finding(id=fid, check=check, layer="api", severity=severity, title=check, explanation="e", clauses=[],
                   evidence=Evidence(kind="http", summary="s", location=Location(url="http://localhost:8000/api/students")),
                   fix=Fix(available=available))


def fake_scan(target, repo, db, scan_id):
    fs = [finding("F-001", "api_pii_exposure", "critical", True), finding("F-002", "api_idor", "high", False)]
    return ScanResult(scan_id=scan_id, target=target, scanned_at="2026-11-23T00:00:00+00:00", score=compute_score(fs),
                      counts=compute_counts(fs), findings=fs)


GOOD = Fix(available=True, diff="--- a\n+++ b\n", verified=True, rescan_passed=True, tests_passed=True, score_after=95)


def live_ok(finding, repo, db, **kw):
    return Verification(fix=GOOD.model_copy(update={"score_before": kw["score_before"]}), rescan=None, tests_output="")


def raises(exc):
    def fn(*a, **k):
        raise exc
    return fn


@pytest.fixture
def golden(tmp_path):
    d = tmp_path / "golden"
    d.mkdir()
    (d / "V1.json").write_text(json.dumps({"golden_id": "V1", "check": "api_pii_exposure", "source": "live",
                                           "diff": "--- golden\n", "verified": True, "rescan_passed": True,
                                           "tests_passed": True}))
    return d


def client(tmp_path, fix_fn, golden_dir):
    (tmp_path / "x.db").write_text("")
    c = TestClient(create_app(scan_fn=fake_scan, repo_root=tmp_path, fix_fn=fix_fn, golden_dir=golden_dir))
    body = {"target_url": "http://localhost:8000", "repo_path": ".", "db_path": "x.db"}
    assert c.post("/scan", json=body).json() == {"scan_id": "S-001"}
    return c


def fix(c, fid="F-001", **params):
    return c.post(f"/findings/{fid}/fix", params={"scan_id": "S-001", **params})


def test_live_fix_updates_the_stored_scan(tmp_path, golden):
    c = client(tmp_path, live_ok, golden)
    r = fix(c)
    body = r.json()
    assert r.status_code == 200 and body["mode"] == "live" and body["fallback_reason"] is None
    assert (body["score_before"], body["score_after"]) == (85, 95)  # 100 - 10 - 5, then critical gone
    assert body["finding"]["status"] == "verified_fixed" and body["finding"]["fix"]["verified"] is True
    stored = c.get("/scan/S-001").json()
    assert stored["score"] == 95 and stored["counts"]["critical"] == 0
    assert next(f for f in stored["findings"] if f["id"] == "F-001")["status"] == "verified_fixed"
    assert fix(c).status_code == 409  # already fixed


def test_live_fix_returns_its_verification_log_and_a_cached_one_does_not(tmp_path, golden):
    log = {"steps": [{"step": "copy", "ms": 12}], "total_ms": 12, "pytest_summary": "3 passed in 0.10s"}
    c = client(tmp_path, lambda f, r, d, **kw: Verification(fix=GOOD, rescan=None, tests_output="", log=log), golden)
    assert fix(c).json()["verification"] == log
    c = client(tmp_path, live_ok, golden)
    assert fix(c, mode="cached").json()["verification"] is None


@pytest.mark.parametrize("exc,expected", [(RuntimeError("boom"), "RuntimeError: boom"), (FixTimeout("too slow"), "FixTimeout: too slow")])
def test_live_failure_falls_back_to_golden_and_says_so(tmp_path, golden, exc, expected):
    c = client(tmp_path, raises(exc), golden)
    body = fix(c).json()
    assert body["mode"] == "cached_golden" and body["fallback_reason"] == expected
    assert body["finding"]["fix"]["diff"] == "--- golden\n" and body["finding"]["status"] == "verified_fixed"
    assert (body["score_before"], body["score_after"]) == (85, 95)  # scored against the actual scan


def test_live_failure_without_golden_is_a_502(tmp_path):
    c = client(tmp_path, raises(RuntimeError("boom")), tmp_path / "none")
    r = fix(c)
    assert r.status_code == 502 and "boom" in r.json()["detail"] and "no cached golden" in r.json()["detail"]
    assert c.get("/scan/S-001").json()["score"] == 85  # unchanged


def test_cached_mode_replays_golden_without_a_reason(tmp_path, golden):
    c = client(tmp_path, raises(AssertionError("live must not run")), golden)
    body = fix(c, mode="cached").json()
    assert body["mode"] == "cached_golden" and body["fallback_reason"] is None and body["score_after"] == 95


def test_cached_mode_without_golden_is_404(tmp_path):
    assert fix(client(tmp_path, live_ok, tmp_path / "none"), mode="cached").status_code == 404


def test_patch_error_is_422_and_never_falls_back(tmp_path, golden):
    c = client(tmp_path, raises(PatchError("snippet not found")), golden)
    r = fix(c)
    assert r.status_code == 422 and "snippet not found" in r.json()["detail"]
    stored = c.get("/scan/S-001").json()
    assert stored["score"] == 85 and next(f for f in stored["findings"] if f["id"] == "F-001")["status"] == "open"


def test_unverified_live_result_is_returned_honestly(tmp_path, golden):
    bad = Fix(available=True, diff="d", verified=False, rescan_passed=False, tests_passed=True, score_after=85)
    c = client(tmp_path, lambda *a, **k: Verification(fix=bad, rescan=None, tests_output=""), golden)
    body = fix(c).json()
    assert body["mode"] == "live" and body["finding"]["status"] == "open" and body["finding"]["fix"]["verified"] is False
    assert body["score_after"] == 85 and c.get("/scan/S-001").json()["score"] == 85


def test_fix_error_cases(tmp_path, golden):
    c = client(tmp_path, live_ok, golden)
    assert fix(c, "F-002").status_code == 400            # no automated fix
    assert fix(c, "F-999").status_code == 404            # unknown finding
    assert c.post("/findings/F-001/fix", params={"scan_id": "S-404"}).status_code == 404
    assert fix(c, mode="bogus").status_code == 422


def test_fix_end_to_end_through_the_api(target, target_db, tmp_path):
    c = TestClient(create_app(repo_root="/", golden_dir=tmp_path / "golden"))
    c.post("/scan", json={"target_url": target, "repo_path": str(BACKEND), "db_path": str(target_db)})
    scan = c.get("/scan/S-001").json()
    v1 = next(f for f in scan["findings"] if f["check"] == "api_pii_exposure")
    assert scan["score"] == 57 and v1["fix"]["available"] is True
    r = fix(c, v1["id"])
    body = r.json()
    assert r.status_code == 200 and body["mode"] == "live" and body["fallback_reason"] is None
    assert body["finding"]["status"] == "verified_fixed"
    assert body["finding"]["fix"]["rescan_passed"] and body["finding"]["fix"]["tests_passed"] and "get_admin_user" in body["finding"]["fix"]["diff"]
    assert (body["score_before"], body["score_after"]) == (57, 67) == (body["finding"]["fix"]["score_before"], body["finding"]["fix"]["score_after"])
    assert c.get("/scan/S-001").json()["score"] == 67
    assert (tmp_path / "golden" / "V1.json").exists()


def test_two_fixes_on_one_scan_score_cumulatively(target, target_db, tmp_path):
    c = TestClient(create_app(repo_root="/", golden_dir=tmp_path / "golden"))
    c.post("/scan", json={"target_url": target, "repo_path": str(BACKEND), "db_path": str(target_db)})
    ids = {f["check"]: f["id"] for f in c.get("/scan/S-001").json()["findings"]}
    first, second = fix(c, ids["api_pii_exposure"]).json(), fix(c, ids["log_pii"]).json()
    assert (first["score_before"], first["score_after"]) == (57, 67)
    assert (second["score_before"], second["score_after"]) == (67, 72)
    assert second["finding"]["fix"]["verified"] and second["finding"]["fix"]["score_after"] == 72  # not the V3-only re-scan (62)
    stored = c.get("/scan/S-001").json()
    assert stored["score"] == 72 and stored["counts"] == {"critical": 1, "high": 3, "medium": 1, "low": 1}
    assert {(tmp_path / "golden" / n).exists() for n in ("V1.json", "V3.json")} == {True}
