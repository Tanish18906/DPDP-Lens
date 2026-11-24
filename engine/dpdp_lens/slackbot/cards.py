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
    head = f"{hid}   {emoji} *{label}*   ·   Status: *{status}*"  # plain id: acting happens in Slack, the dashboard link is only in View Details
    context = [f"`{esc(_where(rec['location']))}`", f"{esc(rec['repo'])}@{esc(rec['branch'] or 'default branch')}",
               PROOF.get(rec["proof"], "Static check")]
    if rec["status"] != "open" and rec.get("status_reason"):
        context.append(f"Reason: {esc(cut(rec['status_reason'], 120))}")
    if rec.get("pr_url"):
        context.append(f"<{rec['pr_url']}|Pull request>")
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


def fix_summary(hid: str, out: dict) -> tuple[list[str], bool]:
    """The lines about a fix run, from the engine's own answer (POST /findings/{id}/fix). Returns (lines, verified). VERIFIED only when the
    engine says fix.verified is true AND the finding is verified_fixed. A cached replay is labelled as one."""
    fix = out["finding"]["fix"]
    verified = fix.get("verified") is True and out["finding"]["status"] == "verified_fixed"
    if verified:
        how = "Cached verified patch (replay)" if out["mode"] == "cached_golden" else "VERIFIED by a live sandbox run"
        if out.get("fallback_reason"):
            how += f" (the live run could not start: {out['fallback_reason']})"
        lines = [f":white_check_mark: *{hid}: {how}*"]
    else:
        lines = [f":x: *{hid}: Not verified*"]
    lines.append(f"Re-scan of the fixed copy: {_yn(fix.get('rescan_passed'))} · App tests: {_yn(fix.get('tests_passed'))}")
    if fix.get("score_before") is not None and fix.get("score_after") is not None:
        lines.append(f"Score {fix['score_before']} to {fix['score_after']}")
    return lines, verified


def _yn(v) -> str:
    return "passed" if v is True else "failed" if v is False else "not run"


def fix_scope_lines(fix: dict, verified: bool) -> list[str]:
    """Two lines: what the run verified and what it did not. Built from the engine's fix fields, nothing else."""
    if verified:
        first = (f"*Verified:* the re-scan of the fixed sandbox copy no longer finds this ({_yn(fix.get('rescan_passed'))}), "
                 f"and the repo's own tests: {_yn(fix.get('tests_passed'))}.")
    else:
        first = "*Not verified:* the fix did not pass the re-scan and the tests, so this finding stays open."
    return [first, "*Not verified, you still must:* your repository itself was not changed. Apply the diff, review it, run your own tests and deploy. "
                   "Other findings are not affected."]


def details(rec: dict, dashboard_url: str = "", fix_button: bool = False, pr: bool = False) -> tuple[str, list]:
    """The reply for View Details (a thread reply under a card, or an ephemeral message under a list). `rec` is GET /findings/{id}: the
    record plus the last finding JSON. fix_button adds Fix and verify (the caller decides: approver, repo allows, fix available).
    dashboard_url adds a small "Open in dashboard" line at the bottom, never the main action."""
    f = rec["finding"]
    parts = [f"*{rec['human_id']}: {esc(f['title'])}*  ·  {PROOF.get(rec.get('proof'), 'Static check')}", esc(f.get("explanation", ""))]
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
    fix = f.get("fix") or {}
    if fix.get("verified") or fix.get("rescan_passed") is not None or fix.get("tests_passed") is not None:  # a fix was run on this finding
        verified = fix.get("verified") is True and rec["status"] == "fixed"
        parts.append("\n".join([":white_check_mark: *Verified fix*" if verified else ":x: *Not verified*",
                               f"Re-scan of the fixed copy: {_yn(fix.get('rescan_passed'))} · App tests: {_yn(fix.get('tests_passed'))}",
                               *fix_scope_lines(fix, verified)]))
    blocks = [_section(p) for p in parts if p.strip()]
    buttons = []
    if fix_button:
        buttons.append({"type": "button", "text": {"type": "plain_text", "text": "Fix and verify"}, "action_id": "dpdp_row_fix", "value": rec["human_id"]})
    if pr and not rec.get("pr_url"):
        buttons.append(pr_button(rec["human_id"]))
    if buttons:
        blocks.append({"type": "actions", "block_id": f"det:{rec['human_id']}", "elements": buttons})
    if rec.get("pr_url"):
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Pull request: <{rec['pr_url']}|{rec['pr_url']}>"}]})
    if dashboard_url:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{dashboard_url.rstrip('/')}/?finding={rec['human_id']}|Open in dashboard>"}]})
    return f"{rec['human_id']} details", blocks


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
    counts = h.get("counts") or {}
    open_n = counts.get("open", 0) + counts.get("in_progress", 0) or len(delta["new"]) + len(delta["reopened"]) + delta["persistent"]
    if open_n:
        lines.append(f"{open_n} finding{'s' if open_n != 1 else ''} still open: /dpdp findings")
    lines.append(f":{emoji}: Health: *{label}*")
    coverage = next((r for r in h["reasons"] if r.startswith("static checks only")), None)
    if coverage:
        lines.append(f"Coverage: {esc(coverage)}")
    lines += [f"• {esc(cut(r, 200))}" for r in h["reasons"] if r != coverage][:4]
    lines += [f"• Scan error: {esc(cut(e, 200))}" for e in list(errors)[:3]]
    return lines[0] if not complete else f"{repo}: scan {delta['scan_id']} complete, health {label}", [_section("\n".join(lines))]


SUPPRESSED = ("false_positive", "wont_fix")
LIST_ORDER = ("open", "in_progress", "fixed", "false_positive", "wont_fix")
MAX_BLOCKS = 50  # Slack's limit for one message


def findings_header(repo: str, count: int, mode: str, health: dict) -> list[str]:
    """First lines of /dpdp findings. A scan that was incomplete or failed, or Unknown health, comes first and the list never reads clean."""
    lines = []
    if health.get("last_scan_status") not in ("complete", None, "") or health.get("status") == "unknown":
        why = {"incomplete": "the last scan was incomplete, so this list may be partial",
               "failed": "the last scan failed, so this list may be out of date"}.get(health.get("last_scan_status"), "health is Unknown, so this list may be partial or stale")
        lines.append(f":grey_question: *Not a clean result: {why}.*")
    unsure = bool(lines)
    lines.append(f"*{esc(repo)}* · {'Open findings' if mode == 'open' else 'All findings'}: {count}")
    if not count:
        lines.append("No open findings are stored for this repo." if mode == "open" else "No findings are stored for this repo.")
        if unsure:
            lines.append("That is not a pass: the scan did not finish cleanly.")
    return lines


def group_heading(status: str, n: int) -> str:
    return f"*{STATUS[status]}*" + (" (suppressed: not counted in health)" if status in SUPPRESSED else "") + f" · {n}"


def _pr_link(rec: dict) -> str:
    return f" · <{rec['pr_url']}|Pull request>" if rec.get("pr_url") else ""


def pr_button(hid: str) -> dict:
    return {"type": "button", "text": {"type": "plain_text", "text": "Open pull request"}, "action_id": "dpdp_row_pr", "value": hid}


def finding_row(rec: dict, pid: str, fix_button: bool, pr: bool = False) -> list[dict]:
    """One interactive row of /dpdp findings: three blocks. The id is plain text. Change Status is shown to everyone and refused for a
    non approver (same as the cards). Fix and verify only when `fix_button` (fix available, repo allows it, requester is an approver)."""
    hid = rec["human_id"]
    emoji, label = SEVERITY.get(rec["severity"], (":white_circle:", str(rec["severity"]).upper()))
    suppressed = " (suppressed)" if rec["status"] in SUPPRESSED else ""
    elements = [{"type": "button", "text": {"type": "plain_text", "text": "View Details"}, "action_id": "dpdp_row_details", "value": hid},
                {"type": "static_select", "action_id": "dpdp_row_status", "placeholder": {"type": "plain_text", "text": "Change Status"},
                 "options": [_opt(hid, st) for st in SELECTABLE]}]
    if rec["status"] in SELECTABLE:
        elements[1]["initial_option"] = _opt(hid, rec["status"])
    if fix_button and rec["status"] != "fixed":
        elements.append({"type": "button", "text": {"type": "plain_text", "text": "Fix and verify"}, "action_id": "dpdp_row_fix", "value": hid})
    if pr and not rec.get("pr_url"):  # only after a verified fix, when the engine says a pull request is allowed (rec["pr_available"])
        elements.append(pr_button(hid))
    return [_section(f"{emoji} *{label}* · {hid}\n*{esc(cut(rec['title'], 150))}*"),
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"`{esc(cut(_where(rec['location']), 200))}` · Status: *{STATUS.get(rec['status'], rec['status'])}*{suppressed}{_pr_link(rec)}"}]},
            {"type": "actions", "block_id": f"row:{pid}:{hid}", "elements": elements}]


def whole_lines(text: str, limit: int) -> tuple[str, int]:
    """The longest run of whole lines from the start of `text` that fits `limit` characters, and how many lines were left out. A line is
    never cut in the middle: a line longer than the limit is left out with the rest."""
    lines, used, kept = text.split("\n"), 0, []
    for line in lines:
        if used + len(line) + 1 > limit:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept), len(lines) - len(kept)


def diff_reply(hid: str, diff: str, limit: int = 2600) -> tuple[str, list]:
    body, left = whole_lines((diff or "(no diff returned)").replace("```", "'''"), limit)
    note = f"\n_{left} more line{'s' if left != 1 else ''} not shown (nothing is cut mid-line): the full diff is in the engine's answer._" if left else ""
    return f"{hid} diff", [_section(f"*Diff* (applied to a sandbox copy only)\n```{body}```{note}")]


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


def report_reply(repo: str, link: dict, engine_url: str) -> tuple[str, list]:
    """/dpdp report: the signed link (valid 15 minutes, only this reply shows it) and a one-line summary. An incomplete scan or an
    Unknown health is said first, so the line never reads as clean."""
    s = link["summary"]
    counts = ", ".join(f"{n} {k}" for k, n in s["open_by_severity"].items() if n) or "no open findings"
    first = [f":warning: {esc(w)}" for w in s.get("warnings", [])[:2]]
    emoji, label = HEALTH.get(s["health"], HEALTH["unknown"])
    line = f"{counts} · :{emoji}: Health: *{label}* · {esc(s['coverage'])}"
    url = engine_url.rstrip("/") + link["url"]
    text = "\n".join([*first, f"<{url}|DPDP readiness report> for *{esc(repo)}* (scan {link['scan_id']}, link valid {link['expires_in'] // 60} minutes)", line,
                      "_A readiness report from automated checks: not legal advice, not a compliance certificate._"])
    return f"DPDP readiness report for {repo}", [_section(text)]


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


def pr_result(hid: str, out: dict) -> tuple[str, list]:
    """The answer to Open pull request: the link, and what a person must still do. A reused pull request says so."""
    head = f":white_check_mark: *{hid}: pull request {'already open' if out.get('reused') else 'opened'}*: <{out['pr_url']}|{esc(out['pr_url'])}>"
    if out.get("branch"):
        head += f" (branch `{esc(out['branch'])}`)"
    lines = [head, "A person must review and merge it: nothing was merged for you. "
                   f"{hid} stays Fixed here; only a later scan of the merged code resolves it. This is a readiness fix, not a compliance certificate."]
    return f"{hid}: pull request opened", [_section("\n".join(lines))]


def reason_modal(hid: str, status: str, meta: str) -> dict:
    """Modal asking for the reason. `meta` is the private_metadata string the submission handler reads back."""
    return {"type": "modal", "callback_id": "dpdp_reason", "private_metadata": meta,
            "title": {"type": "plain_text", "text": "Reason"}, "submit": {"type": "plain_text", "text": "Save"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [{"type": "input", "block_id": "reason", "label": {"type": "plain_text", "text": f"Why is {hid} {STATUS[status]}?"},
                        "hint": {"type": "plain_text", "text": "Up to 300 characters. Do not paste personal data."},
                        "element": {"type": "plain_text_input", "action_id": "text", "multiline": True, "max_length": 300}}]}
