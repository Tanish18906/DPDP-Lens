"""/dpdp findings as interactive rows, and what the row buttons do. Plain values in, no Bolt objects, so tests call these directly.

The list is ephemeral to the requester, sorted critical first, and paged in several messages of at most 50 blocks, so nothing is
dropped. Each row has View Details, Change Status and (for an approver, a repo in DPDP_FIX_REPOS and a finding with a fix) Fix and verify.
Slack lets a response_url replace a whole message only, so every page is kept in memory (flow.Pages) and rebuilt on a click: that is how
"the row updates in place". The status itself and the fix result always come from the engine, never from here."""
import json
import logging

from . import cards
from .actions import _gate
from .api import EngineError
from .redact import redact

log = logging.getLogger("dpdp_lens.slackbot")
OUT_OF_DATE = "This list is out of date (the bot restarted or the page is old). Run /dpdp findings again."


def all_records(ctx, repo_id: int, status: str | None) -> list[dict]:
    out, total = [], None
    while total is None or len(out) < total:
        page = ctx.engine.findings(repo_id, status, 500, len(out))
        total = page["total"]
        out += page["items"]
        if not page["items"]:
            break
    return out


def records(ctx, repo_id: int, mode: str) -> list[dict]:
    if mode == "all":
        return all_records(ctx, repo_id, None)
    return [r for s in ("open", "in_progress") for r in all_records(ctx, repo_id, s)]  # suppressed and fixed are not "open"


def fix_button(ctx, user: str, rec: dict) -> bool:
    return bool(ctx.is_approver(user) and ctx.can_fix(rec["repo"]) and rec.get("fix_available") and rec["status"] != "fixed")


def pr_button(ctx, user: str, rec: dict) -> bool:
    """Open pull request: only for an approver, and only when the engine says one is allowed (switch on, fix repo, GitHub App, verified fix)."""
    return bool(ctx.is_approver(user) and rec.get("pr_available") and not rec.get("pr_url"))


def build_pages(ctx, user: str, channel: str, repo: str, recs: list[dict], mode: str, health: dict) -> list[dict]:
    """Page specs of at most 50 blocks each. A page is {user, channel, units, recs}; a unit is ("raw", [blocks]) or ("row", human_id)."""
    order = lambda r: (cards.SEVERITY_ORDER.get(r["severity"], 9), r["human_id"])  # noqa: E731
    units = [("raw", [cards._section("\n".join(cards.findings_header(repo, len(recs), mode, health)))])]
    if mode == "all":
        for status in cards.LIST_ORDER:
            group = sorted((r for r in recs if r["status"] == status), key=order)
            if group:
                units.append(("raw", [cards._section(cards.group_heading(status, len(group)))]))
                units += [("row", r["human_id"]) for r in group]
    else:
        units += [("row", r["human_id"]) for r in sorted(recs, key=order)]
    by_id = {r["human_id"]: r for r in recs}
    pages, current, used = [], [], 0
    for kind, payload in units:
        size = len(payload) if kind == "raw" else 3
        if used + size > cards.MAX_BLOCKS - 1 and current:  # one block is kept for the "Page i of N" line
            pages.append(current)
            current, used = [], 0
        current.append((kind, payload))
        used += size
    pages.append(current)
    out = []
    for i, page_units in enumerate(pages, 1):
        if len(pages) > 1:
            page_units = [("raw", [{"type": "context", "elements": [{"type": "mrkdwn", "text": f"Page {i} of {len(pages)} · {cards.esc(repo)}"}]}]), *page_units]
        out.append({"user": user, "channel": channel, "repo": repo, "n": i, "of": len(pages), "units": page_units,
                    "recs": {p: by_id[p] for k, p in page_units if k == "row"}})
    return out


def render(ctx, pid: str, page: dict) -> tuple[str, list]:
    blocks = []
    for kind, payload in page["units"]:
        blocks += payload if kind == "raw" else cards.finding_row(page["recs"][payload], pid, fix_button(ctx, page["user"], page["recs"][payload]),
                                                                  pr_button(ctx, page["user"], page["recs"][payload]))
    assert len(blocks) <= cards.MAX_BLOCKS
    return f"{page['repo']}: {len(page['recs'])} findings on this page ({page['n']} of {page['of']})", blocks


def send_list(ctx, user: str, channel: str, repo: str, recs: list[dict], mode: str, health: dict, reply) -> None:
    """The first page goes back as the command's answer, the others as further ephemeral messages (a response_url allows only 5 answers)."""
    for i, page in enumerate(build_pages(ctx, user, channel, repo, recs, mode, health)):
        pid = ctx.pages.add(page)
        text, blocks = render(ctx, pid, page)
        if i == 0:
            reply(text, blocks)
        else:
            ctx.poster.ephemeral(channel, user, text, blocks)


# ---- what the buttons do

def update_row(ctx, pid: str, url: str, rec: dict) -> None:
    """The engine's new record of one finding: put it in its page, replace that page, and update the finding's public card if it has one."""
    page = ctx.pages.get(pid) if pid else None
    if page is not None and rec["human_id"] in page["recs"]:
        page["recs"][rec["human_id"]] = rec
        ctx.poster.respond(url, *render(ctx, pid, page), replace=True)
    elif pid:
        ctx.poster.respond(url, OUT_OF_DATE)
    try:
        ctx.refresh_card(rec["human_id"], rec)
    except EngineError as e:
        log.warning("card of %s not refreshed: %s", rec["human_id"], redact(e.detail))


def _reset(ctx, pid: str, url: str) -> None:
    """Put the page back as it really is (a refused change leaves the select showing the choice)."""
    page = ctx.pages.get(pid)
    if page is not None:
        ctx.poster.respond(url, *render(ctx, pid, page), replace=True)


def row_details(ctx, user: str, channel: str, hid: str, url: str) -> None:
    if not _gate(ctx, user, channel, approver=False):
        return
    try:
        rec = ctx.engine.finding(hid)
    except EngineError as e:
        return ctx.poster.respond(url, f"Could not load {hid}: {e.detail}")
    ctx.poster.respond(url, *cards.details(rec, ctx.cfg.dashboard_url, fix_button(ctx, user, rec), pr_button(ctx, user, rec)))


def row_status(ctx, user: str, channel: str, pid: str, value: str, trigger_id: str, open_view, url: str) -> None:
    """`value` is "DPDP-014|false_positive". False Positive and Won't Fix first ask for a reason in the same modal as the cards."""
    hid, _, status = value.partition("|")
    if not _gate(ctx, user, channel):
        return _reset(ctx, pid, url)
    if status in ("false_positive", "wont_fix"):
        open_view(trigger_id=trigger_id, view=cards.reason_modal(hid, status, json.dumps({"h": hid, "s": status, "c": channel, "p": pid, "u": url})))
        return
    try:
        rec = ctx.engine.set_status(hid, status, "", user)
    except EngineError as e:
        ctx.poster.respond(url, f"Could not change {hid}: {e.detail}")
        return _reset(ctx, pid, url)
    update_row(ctx, pid, url, rec)


def row_fix(ctx, user: str, channel: str, pid: str, hid: str, url: str) -> None:
    """Fix and verify from a row (pid is its page) or from a details message (pid empty). Approvers only. The answer is the engine's:
    VERIFIED only when it returned verified true, a cached replay is labelled, and the diff is shown in whole lines."""
    if not _gate(ctx, user, channel):
        return
    ctx.poster.respond(url, f"Fixing {hid} in a sandbox copy, up to 90 seconds. The repo itself is not changed.")
    try:
        out = ctx.engine.fix(hid, user)
    except EngineError as e:
        return ctx.poster.respond(url, f"Not verified. The fix did not run: {e.detail}")
    lines, verified = cards.fix_summary(hid, out)
    fix = out["finding"]["fix"]
    rec = out.get("record")
    if rec:
        lines.append(f"Status is now *{cards.STATUS.get(rec['status'], rec['status'])}*.")
    lines += cards.fix_scope_lines(fix, verified)
    blocks = [cards._section("\n".join(lines))]
    if fix.get("diff"):
        blocks += cards.diff_reply(hid, fix["diff"])[1]
    if verified and out.get("mode") != "cached_golden" and rec and pr_button(ctx, user, rec):  # a pull request only for a live verified fix
        blocks.append({"type": "actions", "block_id": f"pr:{hid}", "elements": [cards.pr_button(hid)]})
    ctx.poster.respond(url, lines[0], blocks)
    if rec is None:
        return
    if pid:
        update_row(ctx, pid, url, rec)
    else:  # from a details message: show it again with the fix result in it, and update the card
        try:
            ctx.poster.respond(url, *cards.details(ctx.engine.finding(hid), ctx.cfg.dashboard_url, False), replace=True)
            ctx.refresh_card(hid, rec)
        except EngineError as e:
            log.warning("details of %s not refreshed: %s", hid, redact(e.detail))


def row_pr(ctx, user: str, channel: str, pid: str, hid: str, url: str) -> None:
    """Open pull request, from a row, a fix result or a details message. Approvers only. The engine decides (switch, fix repo, GitHub App,
    verified live fix) and answers with the link, or with a plain reason that is shown as it is."""
    if not _gate(ctx, user, channel):
        return
    ctx.poster.respond(url, f"Opening a pull request for {hid}: a branch is pushed and a pull request opened. Nothing is merged.")
    try:
        out = ctx.engine.open_pr(hid, user)
    except EngineError as e:
        return ctx.poster.respond(url, f":x: The pull request for {hid} was not created: {e.detail}")
    ctx.poster.respond(url, *cards.pr_result(hid, out))
    rec = out.get("record")
    if rec and pid:
        update_row(ctx, pid, url, rec)
    elif rec:
        try:
            ctx.refresh_card(hid, rec)
        except EngineError as e:
            log.warning("card of %s not refreshed: %s", hid, redact(e.detail))
