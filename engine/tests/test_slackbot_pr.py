"""Block 13: Open pull request in Slack (rows, fix results, details), against the fake Slack client and fake engine."""
import json

import pytest

from dpdp_lens.slackbot import cards, commands, rows
from slackbot_fakes import APPROVER, CHANNEL, OTHER, make_ctx, stop_servers, verified_fix

URL = "https://hooks.slack.com/actions/T1/222/secretpart"


@pytest.fixture(autouse=True)
def _stop_fake_engines():
    yield
    stop_servers()


class Reply:
    def __init__(self):
        self.sent = []

    def __call__(self, text, blocks=None):
        self.sent.append((text, blocks))


def listed(user=APPROVER, allowed=True, **kw):
    ctx, slack, st = make_ctx(**kw)
    st.pr_allowed = allowed
    commands.run_command(ctx, "connect acme/tutornest", APPROVER, CHANNEL, lambda *a, **k: None)
    r = Reply()
    commands.run_command(ctx, "findings", user, CHANNEL, r)
    pid = next(b["block_id"].split(":")[1] for b in r.sent[0][1] if b["type"] == "actions")
    return ctx, slack, st, pid


def row_actions(blocks, hid):
    return [e["action_id"] for b in blocks if b["type"] == "actions" and b["block_id"].endswith(":" + hid) for e in b["elements"]]


def responses(slack):
    return slack.of("respond")


def test_a_verified_live_fix_result_offers_open_pull_request_to_an_approver():
    ctx, slack, st, pid = listed()
    rows.row_fix(ctx, APPROVER, CHANNEL, pid, "DPDP-001", URL)
    result = responses(slack)[1]
    last = result["blocks"][-1]
    assert last["type"] == "actions" and last["block_id"] == "pr:DPDP-001"
    assert [(e["text"]["text"], e["action_id"], e["value"]) for e in last["elements"]] == [("Open pull request", "dpdp_row_pr", "DPDP-001")]
    assert row_actions(responses(slack)[2]["blocks"], "DPDP-001") and "dpdp_row_pr" in row_actions(responses(slack)[2]["blocks"], "DPDP-001")  # the row too


def test_no_button_when_the_engine_does_not_allow_it_for_a_cached_replay_or_an_unverified_fix():
    ctx, slack, st, pid = listed(allowed=False)  # switch off, repo not in fix repos or not installed: the engine says pr_available false
    rows.row_fix(ctx, APPROVER, CHANNEL, pid, "DPDP-001", URL)
    assert all(b["type"] != "actions" for b in responses(slack)[1]["blocks"])
    ctx, slack, st, pid = listed()
    st.fix_response = verified_fix(mode="cached_golden")
    rows.row_fix(ctx, APPROVER, CHANNEL, pid, "DPDP-001", URL)
    assert all(b["type"] != "actions" for b in responses(slack)[1]["blocks"])  # a cached replay is not offered a pull request
    ctx, slack, st, pid = listed()
    st.fix_response = verified_fix(verified=False)
    rows.row_fix(ctx, APPROVER, CHANNEL, pid, "DPDP-001", URL)
    assert all(b["type"] != "actions" for b in responses(slack)[1]["blocks"])


def test_the_row_of_a_fixed_finding_has_the_button_only_for_an_approver_and_only_when_allowed():
    ctx, slack, st, pid = listed()
    st.findings["DPDP-001"]["status"] = "fixed"
    approver = Reply()
    commands.run_command(ctx, "findings all", APPROVER, CHANNEL, approver)
    assert "dpdp_row_pr" in row_actions(approver.sent[0][1], "DPDP-001") and "dpdp_row_pr" not in row_actions(approver.sent[0][1], "DPDP-002")
    other = Reply()
    commands.run_command(ctx, "findings all", OTHER, CHANNEL, other)
    assert "dpdp_row_pr" not in row_actions(other.sent[0][1], "DPDP-001")  # not an approver
    st.pr_allowed = False
    off = Reply()
    commands.run_command(ctx, "findings all", APPROVER, CHANNEL, off)
    assert "dpdp_row_pr" not in row_actions(off.sent[0][1], "DPDP-001")  # the engine says no


def test_clicking_open_pull_request_calls_the_engine_shows_the_link_and_updates_the_row_and_the_card():
    ctx, slack, st, pid = listed()
    st.findings["DPDP-001"]["status"] = "fixed"
    rows.row_pr(ctx, APPROVER, CHANNEL, pid, "DPDP-001", URL)
    assert st.pr_calls == [("DPDP-001", {"actor": APPROVER})]
    first, result, replaced = responses(slack)
    assert "Opening a pull request for DPDP-001" in first["text"] and "Nothing is merged" in first["text"]
    text = result["blocks"][0]["text"]["text"]
    assert ":white_check_mark: *DPDP-001: pull request opened*: <https://github.com/acme/tutornest/pull/9|https://github.com/acme/tutornest/pull/9>" in text
    assert "(branch `dpdp-lens/fix-DPDP-001-abc1234`)" in text and "A person must review and merge it" in text and "stays Fixed here" in text
    assert "not a compliance certificate" in text
    ctxline = next(b for i, b in enumerate(replaced["blocks"]) if b["type"] == "context" and "Pull request" in b["elements"][0]["text"])["elements"][0]["text"]
    assert "<https://github.com/acme/tutornest/pull/9|Pull request>" in ctxline and "dpdp_row_pr" not in row_actions(replaced["blocks"], "DPDP-001")
    card = [c for c in slack.of("update") if "Pull request" in json.dumps(c["blocks"])]
    assert card  # the public card shows the link too


def test_a_refusal_from_the_engine_is_shown_plainly_and_nothing_else_happens():
    ctx, slack, st, pid = listed()
    st.findings["DPDP-001"]["status"] = "fixed"
    st.pr_error = (403, "pull requests are switched off on this engine: set DPDP_ALLOW_PR=1 to allow them")
    rows.row_pr(ctx, APPROVER, CHANNEL, pid, "DPDP-001", URL)
    assert responses(slack)[-1]["text"] == ":x: The pull request for DPDP-001 was not created: pull requests are switched off on this engine: set DPDP_ALLOW_PR=1 to allow them"
    assert len(responses(slack)) == 2 and st.findings["DPDP-001"].get("pr_url") is None


def test_only_approvers_can_open_a_pull_request():
    ctx, slack, st, pid = listed()
    st.findings["DPDP-001"]["status"] = "fixed"
    rows.row_pr(ctx, OTHER, CHANNEL, pid, "DPDP-001", URL)
    assert st.pr_calls == [] and responses(slack) == [] and "Not allowed" in json.dumps(slack.of("ephemeral"))
    rows.row_pr(ctx, APPROVER, "C_ELSEWHERE", pid, "DPDP-001", URL)  # a channel that does not take commands
    assert st.pr_calls == []


def test_details_show_the_button_or_the_link():
    ctx, slack, st, pid = listed()
    st.findings["DPDP-001"]["status"] = "fixed"
    rows.row_details(ctx, APPROVER, CHANNEL, "DPDP-001", URL)
    assert "dpdp_row_pr" in json.dumps(responses(slack)[0]["blocks"])
    rec = ctx.engine.finding("DPDP-001")
    rec["pr_url"] = "https://github.com/acme/tutornest/pull/9"
    blocks = cards.details(rec, "http://d", False, True)[1]
    assert "dpdp_row_pr" not in json.dumps(blocks) and "Pull request: <https://github.com/acme/tutornest/pull/9|" in json.dumps(blocks)


def test_no_token_or_personal_data_in_any_pr_payload():
    import re
    from slackbot_fakes import PII
    ctx, slack, st, pid = listed()
    st.findings["DPDP-001"]["status"] = "fixed"
    rows.row_pr(ctx, APPROVER, CHANNEL, pid, "DPDP-001", URL)
    text = json.dumps([{k: v for k, v in r.items() if k != "url"} for r in responses(slack)]) + slack.texts().replace(URL, "")
    assert not re.search(r"ghs_|eyJ|xoxb-|secretpart", text) and not PII.search(text)
