"""Scheduled monitoring: re-scan a connected repo every N minutes (block 05). It is a schedule, not real-time and not
continuous: between two scans nothing is watched.

`Monitor.tick(now)` does one pass and is what the tests call. `start()` runs it in a background thread. The clock and the
scan function are injected, so tests need neither real time nor a network. Rules:
- A repo is due when watch_minutes is set and next_run_at <= now. A window missed while the engine was down runs once.
- next_run_at lives in SQLite, so a restart keeps the schedule.
- One scan at a time overall (the monitor is one thread, and api_v2 holds a global scan slot), and none for a repo that
  already has one running.
- A failed or incomplete scan is stored by the scan function (health becomes unknown). Stale repos, with no complete scan in
  twice the interval, are found here and alerted once.
"""
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from . import ingest
from .store import Store

log = logging.getLogger("dpdp_lens")
POLL_SECONDS = 10


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


class Monitor:
    def __init__(self, store: Store, scan_fn, clock=lambda: datetime.now(timezone.utc), poll: float = POLL_SECONDS):
        """scan_fn(repo_row, "schedule") runs one scan to the end and returns its id, or None if the repo is busy."""
        self.store, self.scan_fn, self.clock, self.poll = store, scan_fn, clock, poll
        self._stop, self._thread = threading.Event(), None

    def tick(self, now: datetime | None = None) -> list[int]:
        """One pass. Returns the ids of the repos it started a scan for."""
        now = now or self.clock()
        started = []
        watched = self.store.all("SELECT * FROM repos WHERE watch_minutes IS NOT NULL ORDER BY COALESCE(next_run_at, ''), id")
        for repo in watched:
            if repo["next_run_at"] and _parse(repo["next_run_at"]) > now:
                continue
            try:
                scan_id = self.scan_fn(repo, "schedule")
            except Exception as e:  # the scan function stores its own failures: this is a bug or a broken store
                log.warning("monitor: scan of %s raised %s: %s", repo["full_name"], type(e).__name__, e)
                scan_id = "error"
            if scan_id is None:
                continue  # busy: try again at the next tick, the schedule is not moved
            # From now, not from the old next_run_at: a missed window runs once, never as a burst.
            due = (now + timedelta(minutes=repo["watch_minutes"])).isoformat(timespec="seconds")
            self.store.run("UPDATE repos SET next_run_at=? WHERE id=? AND watch_minutes IS NOT NULL", (due, repo["id"]))
            started.append(repo["id"])
        for repo in self.store.all("SELECT id FROM repos WHERE watch_minutes IS NOT NULL AND EXISTS (SELECT 1 FROM scans WHERE repo_id=repos.id)"):
            try:
                ingest.sync_health(self.store, repo["id"], emit=True, now=now)  # catches a repo that went stale without any scan
            except Exception as e:
                log.warning("monitor: health check of repo %s failed: %s: %s", repo["id"], type(e).__name__, e)
        return started

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="dpdp-monitor", daemon=True)
            self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:  # the thread must survive anything
                log.warning("monitor: tick failed: %s: %s", type(e).__name__, e)
            self._stop.wait(self.poll)

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


def enabled() -> bool:
    """On unless DPDP_MONITOR=0. Never under pytest."""
    return os.environ.get("DPDP_MONITOR") != "0" and "PYTEST_CURRENT_TEST" not in os.environ


def attach_monitor(app) -> None:
    """Start a Monitor when the server starts and stop it when the server stops. Only api.py's own module app calls this,
    so an app built by create_app(store=...) in a test never has a monitor."""
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a):
        monitor = None
        if enabled() and getattr(a.state.core, "store", None) is not None:
            monitor = Monitor(a.state.core.store, a.state.core.scan_repo_now)
            monitor.start()
        try:
            async with inner(a) as state:
                yield state
        finally:
            if monitor is not None:
                monitor.stop()

    app.router.lifespan_context = lifespan
