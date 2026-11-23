"""Block 05: scheduled monitoring and its alerts. A fake clock and a fake scan function, no network, no real time."""
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dpdp_lens import audit, ingest, monitor
from dpdp_lens.ingest import health, ingest_scan, record_scan_failed
from dpdp_lens.monitor import Monitor, attach_monitor
from dpdp_lens.store import SCHEMA_VERSION, Store
from test_store_ingest import finding, scan

T0 = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
CRITICAL = lambda sid, extra=(): scan(sid, [finding(severity="critical"), *extra])  # noqa: E731
CLEAN = lambda sid: scan(sid, [finding(severity="low")])  # noqa: E731


def iso(dt):
    return dt.isoformat(timespec="seconds")


CLOCK = [T0]


@pytest.fixture(autouse=True)
def fake_clock(monkeypatch):
    """audit.now() is the one clock of the engine (events, scans, health), so a test moves time by setting CLOCK."""
    CLOCK[0] = T0
    monkeypatch.setattr(audit, "now", lambda: iso(CLOCK[0]))


def at(minutes=0, seconds=0):
    CLOCK[0] = T0 + timedelta(minutes=minutes, seconds=seconds)
    return CLOCK[0]


def kinds(store, kind=None):
    rows = store.all("SELECT * FROM outbox WHERE kind != 'status_changed' ORDER BY id")
    return [r["kind"] for r in rows if kind in (None, r["kind"])]


def make_store(path=":memory:", watch=5, next_run=None):
    s = Store(path)
    s.run("INSERT INTO repos(full_name, created_at, watch_minutes, next_run_at) VALUES ('acme/app', 'x', ?, ?)", (watch, next_run))
    return s


class FakeScan:
    """Stands in for api_v2's scan_repo_now: stores a scan the way the real one does and returns its id."""

    def __init__(self, store, *outcomes):
        self.store, self.outcomes, self.calls, self.busy = store, list(outcomes), [], False

    def __call__(self, repo, trigger):
        self.calls.append((repo["id"], trigger))
        if self.busy:
            return None
        sid = f"S-{self.store.one('SELECT COUNT(*) FROM scans')[0] + 1:03d}"
        out = self.outcomes.pop(0) if self.outcomes else CLEAN
        if out == "fail":
            record_scan_failed(self.store, repo["id"], sid, trigger, "monitor", "RepoError: clone failed")
        else:
            ingest_scan(self.store, repo["id"], out(sid), trigger, "monitor")
        return sid


def next_run(store):
    return store.one("SELECT next_run_at FROM repos")[0]


# ---- schedule

def test_a_repo_is_scanned_when_due_and_the_next_run_moves_by_the_interval():
    s = make_store(next_run=iso(T0 - timedelta(minutes=1)))
    fake = FakeScan(s)
    assert Monitor(s, fake).tick(at()) == [1] and fake.calls == [(1, "schedule")]
    assert next_run(s) == iso(T0 + timedelta(minutes=5))


def test_a_repo_that_is_not_due_is_left_alone():
    s = make_store(next_run=iso(T0 + timedelta(minutes=2)))
    fake = FakeScan(s)
    assert Monitor(s, fake).tick(at()) == [] and fake.calls == []


def test_a_repo_without_a_watch_is_never_scanned():
    s = make_store(watch=None)
    fake = FakeScan(s)
    assert Monitor(s, fake).tick(at(60 * 24 * 9)) == [] and fake.calls == []


def test_a_watch_without_a_next_run_is_due_at_once():
    s = make_store()
    assert Monitor(s, FakeScan(s)).tick(at()) == [1]


def test_a_missed_window_runs_once_not_as_a_burst():
    s = make_store(watch=1, next_run=iso(T0 - timedelta(hours=3)))
    fake = FakeScan(s)
    m = Monitor(s, fake)
    assert m.tick(at()) == [1]
    assert m.tick(at()) == [] and m.tick(at(seconds=30)) == [] and len(fake.calls) == 1
    assert next_run(s) == iso(T0 + timedelta(minutes=1))
    assert m.tick(at(1)) == [1]


def test_a_busy_repo_is_skipped_and_tried_again_at_the_next_tick():
    s = make_store(next_run=iso(T0))
    fake = FakeScan(s)
    fake.busy = True
    m = Monitor(s, fake)
    assert m.tick(at()) == [] and next_run(s) == iso(T0)  # the schedule did not move
    fake.busy = False
    assert m.tick(at(seconds=10)) == [1]


def test_the_schedule_survives_reopening_the_database(tmp_path):
    s = make_store(tmp_path / "dpdp.db", next_run=iso(T0 - timedelta(minutes=1)))
    Monitor(s, FakeScan(s)).tick(at())
    due = next_run(s)
    s.close()
    again = Store(tmp_path / "dpdp.db")
    fake = FakeScan(again)
    assert next_run(again) == due and Monitor(again, fake).tick(at(1)) == [] and fake.calls == []
    assert Monitor(again, fake).tick(at(5)) == [1]


def test_a_scan_function_that_raises_does_not_stop_the_tick_or_other_repos():
    s = make_store(next_run=iso(T0))
    s.run("INSERT INTO repos(full_name, created_at, watch_minutes, next_run_at) VALUES ('acme/two', 'x', 5, ?)", (iso(T0),))
    seen = []

    def scan_fn(repo, trigger):
        seen.append(repo["full_name"])
        if repo["full_name"] == "acme/app":
            raise RuntimeError("store is broken")
        return "S-001"

    assert Monitor(s, scan_fn).tick(at()) == [1, 2] and seen == ["acme/app", "acme/two"]


# ---- failure, recovery, alerts

def test_a_failed_scan_makes_the_repo_unknown_and_alerts_once():
    s = make_store(watch=1, next_run=iso(T0))
    m = Monitor(s, FakeScan(s, CLEAN, "fail", "fail"))
    m.tick(at())
    assert health(s, 1)["status"] == "healthy" and kinds(s) == []  # a healthy first scan alerts nobody
    m.tick(at(1))
    h = health(s, 1)
    assert h["status"] == "unknown" and h["failed_streak"] == 1 and "clone failed" in h["last_error"]
    assert kinds(s) == ["health_changed"]
    m.tick(at(2))  # still unknown: no second alert
    assert kinds(s) == ["health_changed"] and "the last 2 scans failed or were incomplete" in health(s, 1)["reasons"]


def test_recovery_is_alerted_once_and_the_baseline_is_kept():
    s = make_store(watch=1, next_run=iso(T0))
    m = Monitor(s, FakeScan(s, CLEAN, "fail", CLEAN, CLEAN))
    for i in range(4):
        m.tick(at(i))
    assert health(s, 1)["status"] == "healthy" and kinds(s) == ["health_changed", "health_changed"]  # into unknown, back out
    assert s.one("SELECT baseline_scan_id FROM repos")[0] == "S-001"


def test_an_incomplete_scan_is_unknown_never_green():
    from dpdp_lens.models import ScanError
    s = make_store(watch=1, next_run=iso(T0))
    bad = lambda sid: scan(sid, [], run=(), errors=[ScanError(scanner="log_scan", kind="capped", message="skipped 1 file(s) over 1 MB: big.py")])  # noqa: E731
    m = Monitor(s, FakeScan(s, CLEAN, bad, bad))
    m.tick(at())
    m.tick(at(1))
    m.tick(at(2))
    assert health(s, 1)["status"] == "unknown" and "big.py" in health(s, 1)["last_error"] and kinds(s) == ["health_changed"]


def test_blocking_findings_alert_once_then_only_when_a_new_one_appears():
    s = make_store(watch=1, next_run=iso(T0))
    other = finding(check="log_pii", fp="b" * 16, severity="high")
    m = Monitor(s, FakeScan(s, CRITICAL, CRITICAL, lambda sid: CRITICAL(sid, [other]), lambda sid: CRITICAL(sid, [other])))
    m.tick(at())
    assert kinds(s) == ["scan_delta", "health_changed"]  # first scan: new blocking finding, and the repo is at_risk now
    m.tick(at(1))
    assert kinds(s) == ["scan_delta", "health_changed"]  # unchanged scan: nothing new
    m.tick(at(2))
    assert kinds(s) == ["scan_delta", "health_changed", "scan_delta"]  # a new blocking finding, health did not change
    m.tick(at(3))
    assert len(kinds(s)) == 3
    row = s.one("SELECT * FROM outbox WHERE kind='scan_delta' ORDER BY id DESC")
    assert (row["repo_id"], row["scan_id"], row["human_id"]) == (1, "S-003", "")


def test_a_new_low_finding_does_not_alert():
    s = make_store(watch=1, next_run=iso(T0))
    Monitor(s, FakeScan(s, CLEAN, lambda sid: scan(sid, [finding(severity="low"), finding(fp="c" * 16, severity="low")]))).tick(at())
    Monitor(s, FakeScan(s, lambda sid: scan(sid, [finding(severity="low"), finding(fp="c" * 16, severity="low")]))).tick(at(1))
    assert kinds(s) == []


def test_a_suppressed_blocking_finding_raises_no_scan_delta_when_it_comes_back():
    s = make_store(watch=1, next_run=iso(T0))
    ingest_scan(s, 1, CRITICAL("S-001"), "manual", "t")
    ingest.set_status(s, "DPDP-001", "wont_fix", "accepted", "u")
    Monitor(s, FakeScan(s, CRITICAL)).tick(at())
    assert kinds(s) == ["health_changed"]  # at_risk to healthy (suppressed): one recovery alert, and no scan_delta for it
    Monitor(s, FakeScan(s, CRITICAL)).tick(at(1))
    assert kinds(s) == ["health_changed"]


def test_manual_scans_update_the_remembered_health_but_never_alert():
    s = make_store(watch=1, next_run=iso(T0 + timedelta(hours=1)))
    ingest_scan(s, 1, CRITICAL("S-001"), "bot", "U1")
    assert kinds(s) == [] and s.one("SELECT last_health FROM repos")[0] == "at_risk"
    s.run("UPDATE repos SET next_run_at=?", (iso(T0),))
    Monitor(s, FakeScan(s, CRITICAL)).tick(at())  # still at_risk: not a transition
    assert kinds(s) == []


def test_a_repo_that_went_stale_is_alerted_once_without_any_scan():
    s = make_store(watch=1, next_run=iso(T0 + timedelta(days=1)))  # far from due, and nothing runs it
    at()
    ingest_scan(s, 1, CLEAN("S-001"), "schedule", "monitor")
    m = Monitor(s, FakeScan(s))
    m.tick(at(1))
    assert health(s, 1)["status"] == "healthy" and kinds(s) == []
    m.tick(at(5))
    h = health(s, 1)
    assert h["status"] == "unknown" and h["reasons"][0].startswith("stale") and kinds(s) == ["health_changed"]
    m.tick(at(6))
    assert kinds(s) == ["health_changed"]


def test_audit_events_for_a_failed_scheduled_scan_chain_correctly():
    s = make_store(watch=1, next_run=iso(T0))
    Monitor(s, FakeScan(s, "fail")).tick(at())
    assert s.one("SELECT type, actor FROM events ORDER BY id DESC")["type"] == "scan_failed"
    assert audit.verify_chain(s)["ok"]


def test_alert_and_state_change_commit_together(monkeypatch):
    s = make_store(watch=1, next_run=iso(T0))
    monkeypatch.setattr(ingest, "_outbox", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    with pytest.raises(RuntimeError):
        ingest_scan(s, 1, CRITICAL("S-001"), "schedule", "monitor")
    assert s.one("SELECT COUNT(*) FROM scans")[0] == 0 and s.one("SELECT COUNT(*) FROM findings")[0] == 0  # nothing half-written
    assert s.one("SELECT last_health FROM repos")[0] is None


# ---- thread and start rules

def test_the_background_thread_ticks_and_stops():
    s = make_store(next_run=iso(T0))
    ran = threading.Event()
    m = Monitor(s, lambda repo, trigger: (ran.set(), "S-001")[1], clock=lambda: T0, poll=0.01)
    m.start()
    assert ran.wait(3)
    m.stop()
    assert not m._thread.is_alive()


def test_no_monitor_under_pytest_even_with_attach(monkeypatch):
    app = FastAPI()
    app.state.core = type("C", (), {"store": Store(), "scan_repo_now": staticmethod(lambda *a: None)})()
    attach_monitor(app)
    with TestClient(app):
        assert "dpdp-monitor" not in [t.name for t in threading.enumerate()]  # PYTEST_CURRENT_TEST is set


def test_monitor_starts_with_the_server_and_stops_with_it_unless_switched_off(monkeypatch):
    def run_app():
        app = FastAPI()
        app.state.core = type("C", (), {"store": Store(), "scan_repo_now": staticmethod(lambda *a: None)})()
        attach_monitor(app)
        with TestClient(app):
            running = "dpdp-monitor" in [t.name for t in threading.enumerate()]
        time.sleep(0.05)
        return running, "dpdp-monitor" in [t.name for t in threading.enumerate()]

    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.delenv("DPDP_MONITOR", raising=False)
    assert run_app() == (True, False)  # on by default, stopped at shutdown
    monkeypatch.setenv("DPDP_MONITOR", "0")
    assert run_app() == (False, False)


def test_the_real_module_app_and_create_app_with_a_store_start_nothing():
    from dpdp_lens.api import app, create_app
    with TestClient(app), TestClient(create_app(store=Store())):
        assert "dpdp-monitor" not in [t.name for t in threading.enumerate()]


# ---- schema migration

def test_a_version_1_database_is_migrated_and_keeps_its_data(tmp_path):
    path = tmp_path / "old.db"
    s = make_store(path)
    s.run("INSERT INTO outbox(kind, human_id, created_at) VALUES ('status_changed', 'DPDP-001', 'x')")
    s.run("ALTER TABLE repos DROP COLUMN last_health")
    s.run("ALTER TABLE outbox DROP COLUMN repo_id")
    s.run("ALTER TABLE outbox DROP COLUMN scan_id")
    s.run("ALTER TABLE repos DROP COLUMN installation_id")  # the objects of version 3: a real version 1 file has neither
    s.run("DROP TABLE installations")
    s.run("ALTER TABLE findings DROP COLUMN pr_url")  # the object of version 4
    s.run("PRAGMA user_version=1")
    s.close()
    new = Store(path)
    assert new.one("PRAGMA user_version")[0] == SCHEMA_VERSION == 4
    assert new.one("SELECT human_id, repo_id, scan_id FROM outbox")[:] == ("DPDP-001", None, "")
    assert new.one("SELECT full_name, last_health FROM repos")[:] == ("acme/app", None)
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 4
