"""What happens after a scan: wait for it, post the summary, post one card per new finding, keep cards in step with the engine."""
import logging
import time

from . import cards
from .api import EngineError
from .redact import add_secret, redact

log = logging.getLogger("dpdp_lens.slackbot")
SCAN_WAIT = 300  # seconds to wait for a clone and scan before telling the channel that it timed out


class Ctx:
    """Everything a handler needs. `slack` is a Slack WebClient (or a fake in tests)."""

    def __init__(self, cfg, engine, slack, poster, sleep=time.sleep):
        self.cfg, self.engine, self.slack, self.poster, self.sleep = cfg, engine, slack, poster, sleep
        self.alerted: set[int] = set()  # repo ids whose health alert is out and not yet followed by a recovery (memory only)
        for secret in (cfg.api_token, cfg.bot_token, cfg.app_token):
            add_secret(secret)

    def is_approver(self, user: str) -> bool:
        return user in self.cfg.approvers

    def can_fix(self, repo: str) -> bool:
        return repo.lower() in self.cfg.fix_repos

    def card(self, rec: dict) -> tuple[str, list]:
        return cards.finding_card(rec, self.cfg.dashboard_url, self.can_fix(rec["repo"]))

    def refresh_card(self, hid: str, rec: dict | None = None) -> None:
        """Edit the finding's card in place from the engine's current record. Does nothing when it never had a card."""
        rec = rec or self.engine.finding(hid)
        if rec.get("slack"):
            text, blocks = self.card(rec)
            self.poster.update(rec["slack"]["channel"], rec["slack"]["ts"], text, blocks)


def wait_for_delta(ctx: Ctx, scan_id: str, timeout: float = SCAN_WAIT, poll: float = 2.0) -> dict:
    """The delta appears once the scan is cloned, scanned and stored. A scan the engine lost answers 500 on /scan/{id}."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return ctx.engine.delta(scan_id)
        except EngineError as e:
            if e.status != 404:
                raise
        ctx.engine.scan_result(scan_id)  # raises EngineError(500, ...) when the scan failed before it was stored
        if time.monotonic() >= deadline:
            raise EngineError(0, f"scan {scan_id} did not finish in {int(timeout)} seconds")
        ctx.sleep(poll)


def scan_errors(ctx: Ctx, scan_id: str) -> tuple[list[str], bool]:
    """(why a scan was incomplete, whether it failed outright). A scan that failed outright has no result: /scan/{id} answers with its error."""
    try:
        scan = ctx.engine.scan_result(scan_id)
    except EngineError as e:
        return [e.detail], True
    return [f"{e['scanner']} {e['kind']}: {e['message']}" for e in scan.get("scan_errors", [])], False


def post_cards(ctx: Ctx, channel: str, human_ids: list[str]) -> int:
    """One card per finding, once. A finding that already has a card (the engine remembers its Slack ts) is skipped."""
    recs = [r for r in (ctx.engine.finding(h) for h in human_ids) if not r.get("slack")]
    recs.sort(key=lambda r: (cards.SEVERITY_ORDER.get(r["severity"], 9), r["human_id"]))
    for rec in recs:
        text, blocks = ctx.card(rec)
        ts = ctx.poster.post(channel, text, blocks)
        try:
            ctx.engine.link(rec["human_id"], channel, ts)
        except EngineError as e:
            log.warning("could not store the Slack link of %s: %s", rec["human_id"], redact(e.detail))
    return len(recs)


def post_report(ctx: Ctx, channel: str, repo: str, delta: dict) -> None:
    errors, lost = ([], False) if delta["complete"] else scan_errors(ctx, delta["scan_id"])
    if lost:
        ctx.poster.post(channel, *cards.failed(repo, delta["scan_id"], errors[0]))
        return
    ctx.poster.post(channel, *cards.summary(repo, delta, errors))
    post_cards(ctx, channel, delta["new"] + delta["reopened"])


def connect_and_scan(ctx: Ctx, full_name: str, branch: str, user: str, channel: str, installation_id: int | None = None) -> None:
    """Connect the repo (the engine checks the allowlist or the installation), start a static scan, follow it into the channel."""
    repo = ctx.engine.connect(full_name, branch, channel, user, installation_id)
    scan_id = ctx.engine.scan(repo["id"], user)["scan_id"]
    ctx.poster.post(channel, f"Scanning {full_name} (static checks only)")
    follow_scan(ctx, repo, scan_id, channel)


def follow_scan(ctx: Ctx, repo: dict, scan_id: str, channel: str) -> None:
    try:
        delta = wait_for_delta(ctx, scan_id)
    except EngineError as e:
        text, blocks = cards.failed(repo["full_name"], scan_id, e.detail)
        ctx.poster.post(channel, text, blocks)
        return
    post_report(ctx, channel, repo["full_name"], delta)
