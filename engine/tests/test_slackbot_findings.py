"""Block 10: /dpdp findings and the "still open" line in the scan summary, against the fake Slack client and the fake engine."""
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

    @property
    def text(self):
        return "\n".join(b["text"]["text"] if blocks else text for text, blocks in self.sent for b in (blocks or [None]))


def run(ctx, text, user=OTHER):
    reply = Reply()
    commands.run_command(ctx, text, user, CHANNEL, reply)
    return reply


def connected():
    ctx, slack, st = make_ctx()
    run(ctx, "connect acme/tutornest", APPROVER)  # three open findings: critical, high, medium
    return ctx, slack, st


def add(st, n, severity="medium", status="open", title="Extra finding"):
    for i in range(n):
        hid = f"DPDP-{len(st.findings) + 1:03d}"
        st.findings[hid] = dict(check="log_pii", severity=severity, proof="static", layer="code", title=f"{title} {i}", fix=False, file=f"app/m{i}.py",
                                line=i + 1, explanation="x", sample="a***@x.com", human_id=hid, status=status, reason="", by="system", slack=None)


def lines(reply):
    return [x for x in reply.text.split("\n") if "?finding=" in x]


def test_a_normal_list_is_critical_first_with_links_titles_locations_and_status():
    ctx, slack, st = connected()
    calls = len(slack.calls)
    r = run(ctx, "findings")
    got = lines(r)
    assert [x.split()[1] for x in got] == ["CRITICAL", "HIGH", "MEDIUM"]  # sorted by severity, not by id
    first = got[0]
    assert first.startswith(":red_circle: CRITICAL <http://dash.test/?finding=DPDP-003|DPDP-003> Personal data open to anyone")
    assert "· /api/students ·" in first and first.endswith("· Open")
    assert "backend/app/main.py:87" in got[1] and ":large_orange_circle:" in got[1] and ":large_yellow_circle:" in got[2]
    assert "Open findings: 3" in r.text and "Not a clean result" not in r.text
    assert len(slack.calls) == calls  # an ephemeral reply, nothing posted to the channel


def test_open_is_the_default_and_lists_in_progress_but_not_fixed_or_suppressed():
    ctx, slack, st = connected()
    st.findings["DPDP-001"]["status"] = "in_progress"
    st.findings["DPDP-002"]["status"] = "false_positive"
    st.findings["DPDP-003"]["status"] = "fixed"
    got = lines(run(ctx, "findings"))
    assert len(got) == 1 and "DPDP-001" in got[0] and got[0].endswith("In Progress")
    assert lines(run(ctx, "findings open")) == got


def test_all_groups_by_status_and_labels_suppressed_ones():
    ctx, slack, st = connected()
    st.findings["DPDP-001"]["status"] = "false_positive"
    st.findings["DPDP-002"]["status"] = "wont_fix"
    st.findings["DPDP-003"]["status"] = "fixed"
    add(st, 1, "low")
    r = run(ctx, "findings all")
    text = r.text
    heads = [x for x in text.split("\n") if x.startswith("*") and "·" in x and "?finding" not in x][1:]
    assert [h.split("*")[1] for h in heads] == ["Open", "Fixed", "False Positive", "Won't Fix"]
    assert "(suppressed: not counted in health)" in text
    suppressed = [x for x in lines(r) if "DPDP-001" in x or "DPDP-002" in x]
    assert len(suppressed) == 2 and all(x.endswith("(suppressed)") for x in suppressed)
    assert "(suppressed)" not in [x for x in lines(r) if "DPDP-003" in x][0]
    assert len(lines(r)) == 4


def test_suppressed_findings_are_never_listed_under_open():
    ctx, slack, st = connected()
    st.findings["DPDP-001"]["status"] = "wont_fix"
    r = run(ctx, "findings")
    assert "DPDP-001" not in r.text and "suppressed" not in r.text and len(lines(r)) == 2


def test_an_empty_list_is_said_plainly():
    ctx, slack, st = connected()
    for f in st.findings.values():
        f["status"] = "fixed"
    r = run(ctx, "findings")
    assert "No open findings are stored for this repo." in r.text and lines(r) == [] and "Not a clean result" not in r.text
    st.findings.clear()
    assert "No findings are stored for this repo." in run(ctx, "findings all").text


def test_over_50_shows_50_lines_critical_first_and_says_how_many_more():
    ctx, slack, st = connected()
    add(st, 57, "low", title="A long enough title to make the lines add up")
    r = run(ctx, "findings")
    got = lines(r)
    assert len(got) == 50 and "CRITICAL" in got[0] and "HIGH" in got[1] and "MEDIUM" in got[2] and all("LOW" in x for x in got[3:])
    assert "and 10 more, see the dashboard" in r.text
    assert all(len(b["text"]["text"]) <= 3000 for _, blocks in r.sent for b in blocks)  # a Slack section holds 3000 characters
    assert len(r.sent[0][1]) <= 50
    allr = run(ctx, "findings all")
    assert len(lines(allr)) == 50 and "and 10 more, see the dashboard" in allr.text


def test_an_incomplete_scan_says_so_in_the_first_line_and_never_reads_clean():
    ctx, slack, st = make_ctx()
    st.complete = False
    run(ctx, "connect acme/tutornest", APPROVER)
    r = run(ctx, "findings")
    first = r.text.split("\n")[0]
    assert "Not a clean result" in first and "incomplete" in first and "partial" in first
    st.findings.clear()
    empty = run(ctx, "findings")
    assert empty.text.split("\n")[0] == first and "not a pass" in empty.text and empty.sent[0][0] == first  # even the plain text starts with the warning


@pytest.mark.parametrize("health, word", [
    ({"status": "unknown", "reasons": [], "last_complete_scan_at": None, "last_scan_status": "failed", "counts": {}}, "failed"),
    ({"status": "unknown", "reasons": [], "last_complete_scan_at": None, "last_scan_status": None, "counts": {}}, "Unknown")])
def test_a_failed_scan_or_unknown_health_warns_first(health, word):
    ctx, slack, st = connected()
    st.health = health
    first = run(ctx, "findings").text.split("\n")[0]
    assert "Not a clean result" in first and word in first


def test_a_bad_argument_gets_the_usage_and_help_lists_the_command():
    ctx, slack, st = connected()
    assert "Usage: `/dpdp findings" in run(ctx, "findings everything").text
    assert "Usage" in run(ctx, "findings open all").text
    assert "/dpdp findings [open|all]" in run(ctx, "help").text


def test_findings_needs_a_repo_in_the_channel():
    ctx, slack, st = make_ctx()
    assert "none is connected yet" in run(ctx, "findings").text


def test_no_raw_personal_data_in_any_payload_text():
    ctx, slack, st = connected()
    add(st, 3, "high", title="Aadhaar 2345 6789 0123 logged")  # a title is the engine's own text: the masking happens there, but the bot adds nothing raw
    for f in st.findings.values():
        f["title"] = "Personal data in a log"
    replies = [run(ctx, "findings"), run(ctx, "findings all")]
    everything = json.dumps(replies[0].sent) + json.dumps(replies[1].sent) + slack.texts()
    assert not PII.search(everything)


def test_the_scan_summary_counts_open_findings_and_points_to_the_command():
    ctx, slack, st = make_ctx()
    run(ctx, "connect acme/tutornest", APPROVER)
    summary = slack.of("post")[1]["blocks"][0]["text"]["text"]
    assert "3 findings still open: /dpdp findings" in summary
    posts = len(slack.of("post"))
    run(ctx, "scan", APPROVER)  # nothing changed: a summary, and no card for an unchanged finding (dedup)
    again = slack.of("post")[posts:]
    assert len(again) == 2 and "3 findings still open: /dpdp findings" in again[1]["blocks"][0]["text"]["text"]  # "Scanning" line plus the summary


def test_the_summary_line_is_singular_for_one_and_absent_for_none():
    delta = {"scan_id": "S-1", "complete": True, "commit": "", "new": [], "reopened": [], "resolved": [], "persistent": 0, "suppressed": 2,
             "health": {"status": "healthy", "reasons": [], "counts": {"open": 0, "in_progress": 0}}}
    assert "still open" not in cards.summary("acme/x", delta)[1][0]["text"]["text"]
    delta["health"]["counts"]["open"] = 1
    assert "1 finding still open: /dpdp findings" in cards.summary("acme/x", delta)[1][0]["text"]["text"]
