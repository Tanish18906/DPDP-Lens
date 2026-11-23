"""Block Kit builders. Pure functions: a dict from the engine in, (text, blocks) out. Nothing here talks to Slack or the engine.
Only masked evidence ever reaches these functions, and no function adds anything raw."""
SEVERITY = {"critical": (":red_circle:", "CRITICAL"), "high": (":large_orange_circle:", "HIGH"),
            "medium": (":large_yellow_circle:", "MEDIUM"), "low": (":large_blue_circle:", "LOW")}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
STATUS = {"open": "Open", "in_progress": "In Progress", "fixed": "Fixed", "false_positive": "False Positive", "wont_fix": "Won't Fix"}
SELECTABLE = ("open", "in_progress", "false_positive", "wont_fix")  # Fixed is set by a scan or a verified fix, never by hand
PROOF = {"probed": "Behaviour confirmed by a live request", "observed": "Observed in scan", "static": "Static check"}
HEALTH = {"healthy": ("white_check_mark", "Healthy"), "changed": ("large_yellow_circle", "Changed"),
          "at_risk": ("rotating_light", "At risk"), "unknown": ("grey_question", "Unknown")}


def esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def cut(s, n: int) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": cut(text, 2900)}}


def _opt(hid: str, status: str) -> dict:
    return {"text": {"type": "plain_text", "text": STATUS[status]}, "value": f"{hid}|{status}"}


def _where(loc: dict) -> str:
    if loc.get("file"):
        return f"{loc['file']}:{loc['line']}" if loc.get("line") else loc["file"]
    return loc.get("url") or "no location"


def finding_card(rec: dict, dashboard_url: str, can_fix: bool) -> tuple[str, list]:
    """The one card per finding. `rec` is a FindingRecord. Rebuilt from the record every time, so an edit can never show a stale status."""
    hid, sev = rec["human_id"], rec["severity"]
    emoji, label = SEVERITY.get(sev, (":white_circle:", str(sev).upper()))
    status = STATUS.get(rec["status"], rec["status"])
    head = f"<{dashboard_url.rstrip('/')}/?finding={hid}|{hid}>   {emoji} *{label}*   ·   Status: *{status}*"
    context = [f"`{esc(_where(rec['location']))}`", f"{esc(rec['repo'])}@{esc(rec['branch'] or 'default branch')}",
               PROOF.get(rec["proof"], "Static check")]
    if rec["status"] != "open" and rec.get("status_reason"):
        context.append(f"Reason: {esc(cut(rec['status_reason'], 120))}")
    actions = [{"type": "button", "text": {"type": "plain_text", "text": "View Details"}, "action_id": "dpdp_details", "value": hid},
               {"type": "static_select", "action_id": "dpdp_status", "placeholder": {"type": "plain_text", "text": "Change Status"},
                "options": [_opt(hid, s) for s in SELECTABLE]}]
    if rec["status"] in SELECTABLE:
        actions[1]["initial_option"] = _opt(hid, rec["status"])
    if can_fix and rec.get("fix_available") and rec["status"] != "fixed":
        actions.append({"type": "button", "text": {"type": "plain_text", "text": "Fix and verify"}, "action_id": "dpdp_fix", "value": hid})
    blocks = [_section(head), _section(f"*{esc(rec['title'])}*"),
              {"type": "context", "elements": [{"type": "mrkdwn", "text": cut(c, 300)} for c in context]},
              {"type": "actions", "elements": actions}]
    return f"{hid} {label} {status}: {rec['title']}", blocks


def details(rec: dict) -> tuple[str, list]:
    """Thread reply for View Details. `rec` is GET /findings/{id}: the record plus the last finding JSON."""
    f = rec["finding"]
    parts = [f"*{rec['human_id']}: {esc(f['title'])}*", esc(f.get("explanation", ""))]
    if f.get("severity_reason"):
        parts.append(f"_Why {rec['severity']}:_ {esc(f['severity_reason'])}")
    if f.get("clauses"):
        parts.append("\n".join(f"• Likely does not meet {esc(c['ref'])}: {esc(c['note'])}" for c in f["clauses"]))
    ev = f.get("evidence") or {}
    evidence = f"*Evidence:* {esc(ev.get('summary', ''))}"
    if ev.get("masked_sample"):
        evidence += f"\n```{cut(ev['masked_sample'], 600).replace('```', "'''")}```"  # masked by the engine, never raw
    parts.append(evidence)
    if f.get("recommendation"):
        parts.append(f"*Recommendation:* {esc(f['recommendation'])}")
    return f"{rec['human_id']} details", [_section(p) for p in parts if p.strip()]


def summary(repo: str, delta: dict, errors: list[str] = ()) -> tuple[str, list]:
    """The message after every scan. An incomplete scan always starts with the partial warning and always reads Unknown."""
    complete = delta["complete"]
    h = delta["health"]
    status = h["status"] if complete else "unknown"  # never trust a green status over an incomplete scan
    emoji, label = HEALTH.get(status, HEALTH["unknown"])
    lines = [] if complete else ["*Scan incomplete: results are partial*"]
    commit = f" · `{delta['commit'][:7]}`" if delta.get("commit") else ""
    lines.append(f"*{esc(repo)}* · scan {delta['scan_id']}{commit}")
    lines.append(f"New {len(delta['new'])} · Resolved {len(delta['resolved'])} · Reopened {len(delta['reopened'])} · "
                 f"Persistent {delta['persistent']} · Suppressed {delta['suppressed']}")
    lines.append(f":{emoji}: Health: *{label}*")
    coverage = next((r for r in h["reasons"] if r.startswith("static checks only")), None)
    if coverage:
        lines.append(f"Coverage: {esc(coverage)}")
    lines += [f"• {esc(cut(r, 200))}" for r in h["reasons"] if r != coverage][:4]
    lines += [f"• Scan error: {esc(cut(e, 200))}" for e in list(errors)[:3]]
    return lines[0] if not complete else f"{repo}: scan {delta['scan_id']} complete, health {label}", [_section("\n".join(lines))]


def diff(repo: str, d: dict, dashboard_url: str, errors: list[str] = ()) -> tuple[str, list]:
    """/dpdp diff: the latest scan against the baseline. An incomplete scan says so first and its Resolved list is only what it could check."""
    link = lambda ids: ", ".join(f"<{dashboard_url.rstrip('/')}/?finding={h}|{h}>" for h in ids[:15]) + (f" and {len(ids) - 15} more" if len(ids) > 15 else "")  # noqa: E731
    lines = [] if d["complete"] else ["*Scan incomplete: results are partial*"]
    lines.append(f"*{esc(repo)}* · scan {d['scan_id']} against baseline {d['baseline_scan_id']}")
    lines.append(f"New {len(d['new'])} · Resolved {len(d['resolved'])} · Persistent {len(d['persistent'])}")
    lines += [f"{label}: {link(d[key])}" for label, key in (("New", "new"), ("Resolved", "resolved")) if d[key]]
    lines += [f"• Scan error: {esc(cut(e, 200))}" for e in list(errors)[:3]]
    return lines[0] if not d["complete"] else f"{repo}: scan {d['scan_id']} against baseline {d['baseline_scan_id']}", [_section("\n".join(lines))]


def failed(repo: str, scan_id: str, why: str) -> tuple[str, list]:
    text = f"*Scan failed: no results for {esc(repo)} ({scan_id})*\n:grey_question: Health: *Unknown*. This is not a pass.\n{esc(cut(why, 300))}"
    return f"Scan failed for {repo}", [_section(text)]


def github_link(url: str) -> tuple[str, list]:
    """No installation yet: a link button to the engine's /github/connect (it redirects to GitHub). The signed state is never in Slack."""
    text = "Connect GitHub: install the DPDP Lens GitHub App on your account and pick the repositories to share (read-only)."
    return text, [_section(text), {"type": "actions", "elements": [
        {"type": "button", "action_id": "dpdp_github_link", "text": {"type": "plain_text", "text": "Connect GitHub"}, "url": url, "style": "primary"}]}]


def repo_picker(repos: list[dict]) -> tuple[str, list]:
    """repos: [{installation_id, full_name, connected}]. Slack allows 100 options per select, so a longer list is cut and says so."""
    shown = repos[:100]
    options = [{"text": {"type": "plain_text", "text": cut(r["full_name"] + (" (connected)" if r["connected"] else ""), 75)},
                "value": f"{r['installation_id']}|{r['full_name']}"} for r in shown]
    text = "Pick a repository to connect and scan" + (f" (showing {len(shown)} of {len(repos)})" if len(repos) > len(shown) else "")
    return text, [_section(text), {"type": "actions", "block_id": "repo_pick", "elements": [
        {"type": "static_select", "action_id": "dpdp_repo_pick", "placeholder": {"type": "plain_text", "text": "Repository"}, "options": options},
        {"type": "button", "action_id": "dpdp_repo_connect", "text": {"type": "plain_text", "text": "Connect"}, "style": "primary"}]}]


def repo_list(repos: list[dict]) -> str:
    lines = [f"• {esc(r['full_name'])}" + (" (connected)" if r["connected"] else "") for r in repos[:40]]
    return f"*Repositories shared with the GitHub App ({len(repos)})*\n" + "\n".join(lines) + (f"\n…and {len(repos) - 40} more" if len(repos) > 40 else "")


def alert(repo: str, health: dict, scan_id: str = "") -> tuple[str, list]:
    emoji, label = HEALTH.get(health["status"], HEALTH["unknown"])
    what = "A scan was incomplete or failed, or no complete scan is recent. This is not a pass." if health["status"] == "unknown" \
        else "Blocking findings are open."
    lines = [f":{emoji}: *{esc(repo)}: health is {label}*", what] + [f"• {esc(cut(r, 200))}" for r in health["reasons"][:4]]
    return f"{repo}: health is {label}", [_section("\n".join(lines))]


def recovery(repo: str, health: dict) -> tuple[str, list]:
    emoji, label = HEALTH.get(health["status"], HEALTH["unknown"])
    lines = [f":{emoji}: *{esc(repo)}: health recovered, now {label}*"] + [f"• {esc(cut(r, 200))}" for r in health["reasons"][:3]]
    return f"{repo}: health recovered, now {label}", [_section("\n".join(lines))]


def diff_reply(hid: str, diff: str) -> tuple[str, list]:
    body = cut((diff or "(no diff returned)").replace("```", "'''"), 2700)
    return f"{hid} diff", [_section(f"*Diff* (applied to a sandbox copy only)\n```{body}```")]


def reason_modal(hid: str, status: str, meta: str) -> dict:
    """Modal asking for the reason. `meta` is the private_metadata string the submission handler reads back."""
    return {"type": "modal", "callback_id": "dpdp_reason", "private_metadata": meta,
            "title": {"type": "plain_text", "text": "Reason"}, "submit": {"type": "plain_text", "text": "Save"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [{"type": "input", "block_id": "reason", "label": {"type": "plain_text", "text": f"Why is {hid} {STATUS[status]}?"},
                        "hint": {"type": "plain_text", "text": "Up to 300 characters. Do not paste personal data."},
                        "element": {"type": "plain_text_input", "action_id": "text", "multiline": True, "max_length": 300}}]}
