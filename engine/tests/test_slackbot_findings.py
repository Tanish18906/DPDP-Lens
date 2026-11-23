"""Blocks 10 and 12: /dpdp findings as interactive ephemeral rows (fake Slack client, fake engine). The first version of this file tested a
read-only list with dashboard links; block 12 replaced it with rows, so each earlier check is kept in its new form."""
import json

import pytest

from dpdp_lens.slackbot import cards, commands
from slackbot_fakes import APPROVER, CHANNEL, OTHER, PII, make_ctx, stop_servers


@pytest.fixture(autouse=True)
def _stop_fake_engines():
    yield
    stop_servers()


class Reply:
    def __init__(self):
        self.sent = []

    def __call__(self, text, blocks=None):
        self.sent.append((text, blocks))


def run(ctx, text, user=OTHER):
    reply = Reply()
    commands.run_command(ctx, text, user, CHANNEL, reply)
    return reply


def connected(**kw):
    ctx, slack, st = make_ctx(**kw)
    run(ctx, "connect acme/tutornest", APPROVER)  # three open findings: critical, high, medium
    return ctx, slack, st


def add(st, n, severity="medium", status="open", title="Extra finding", fix=False):
    for i in range(n):
        hid = f"DPDP-{len(st.findings) + 1:03d}"
        st.findings[hid] = dict(check="log_pii", severity=severity, proof="static", layer="code", title=f"{title} {i}", fix=fix, file=f"app/m{i}.py",
                                line=i + 1, explanation="x", sample="a***@x.com", human_id=hid, status=status, reason="", by="system", slack=None)


def pages(r, slack):
    """Every message of one /dpdp findings answer: the command's own reply first, then the further ephemeral pages."""
    return [blocks for _, blocks in r.sent] + [c["blocks"] for c in slack.of("ephemeral")]


def rows(blocks_list):
    """(human_id, [action ids]) of every row, in order, over all pages."""
    out = []
    for blocks in blocks_list:
        for b in blocks:
            if b["type"] == "actions" and b["block_id"].startswith("row:"):
                out.append((b["block_id"].split(":")[2], [e["action_id"] for e in b["elements"]]))
    return out


def texts(blocks_list):
    return "\n".join(b["text"]["text"] if b["type"] == "section" else " ".join(e["text"] for e in b["elements"] if "text" in e and isinstance(e["text"], str))
                     for blocks in blocks_list for b in blocks if b["type"] in ("section", "context"))


def test_rows_are_critical_first_plain_ids_with_title_location_status_and_actions():
    ctx, slack, st = connected()
    r = run(ctx, "findings")
    got = rows(pages(r, slack))
    assert [h for h, _ in got] == ["DPDP-003", "DPDP-001", "DPDP-002"]  # critical, high, medium: not by id
    text = texts(pages(r, slack))
    assert ":red_circle: *CRITICAL* · DPDP-003\n*Personal data open to anyone*" in text and "`/api/students` · Status: *Open*" in text
    assert "`backend/app/main.py:87` · Status: *Open*" in text and ":large_orange_circle: *HIGH* · DPDP-001" in text
    assert "?finding=" not in json.dumps(pages(r, slack)) and "http://dash.test" not in json.dumps(pages(r, slack))  # no dashboard link in the list
    assert all(a[:2] == ["dpdp_row_details", "dpdp_row_status"] for _, a in got)
    select = pages(r, slack)[0][3]["elements"][1]
    assert [o["text"]["text"] for o in select["options"]] == ["Open", "In Progress", "False Positive", "Won't Fix"] and select["initial_option"]["value"] == "DPDP-003|open"
    posted = len(slack.of("post"))
    run(ctx, "findings")
    assert len(slack.of("post")) == posted  # the list is ephemeral: nothing is posted to the channel


def test_fix_and_verify_only_for_an_approver_a_fixable_finding_and_a_repo_that_allows_it():
    ctx, slack, st = connected()
    approver = dict(rows(pages(run(ctx, "findings", APPROVER), slack)))
    assert "dpdp_row_fix" in approver["DPDP-001"] and "dpdp_row_fix" in approver["DPDP-003"] and "dpdp_row_fix" not in approver["DPDP-002"]  # 002 has no fix
    other = Reply()
    commands.run_command(ctx, "findings", OTHER, CHANNEL, other)
    assert all("dpdp_row_fix" not in a for _, a in rows(pages(other, slack)[:1]))  # not an approver
    ctx2, slack2, st2 = connected(fix_repos=())  # a repo that does not allow fixing
    assert all("dpdp_row_fix" not in a for _, a in rows(pages(run(ctx2, "findings", APPROVER), slack2)))


def test_open_is_the_default_and_lists_in_progress_but_not_fixed_or_suppressed():
    ctx, slack, st = connected()
    st.findings["DPDP-001"]["status"] = "in_progress"
    st.findings["DPDP-002"]["status"] = "false_positive"
    st.findings["DPDP-003"]["status"] = "fixed"
    r = run(ctx, "findings")
    assert [h for h, _ in rows(pages(r, slack))] == ["DPDP-001"] and "Status: *In Progress*" in texts(pages(r, slack))
    assert [h for h, _ in rows(pages(run(ctx, "findings open"), slack))] == ["DPDP-001"]  # "open" is the default
    assert "suppressed" not in texts(pages(r, slack))


def test_all_groups_by_status_and_labels_suppressed_ones():
    ctx, slack, st = connected()
    st.findings["DPDP-001"]["status"] = "false_positive"
    st.findings["DPDP-002"]["status"] = "wont_fix"
    st.findings["DPDP-003"]["status"] = "fixed"
    add(st, 1, "low")
    r = run(ctx, "findings all")
    text = texts(pages(r, slack))
    heads = [x for x in text.split("\n") if x.startswith("*") and x.endswith(("· 1", "· 2")) and "CRITICAL" not in x]
    assert [h.split("*")[1] for h in heads] == ["Open", "Fixed", "False Positive", "Won't Fix"]
    assert "(suppressed: not counted in health)" in text and text.count("Status: *False Positive* (suppressed)") == 1 and text.count("Status: *Won't Fix* (suppressed)") == 1
    assert "Status: *Fixed* (suppressed)" not in text and "Status: *Open* (suppressed)" not in text
    assert [h for h, _ in rows(pages(r, slack))] == ["DPDP-004", "DPDP-003", "DPDP-001", "DPDP-002"]  # grouped: open, fixed, false positive, won't fix
    assert "dpdp_row_fix" not in dict(rows(pages(r, slack)))["DPDP-003"]  # a fixed finding has no fix button


def test_an_empty_list_is_said_plainly():
    ctx, slack, st = connected()
    for f in st.findings.values():
        f["status"] = "fixed"
    r = run(ctx, "findings")
    assert "No open findings are stored for this repo." in texts(pages(r, slack)) and rows(pages(r, slack)) == []
    st.findings.clear()
    assert "No findings are stored for this repo." in texts(pages(run(ctx, "findings all"), slack))


def test_a_long_list_is_paged_in_messages_of_at_most_50_blocks_and_nothing_is_dropped():
    ctx, slack, st = connected()
    add(st, 57, "low", title="A long enough title to make the page add up")
    reply = Reply()
    commands.run_command(ctx, "findings", APPROVER, CHANNEL, reply)
    allpages = pages(reply, slack)
    assert len(allpages) == 4 and all(len(p) <= 50 for p in allpages)  # 60 rows, 3 blocks each, 16 rows per page
    got = rows(allpages)
    assert len(got) == 60 and len({h for h, _ in got}) == 60  # every finding exactly once: never silently truncated
    assert [h for h, _ in got][:3] == ["DPDP-003", "DPDP-001", "DPDP-002"]  # critical first across pages
    assert len(reply.sent) == 1 and len(slack.of("ephemeral")) == 3 and all(c["user"] == APPROVER for c in slack.of("ephemeral"))
    assert "Page 1 of 4" in texts(allpages[:1]) and "Page 4 of 4" in texts(allpages[3:])
    assert "and 10 more" not in texts(allpages)
    for p in allpages:
        assert all(len(b["text"]["text"]) <= 3000 for b in p if b["type"] == "section")


def test_the_list_header_lines_say_incomplete_failed_or_unknown_before_any_row():
    ctx, slack, st = make_ctx()
    st.complete = False
    run(ctx, "connect acme/tutornest", APPROVER)
    r = run(ctx, "findings")
    first = r.sent[0][1][0]["text"]["text"]
    assert first.splitlines()[0].startswith(":grey_question: *Not a clean result:") and "incomplete" in first and "partial" in first
    assert r.sent[0][1].index(next(b for b in r.sent[0][1] if b["type"] == "actions")) > 0  # rows come after the warning
    st.findings.clear()
    empty = run(ctx, "findings")
    assert empty.sent[0][1][0]["text"]["text"].splitlines()[0] == first.splitlines()[0] and "not a pass" in empty.sent[0][1][0]["text"]["text"]


@pytest.mark.parametrize("health, word", [
    ({"status": "unknown", "reasons": [], "last_complete_scan_at": None, "last_scan_status": "failed", "counts": {}}, "failed"),
    ({"status": "unknown", "reasons": [], "last_complete_scan_at": None, "last_scan_status": None, "counts": {}}, "Unknown")])
def test_a_failed_scan_or_unknown_health_warns_first(health, word):
    ctx, slack, st = connected()
    st.health = health
    first = run(ctx, "findings").sent[0][1][0]["text"]["text"].splitlines()[0]
    assert "Not a clean result" in first and word in first


def test_a_bad_argument_gets_the_usage_and_help_lists_the_command():
    ctx, slack, st = connected()
    assert "Usage: `/dpdp findings" in run(ctx, "findings everything").sent[0][0]
    assert "Usage" in run(ctx, "findings open all").sent[0][0]
    assert "/dpdp findings [open|all]" in run(ctx, "help").sent[0][0]


def test_findings_needs_a_repo_in_the_channel():
    ctx, slack, st = make_ctx()
    assert "none is connected yet" in run(ctx, "findings").sent[0][0]


def test_no_raw_personal_data_or_token_in_any_payload():
    ctx, slack, st = connected()
    add(st, 3, "high", title="Aadhaar logged")
    everything = json.dumps([pages(run(ctx, "findings"), slack), pages(run(ctx, "findings all"), slack)]) + slack.texts()
    assert not PII.search(everything) and "xoxb" not in everything and "ghs_" not in everything


def test_the_scan_summary_counts_open_findings_and_points_to_the_command():
    ctx, slack, st = make_ctx()
    run(ctx, "connect acme/tutornest", APPROVER)
    assert "3 findings still open: /dpdp findings" in slack.of("post")[1]["blocks"][0]["text"]["text"]
    posts = len(slack.of("post"))
    run(ctx, "scan", APPROVER)  # nothing changed: a summary and no card for an unchanged finding (dedup)
    again = slack.of("post")[posts:]
    assert len(again) == 2 and "3 findings still open: /dpdp findings" in again[1]["blocks"][0]["text"]["text"]


def test_the_summary_line_is_singular_for_one_and_absent_for_none():
    delta = {"scan_id": "S-1", "complete": True, "commit": "", "new": [], "reopened": [], "resolved": [], "persistent": 0, "suppressed": 2,
             "health": {"status": "healthy", "reasons": [], "counts": {"open": 0, "in_progress": 0}}}
    assert "still open" not in cards.summary("acme/x", delta)[1][0]["text"]["text"]
    delta["health"]["counts"]["open"] = 1
    assert "1 finding still open: /dpdp findings" in cards.summary("acme/x", delta)[1][0]["text"]["text"]
