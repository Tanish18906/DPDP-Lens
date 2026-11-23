"""Block 11: /dpdp report against the fake Slack client and the fake engine."""
import pytest

from dpdp_lens.slackbot import commands
from slackbot_fakes import APPROVER, CHANNEL, OTHER, PII, TOKEN, make_ctx, stop_servers


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


def run(ctx, text, user=APPROVER):
    reply = Reply()
    commands.run_command(ctx, text, user, CHANNEL, reply)
    return reply


def connected():
    ctx, slack, st = make_ctx()
    run(ctx, "connect acme/tutornest")
    return ctx, slack, st


def test_report_replies_with_the_signed_link_and_a_one_line_summary():
    ctx, slack, st = connected()
    posts = len(slack.calls)
    r = run(ctx, "report")
    assert st.report_calls == [(1, {"actor": APPROVER})]
    assert f"<{ctx.cfg.engine_url}/repos/1/report?scan_id=S-001&sig=PAYLOAD.MAC|DPDP readiness report>" in r.text
    assert "for *acme/tutornest* (scan S-001, link valid 15 minutes)" in r.text
    assert "1 critical, 1 high, 1 medium" in r.text and "Health: *At risk*" in r.text and "static checks only (9 of 19)" in r.text
    assert "not legal advice, not a compliance certificate" in r.text
    assert len(slack.calls) == posts  # ephemeral: nothing is posted to the channel
    assert TOKEN not in r.text and not PII.search(r.text)  # the engine token never appears, only the short lived signed link


def test_report_is_for_approvers_only():
    ctx, slack, st = connected()
    r = run(ctx, "report", user=OTHER)
    assert "Not allowed" in r.text and st.report_calls == []


def test_report_with_a_repo_name_and_without_a_repo():
    ctx, slack, st = connected()
    assert "readiness report" in run(ctx, "report acme/tutornest").text
    assert "is not connected" in run(ctx, "report acme/nope").text
    other, _, st2 = make_ctx()
    assert "none is connected yet" in run(other, "report").text and st2.report_calls == []


def test_an_incomplete_scan_or_unknown_health_is_said_first():
    ctx, slack, st = connected()
    st.report_response = {"url": "/repos/1/report?scan_id=S-001&sig=A.B", "scan_id": "S-001", "expires_in": 900,
                          "summary": {"findings": 0, "open_by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0}, "health": "unknown",
                                      "coverage": "static checks only (8 of 19)", "complete": False,
                                      "warnings": ["Scan incomplete: results are partial (scan S-001). This is not a clean result."]}}
    r = run(ctx, "report")
    lines = r.text.split("\n")
    assert lines[0].startswith(":warning: Scan incomplete: results are partial") and "no open findings" in r.text and "Health: *Unknown*" in r.text


def test_help_lists_the_report_command():
    ctx, slack, st = make_ctx()
    assert "/dpdp report [owner/repo]" in run(ctx, "help").text
