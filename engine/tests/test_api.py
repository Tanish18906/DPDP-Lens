from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import BACKEND
from dpdp_lens.api import _is_local, create_app, default_repo_root
from dpdp_lens.runner import run_scan


def open_app(**kw):
    """App that may scan anywhere: for tests whose temp DBs live outside the repo."""
    return create_app(repo_root="/", **kw)


def body(target, db, **over):
    return {"target_url": target, "repo_path": str(BACKEND), "db_path": str(db), **over}


def test_health():
    assert TestClient(create_app()).get("/health").json() == {"ok": True}


def test_scan_then_get_matches_run_scan(target, target_db):
    c = TestClient(open_app())
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

    c = TestClient(open_app(scan_fn=boom))
    sid = c.post("/scan", json=body(target, fresh_db)).json()["scan_id"]
    r = c.get(f"/scan/{sid}")
    assert r.status_code == 500 and r.json() == {"error": "Internal Server Error", "detail": "RuntimeError: boom"}


def test_bad_input_is_400_or_422(target, fresh_db, tmp_path):
    c = TestClient(open_app())
    for over in ({"target_url": "http://example.com"}, {"target_url": "ftp://localhost"},
                 {"repo_path": str(tmp_path / "nope")}, {"db_path": str(tmp_path / "nope.db")}):
        r = c.post("/scan", json=body(target, fresh_db, **over))
        assert r.status_code == 400 and set(r.json()) == {"error", "detail"}
    r = c.post("/scan", json={"target_url": target})
    assert r.status_code == 422 and set(r.json()) == {"error", "detail"}


def test_is_local():
    assert all(_is_local(u) for u in ("http://localhost:8000", "http://127.0.0.1:8000", "http://192.168.1.5:8000"))
    assert not any(_is_local(u) for u in ("http://example.com", "http://8.8.8.8", "file:///etc/passwd", "localhost"))


def test_fix_unknown_scan_is_404_json():
    r = TestClient(create_app()).post("/findings/F-001/fix?scan_id=S-001")
    assert r.status_code == 404 and set(r.json()) == {"error", "detail"}


def test_cors_allows_localhost_only():
    c = TestClient(create_app())
    ok = c.get("/health", headers={"Origin": "http://localhost:5174"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5174"
    assert "access-control-allow-origin" not in c.get("/health", headers={"Origin": "https://evil.example"}).headers


# Repo root scoping: relative paths resolve against the root, nothing outside it can be scanned.
@pytest.fixture
def scoped(tmp_path):
    """App rooted at tmp_path/repo with a stub scanner that records the paths it is given."""
    root = tmp_path / "repo"
    (root / "backend").mkdir(parents=True)
    (root / "x.db").write_text("")
    outside = tmp_path / "outside"
    (outside / "backend").mkdir(parents=True)
    (outside / "y.db").write_text("")
    (root / "link").symlink_to(outside)
    calls = []

    def stub(target, repo, db, scan_id):
        calls.append((repo, db))

    return TestClient(create_app(scan_fn=stub, repo_root=root)), root, outside, calls


def scan_body(repo, db):
    return {"target_url": "http://localhost:8000", "repo_path": str(repo), "db_path": str(db)}


def test_relative_paths_resolve_against_repo_root(scoped):
    c, root, _, calls = scoped
    assert c.post("/scan", json=scan_body("backend", "x.db")).status_code == 200
    assert c.post("/scan", json=scan_body("backend/../backend", "./x.db")).status_code == 200  # stays inside
    assert calls == [(str(root / "backend"), str(root / "x.db"))] * 2


def test_absolute_path_inside_repo_works(scoped):
    c, root, _, calls = scoped
    assert c.post("/scan", json=scan_body(root / "backend", root / "x.db")).status_code == 200
    assert calls == [(str(root / "backend"), str(root / "x.db"))]


@pytest.mark.parametrize("repo,db", [
    ("../outside/backend", "x.db"), ("backend", "../outside/y.db"),      # ../ escapes
    ("link/backend", "x.db"), ("backend", "link/y.db"),                  # symlink inside the repo pointing out
    ("/etc", "x.db"), ("backend", "/etc/passwd"),                        # absolute paths outside
])
def test_paths_outside_repo_are_rejected(scoped, repo, db):
    c, _, _, calls = scoped
    r = c.post("/scan", json=scan_body(repo, db))
    assert r.status_code == 400 and "inside the project folder" in r.json()["detail"]
    assert calls == []


def test_absolute_path_to_a_real_folder_outside_repo_is_rejected(scoped):
    c, _, outside, calls = scoped
    r = c.post("/scan", json=scan_body(outside / "backend", outside / "y.db"))
    assert r.status_code == 400 and "inside the project folder" in r.json()["detail"] and calls == []


def test_repo_root_env_override_and_default(scoped, monkeypatch):
    _, root, _, calls = scoped
    assert default_repo_root() == Path(__file__).resolve().parents[2]  # the real repo root
    monkeypatch.setenv("DPDP_REPO_ROOT", str(root))
    assert default_repo_root() == root.resolve()
    c = TestClient(create_app(scan_fn=lambda *a, **k: calls.append(a)))
    assert c.post("/scan", json=scan_body("backend", "x.db")).status_code == 200
    assert c.post("/scan", json=scan_body("../outside", "x.db")).status_code == 400
