"""The /dpdp command. `run_command` is what the Bolt listener calls (after it has acked) and what the tests call.
`reply(text, blocks=None)` sends an ephemeral answer to the person who typed the command."""
import logging

from . import cards, flow
from .api import EngineError
from .redact import redact

log = logging.getLogger("dpdp_lens.slackbot")
HELP = ("*DPDP Lens* (readiness checks, not a compliance certificate)\n"
        "• `/dpdp connect owner/repo [branch]`: connect a repo and run a static scan\n"
        "• `/dpdp connect`: connect through the GitHub App: install it, then pick a repository (approvers)\n"
        "• `/dpdp repos`: repositories shared with the GitHub App, and which are connected (approvers)\n"
        "• `/dpdp scan [owner/repo]`: scan again\n"
        "• `/dpdp findings [open|all]`: the findings of this channel's repo, critical first (default open; all adds fixed and suppressed)\n"
        "• `/dpdp status`: health, last complete scan, counts\n"
        "• `/dpdp diff`: the latest scan against the baseline: new, resolved, persistent\n"
        "• `/dpdp baseline`: use the latest complete scan as the baseline (approvers)\n"
        "• `/dpdp watch <minutes>|off`: scheduled re-scan (approvers)")


def _pick_repo(ctx, args: list[str], channel: str) -> dict:
    repos = ctx.engine.repos()
    if args and "/" in args[0]:
        for r in repos:
            if r["full_name"].lower() == args[0].lower():
                return r
        raise EngineError(404, f"{args[0]} is not connected. Use /dpdp connect {args[0]}")
    here = [r for r in repos if r["slack_channel"] == channel] or (repos if len(repos) == 1 else [])
    if len(here) == 1:
        return here[0]
    raise EngineError(422, "Say which repo: " + (", ".join(r["full_name"] for r in repos) or "none is connected yet, use /dpdp connect owner/repo"))


def _need_approver(ctx, user: str, reply) -> bool:
    if ctx.is_approver(user):
        return True
    reply("Not allowed: only approvers can do this.")
    return False


def _shared_repos(ctx, reply):
    """Every repo the app's installations share, with connected status. None (after telling the user why) when there is nothing to list."""
    try:
        installs = ctx.engine.github_installations()
    except EngineError as e:
        if e.status != 503:
            raise
        reply("The GitHub App is not set up on the engine. Use `/dpdp connect owner/repo` for an allowlisted repo.")
        return None
    if not installs:
        text, blocks = cards.github_link(ctx.cfg.engine_url + "/github/connect")
        reply(text, blocks)
        return None
    return [{**r, "installation_id": i["installation_id"]} for i in installs for r in ctx.engine.github_repos(i["installation_id"])]


def _connect(ctx, args, user, channel, reply):
    if not args:  # no argument: the GitHub App flow. It lists private repo names, so approvers only.
        if not _need_approver(ctx, user, reply):
            return
        repos = _shared_repos(ctx, reply)
        if repos is None:
            return
        if not repos:
            return reply("The GitHub App is installed but shares no repository. Change its repository access on GitHub, then try again.")
        return reply(*cards.repo_picker(repos))
    flow.connect_and_scan(ctx, args[0], args[1] if len(args) > 1 else "", user, channel)


def _repos(ctx, args, user, channel, reply):
    if not _need_approver(ctx, user, reply):
        return
    repos = _shared_repos(ctx, reply)
    if repos is not None:
        reply(cards.repo_list(repos) if repos else "The GitHub App is installed but shares no repository.")


def _scan(ctx, args, user, channel, reply):
    repo = _pick_repo(ctx, args, channel)
    scan_id = ctx.engine.scan(repo["id"], user)["scan_id"]
    ctx.poster.post(channel, f"Scanning {repo['full_name']} (static checks only)")
    flow.follow_scan(ctx, repo, scan_id, channel)


def _status(ctx, args, user, channel, reply):
    repo = _pick_repo(ctx, args, channel)
    h = ctx.engine.health(repo["id"])
    emoji, label = cards.HEALTH.get(h["status"], cards.HEALTH["unknown"])
    c = h["counts"]
    lines = [f"*{cards.esc(repo['full_name'])}* :{emoji}: Health: *{label}*",
             f"Last complete scan: {h['last_complete_scan_at'] or 'none'} · latest scan: {h['last_scan_status'] or 'none'}",
             " · ".join(f"{cards.STATUS[s]} {c.get(s, 0)}" for s in cards.STATUS)]
    lines += [f"• {cards.esc(r)}" for r in h["reasons"]]
    reply("\n".join(lines))


def _all_records(ctx, repo_id: int, status: str | None) -> list[dict]:
    out, total = [], None
    while total is None or len(out) < total:
        page = ctx.engine.findings(repo_id, status, 500, len(out))
        total = page["total"]
        out += page["items"]
        if not page["items"]:
            break
    return out


def _findings(ctx, args, user, channel, reply):
    modes = [a.lower() for a in args if a.lower() in ("open", "all")]
    if len(modes) > 1 or any(a.lower() not in ("open", "all") and "/" not in a for a in args):
        return reply("Usage: `/dpdp findings [open|all] [owner/repo]`")
    mode = modes[0] if modes else "open"
    repo = _pick_repo(ctx, [a for a in args if "/" in a], channel)
    recs = _all_records(ctx, repo["id"], None) if mode == "all" else \
        [r for s in ("open", "in_progress") for r in _all_records(ctx, repo["id"], s)]  # suppressed and fixed are not "open"
    reply(*cards.findings_list(repo["full_name"], recs, mode, ctx.engine.health(repo["id"]), ctx.cfg.dashboard_url))


def _diff(ctx, args, user, channel, reply):
    repo = _pick_repo(ctx, args, channel)
    d = ctx.engine.diff(repo["id"])  # 404 with a clear text when the repo has no baseline: shown as the engine's answer
    reply(*cards.diff(repo["full_name"], d, ctx.cfg.dashboard_url, [] if d["complete"] else flow.scan_errors(ctx, d["scan_id"])[0]))


def _baseline(ctx, args, user, channel, reply):
    if not _need_approver(ctx, user, reply):
        return
    repo = _pick_repo(ctx, args, channel)
    reply(f"Baseline of {repo['full_name']} is now {ctx.engine.baseline(repo['id'], user)['baseline_scan_id']}.")


def _watch(ctx, args, user, channel, reply):
    if not _need_approver(ctx, user, reply):
        return
    value = args[0].lower() if args else ""
    if value != "off" and not value.isdigit():
        return reply("Usage: `/dpdp watch <minutes>` or `/dpdp watch off`")
    repo = _pick_repo(ctx, args[1:], channel)
    out = ctx.engine.watch(repo["id"], None if value == "off" else int(value), user)
    reply(f"Scheduled scans of {repo['full_name']}: " + (f"every {out['watch_minutes']} minutes (a schedule, not real-time)" if out["watch_minutes"] else "off"))


COMMANDS = {"connect": _connect, "repos": _repos, "scan": _scan, "status": _status, "findings": _findings, "diff": _diff, "baseline": _baseline, "watch": _watch}


def run_command(ctx, text: str, user: str, channel: str, reply) -> None:
    if channel not in ctx.cfg.allowed_channels:
        return reply("DPDP Lens does not take commands in this channel.")
    parts = (text or "").split()
    sub = parts[0].lower() if parts else "help"
    handler = COMMANDS.get(sub)
    if handler is None:
        return reply(HELP)
    try:
        handler(ctx, parts[1:], user, channel, reply)
    except EngineError as e:
        reply(f"The engine said: {e.detail}" if e.status else f"Could not reach the engine: {e.detail}")
    except Exception as e:  # never leave a command without an answer, and never show a token
        log.warning("command %s failed: %s: %s", sub, type(e).__name__, redact(e))
        reply(f"Something went wrong ({type(e).__name__}). Details are in the bot log.")
