"""Saved scans survive an engine restart, and the runner reports real progress."""
import time
import json

from fastapi.testclient import TestClient

from dpdp_lens import runner
from dpdp_lens.api import create_app
from dpdp_lens.fixer.verify import Verification
from dpdp_lens.models import Fix
from test_fix_api import GOOD, fake_scan

BODY = {"target_url": "http://localhost:8000", "repo_path": ".", "db_path": "x.db"}


def live_ok(finding, repo, db, **kw):
    return Verification(fix=GOOD.model_copy(update={"score_before": kw["score_before"]}), rescan=None, tests_output="")


def boot(tmp_path, **kw):
    (tmp_path / "x.db").write_text("")
    return TestClient(create_app(scan_fn=kw.pop("scan_fn", fake_scan), repo_root=tmp_path, fix_fn=live_ok,
                                 golden_dir=tmp_path / "golden", state_dir=tmp_path / "state", **kw))


def test_a_finished_scan_comes_back_after_a_restart_and_ids_continue(tmp_path):
    first = boot(tmp_path)
    assert first.post("/scan", json=BODY).json() == {"scan_id": "S-001"}
    saved = first.get("/scan/S-001").json()
    second = boot(tmp_path)  # new app object, same state folder: an engine restart
    assert second.get("/scan/S-001").json() == saved
    assert second.post("/scan", json=BODY).json() == {"scan_id": "S-002"}


def test_a_fix_after_the_restart_works_and_is_saved_with_its_mode(tmp_path):
    first = boot(tmp_path)
    first.post("/scan", json=BODY)
    second = boot(tmp_path)
    r = second.post("/findings/F-001/fix", params={"scan_id": "S-001"})
    assert r.status_code == 200 and r.json()["mode"] == "live" and r.json()["finding"]["status"] == "verified_fixed"
    third = boot(tmp_path)  # restart again: the fixed state and the mode are still there
    assert third.get("/scan/S-001").json()["findings"][0]["status"] == "verified_fixed"
    assert 'Cached golden' not in third.get("/report/S-001").text and "Verified fixed" in third.get("/report/S-001").text


def test_an_unreadable_state_file_is_skipped_and_the_others_load(tmp_path):
    first = boot(tmp_path)
    first.post("/scan", json=BODY)
    (tmp_path / "state" / "S-002.json").write_text("{not json")
    (tmp_path / "state" / "S-003.json").write_text(json.dumps({"scan": {"nope": 1}, "inputs": [], "fix_modes": {}}))
    second = boot(tmp_path)
    assert second.get("/scan/S-001").status_code == 200 and second.get("/scan/S-002").status_code == 404
    assert second.post("/scan", json=BODY).json() == {"scan_id": "S-002"}  # ids continue after the last good file


def test_a_disk_problem_does_not_break_the_scan(tmp_path):
    (tmp_path / "x.db").write_text("")
    (tmp_path / "state").write_text("a file where the folder should be")
    c = TestClient(create_app(scan_fn=fake_scan, repo_root=tmp_path, state_dir=tmp_path / "state"))
    assert c.post("/scan", json=BODY).json() == {"scan_id": "S-001"}
    assert c.get("/scan/S-001").status_code == 200  # still served from memory


def test_no_state_dir_means_nothing_is_written(tmp_path):
    (tmp_path / "x.db").write_text("")
    TestClient(create_app(scan_fn=fake_scan, repo_root=tmp_path)).post("/scan", json=BODY)
    assert not (tmp_path / "state").exists() and not list(tmp_path.glob("*.json"))


# --- progress
def test_run_scan_reports_each_step_before_it_runs(monkeypatch):
    monkeypatch.setattr(runner, "SCANNERS", [("one", lambda *a: []), ("two", lambda *a: [])])
    monkeypatch.setattr(runner.notice_drift, "build", lambda t, d: (_ for _ in ()).throw(RuntimeError("skip")))
    calls = []
    runner.run_scan("http://x", ".", "x.db", progress=lambda *a: calls.append(a), frontend_url=None)
    assert calls == [("one", 0, 3), ("two", 1, 3), ("notice_drift", 2, 3)]


def test_run_scan_with_a_custom_list_has_no_drift_step():
    calls = []
    runner.run_scan("http://x", ".", "x.db", scanners=[("a", lambda *a: [])], progress=lambda *a: calls.append(a))
    assert calls == [("a", 0, 1)]


def test_the_api_shows_progress_while_a_scan_runs_and_drops_it_after(tmp_path):
    seen = {}

    def slow_scan(target, repo, db, scan_id, progress):
        progress("api_scan", 2, 9)
        seen.update(c.app.state.scans[scan_id])  # what GET /scan/{id} would return right now
        return fake_scan(target, repo, db, scan_id)

    (tmp_path / "x.db").write_text("")
    c = TestClient(create_app(scan_fn=slow_scan, repo_root=tmp_path))
    c.post("/scan", json=BODY)
    assert seen == {"status": "running", "step": "api_scan", "done": 2, "total": 9, "steps_ms": []}
    assert "status" not in c.get("/scan/S-001").json() and c.get("/scan/S-001").json()["scan_id"] == "S-001"


def test_the_api_measures_each_scan_step(tmp_path):
    seen = {}

    def two_steps(target, repo, db, scan_id, progress):
        progress("api_scan", 0, 2)
        time.sleep(0.05)
        progress("db_scan", 1, 2)
        seen.update(c.app.state.scans[scan_id])
        return fake_scan(target, repo, db, scan_id)

    (tmp_path / "x.db").write_text("")
    c = TestClient(create_app(scan_fn=two_steps, repo_root=tmp_path))
    c.post("/scan", json=BODY)
    assert [s["step"] for s in seen["steps_ms"]] == ["api_scan"] and seen["steps_ms"][0]["ms"] >= 50
    steps = c.get("/scan/S-001/timings").json()["steps"]
    assert [s["step"] for s in steps] == ["api_scan", "db_scan"] and all(s["ms"] >= 0 for s in steps)
    assert c.get("/scan/S-999/timings").status_code == 404


def test_a_scan_function_without_progress_still_works(tmp_path):
    (tmp_path / "x.db").write_text("")
    c = TestClient(create_app(scan_fn=fake_scan, repo_root=tmp_path))
    assert c.post("/scan", json=BODY).status_code == 200 and c.get("/scan/S-001").status_code == 200
