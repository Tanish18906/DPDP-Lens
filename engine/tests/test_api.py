from fastapi.testclient import TestClient

from conftest import BACKEND
from dpdp_lens.api import _is_local, create_app
from dpdp_lens.runner import run_scan


def body(target, db, **over):
    return {"target_url": target, "repo_path": str(BACKEND), "db_path": str(db), **over}


def test_health():
    assert TestClient(create_app()).get("/health").json() == {"ok": True}


def test_scan_then_get_matches_run_scan(target, target_db):
    c = TestClient(create_app())
    r = c.post("/scan", json=body(target, target_db))
    assert r.status_code == 200 and r.json() == {"scan_id": "S-001"}
    got = c.get("/scan/S-001").json()
    expected = run_scan(target, str(BACKEND), str(target_db)).model_dump()
    for d in (got, expected):
        d.pop("scanned_at")
    assert got == expected
    assert len(got["findings"]) == 6 and got["score"] == 28
    assert c.post("/scan", json=body(target, target_db)).json() == {"scan_id": "S-002"}


def test_running_scan_returns_status():
    app = create_app()
    app.state.scans["S-009"] = {"status": "running"}
    assert TestClient(app).get("/scan/S-009").json() == {"status": "running"}


def test_unknown_scan_is_404_json():
    r = TestClient(create_app()).get("/scan/S-404")
    assert r.status_code == 404 and r.json() == {"error": "Not Found", "detail": "Unknown scan S-404"}


def test_failed_scan_is_500_json(target, fresh_db):
    def boom(*a, **k):
        raise RuntimeError("boom")

    c = TestClient(create_app(scan_fn=boom))
    sid = c.post("/scan", json=body(target, fresh_db)).json()["scan_id"]
    r = c.get(f"/scan/{sid}")
    assert r.status_code == 500 and r.json() == {"error": "Internal Server Error", "detail": "RuntimeError: boom"}


def test_bad_input_is_400_or_422(target, fresh_db, tmp_path):
    c = TestClient(create_app())
    for over in ({"target_url": "http://example.com"}, {"target_url": "ftp://localhost"},
                 {"repo_path": str(tmp_path / "nope")}, {"db_path": str(tmp_path / "nope.db")}):
        r = c.post("/scan", json=body(target, fresh_db, **over))
        assert r.status_code == 400 and set(r.json()) == {"error", "detail"}
    r = c.post("/scan", json={"target_url": target})
    assert r.status_code == 422 and set(r.json()) == {"error", "detail"}


def test_is_local():
    assert all(_is_local(u) for u in ("http://localhost:8000", "http://127.0.0.1:8000", "http://192.168.1.5:8000"))
    assert not any(_is_local(u) for u in ("http://example.com", "http://8.8.8.8", "file:///etc/passwd", "localhost"))


def test_fix_not_implemented_yet():
    r = TestClient(create_app()).post("/findings/F-001/fix?scan_id=S-001")
    assert r.status_code == 501 and set(r.json()) == {"error", "detail"}


def test_cors_allows_localhost_only():
    c = TestClient(create_app())
    ok = c.get("/health", headers={"Origin": "http://localhost:5174"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5174"
    assert "access-control-allow-origin" not in c.get("/health", headers={"Origin": "https://evil.example"}).headers
