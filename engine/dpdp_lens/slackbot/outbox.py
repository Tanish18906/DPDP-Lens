"""Engine to Slack sync. Polls GET /outbox every 2 seconds. A kind the bot does not know is skipped, so a newer engine never breaks it.
Starts at the end of the outbox: what happened while the bot was down is not replayed (cards are rebuilt on the next change)."""
import logging
import threading

from . import cards, flow
from .redact import redact

log = logging.getLogger("dpdp_lens.slackbot")


class Poller:
    def __init__(self, ctx, interval: float = 2.0):
        self.ctx, self.interval, self.cursor = ctx, interval, None
        self.handlers = {"status_changed": self._status_changed, "scan_delta": self._scan_delta, "health_changed": self._health_changed}

    def _repo(self, repo_id) -> dict | None:
        return next((r for r in self.ctx.engine.repos() if r["id"] == repo_id), None)

    def _status_changed(self, row) -> None:
        self.ctx.refresh_card(row["human_id"])

    def _scan_delta(self, row) -> None:
        """A scheduled scan found new blocking findings: summary plus cards, in the repo's channel."""
        repo = self._repo(row["repo_id"])
        if repo is None:
            return
        flow.post_report(self.ctx, repo["slack_channel"] or self.ctx.cfg.channel, repo["full_name"], self.ctx.engine.delta(row["scan_id"]))

    def _health_changed(self, row) -> None:
        """One alert when health turns at_risk or unknown, and nothing more until it has recovered."""
        repo = self._repo(row["repo_id"])
        if repo is None:
            return
        channel, health = repo["slack_channel"] or self.ctx.cfg.channel, self.ctx.engine.health(row["repo_id"])
        if health["status"] in ("at_risk", "unknown"):
            if row["repo_id"] not in self.ctx.alerted:
                self.ctx.alerted.add(row["repo_id"])
                self.ctx.poster.post(channel, *cards.alert(repo["full_name"], health))
        elif row["repo_id"] in self.ctx.alerted:
            self.ctx.alerted.discard(row["repo_id"])
            self.ctx.poster.post(channel, *cards.recovery(repo["full_name"], health))

    def poll_once(self) -> int:
        """Handle every new row. Returns how many it handled. A row that fails is logged and skipped, never retried forever."""
        if self.cursor is None:  # first poll: remember where the outbox ends (the route returns at most 500 rows per call)
            self.cursor = 0
            while rows := self.ctx.engine.outbox(self.cursor):
                self.cursor = rows[-1]["id"]
            return 0
        rows = self.ctx.engine.outbox(self.cursor)
        done = 0
        for row in rows:
            self.cursor = row["id"]
            handler = self.handlers.get(row.get("kind"))
            if handler is None:
                continue
            try:
                handler(row)
                done += 1
            except Exception as e:
                log.warning("outbox row %s (%s) failed: %s: %s", row["id"], row.get("kind"), type(e).__name__, redact(e))
        return done

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.poll_once()
            except Exception as e:  # engine down or restarting: try again at the next tick
                log.warning("outbox poll failed: %s: %s", type(e).__name__, redact(e))
            stop.wait(self.interval)
