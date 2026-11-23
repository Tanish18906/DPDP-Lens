"""Button, select and modal handlers. Each takes plain values (no Bolt objects), so tests call them directly.
Only approvers may change a status or run a fix. Anyone in an allowed channel may read details."""
import json
import logging

from . import cards, flow
from .api import EngineError
from .redact import redact

log = logging.getLogger("dpdp_lens.slackbot")
NOT_ALLOWED = "Not allowed: only approvers can do this."


def _gate(ctx, user: str, channel: str, approver: bool = True) -> bool:
    if channel not in ctx.cfg.allowed_channels:
        return False
    if approver and not ctx.is_approver(user):
        ctx.poster.ephemeral(channel, user, NOT_ALLOWED)
        return False
    return True


def connect_picked(ctx, user: str, channel: str, value: str, reply) -> None:
    """The Connect button of the repo picker. `value` is "<installation id>|owner/repo" from the select, or empty when nothing was picked.
    The engine decides again whether the installation really shares the repo."""
    if not _gate(ctx, user, channel):
        return
    iid, _, name = value.partition("|")
    if not iid.isdigit() or not name:
        return reply("Pick a repository first.")
    reply(f"Connecting {name}...")
    try:
        flow.connect_and_scan(ctx, name, "", user, channel, int(iid))
    except EngineError as e:
        reply(f"The engine said: {e.detail}" if e.status else f"Could not reach the engine: {e.detail}")


def view_details(ctx, user: str, channel: str, ts: str, hid: str) -> None:
    if not _gate(ctx, user, channel, approver=False):
        return
    try:
        text, blocks = cards.details(ctx.engine.finding(hid), ctx.cfg.dashboard_url)
    except EngineError as e:
        text, blocks = f"Could not load {hid}: {e.detail}", None
    ctx.poster.post(channel, text, blocks, thread_ts=ts)


def change_status(ctx, user: str, channel: str, ts: str, value: str, trigger_id: str, open_view) -> None:
    """`value` is "DPDP-014|false_positive" from the select. False Positive and Won't Fix first ask for a reason in a modal."""
    hid, _, status = value.partition("|")
    if not _gate(ctx, user, channel):
        try:
            ctx.refresh_card(hid)  # put the select back to the real status
        except EngineError:
            pass
        return
    if status in ("false_positive", "wont_fix"):
        open_view(trigger_id=trigger_id, view=cards.reason_modal(hid, status, json.dumps({"h": hid, "s": status, "c": channel, "t": ts})))
        return
    try:
        ctx.engine.set_status(hid, status, "", user)
        ctx.refresh_card(hid)
    except EngineError as e:
        ctx.poster.ephemeral(channel, user, f"Could not change {hid}: {e.detail}")


def submit_reason(ctx, user: str, meta: str, reason: str) -> str | None:
    """Modal submit. Returns an error text for the modal, or None when the status was saved."""
    m = json.loads(meta)
    reason = (reason or "").strip()
    if not _gate(ctx, user, m["c"]):
        return NOT_ALLOWED
    if not 1 <= len(reason) <= 300:
        return "Give a reason of 1 to 300 characters."
    try:
        rec = ctx.engine.set_status(m["h"], m["s"], reason, user)
    except EngineError as e:
        return e.detail  # for example: the reason must not contain personal data
    if m.get("u"):  # the modal was opened from a row of /dpdp findings: update that row and the card
        from .rows import update_row  # late import: rows.py imports this module
        update_row(ctx, m.get("p", ""), m["u"], rec)
        return None
    try:
        ctx.refresh_card(m["h"])
    except EngineError as e:
        log.warning("card of %s not refreshed: %s", m["h"], redact(e.detail))
    return None


def fix_and_verify(ctx, user: str, channel: str, ts: str, hid: str) -> None:
    if not _gate(ctx, user, channel):
        return
    post = lambda text, blocks=None: ctx.poster.post(channel, text, blocks, thread_ts=ts)  # noqa: E731
    post(f"Fixing {hid} in a sandbox copy. The repo itself is not changed.")
    try:
        out = ctx.engine.fix(hid, user)
    except EngineError as e:
        return post(f"Not verified. The fix did not run: {e.detail}")
    fix = out["finding"]["fix"]
    if fix.get("verified") is True and out["finding"]["status"] == "verified_fixed":  # the engine's computed answer, nothing else
        how = "Cached verified patch (replay)" if out["mode"] == "cached_golden" else "VERIFIED by a live sandbox run"
        if out.get("fallback_reason"):
            how += f" (the live run could not start: {out['fallback_reason']})"
        lines = [f":white_check_mark: *{hid}: {how}*"]
    else:
        lines = [f":x: *{hid}: Not verified*"]
    lines.append(f"Re-scan of the fixed copy: {_yn(fix.get('rescan_passed'))} · App tests: {_yn(fix.get('tests_passed'))}")
    if fix.get("score_before") is not None and fix.get("score_after") is not None:
        lines.append(f"Score {fix['score_before']} to {fix['score_after']}")
    post("\n".join(lines), [cards._section("\n".join(lines))])
    if fix.get("diff"):
        post(*cards.diff_reply(hid, fix["diff"]))
    try:
        ctx.refresh_card(hid, out.get("record"))
    except EngineError as e:
        log.warning("card of %s not refreshed: %s", hid, redact(e.detail))


def _yn(v) -> str:
    return "passed" if v is True else "failed" if v is False else "not run"
