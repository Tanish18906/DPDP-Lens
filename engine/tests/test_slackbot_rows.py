"""Block 12: what the buttons of a /dpdp findings row do (View Details, Change Status, Fix and verify), against the fake Slack client and
fake engine. Rows are answered through response_urls, which the fake Slack client records."""
import json

import pytest

from dpdp_lens.slackbot import actions, cards, commands, rows
from dpdp_lens.slackbot.poster import Poster
from slackbot_fakes import APPROVER, CHANNEL, OTHER, PII, FakeSlack, make_ctx, stop_servers, verified_fix
from test_slackbot_bolt import wired  # noqa: F401  (the Bolt fixture)

URL = "https://hooks.slack.com/actions/T1/111/secretpart"


@pytest.fixture(autouse=True)
def _stop_fake_engines():
    yield
    stop_servers()


class Reply:
    def __init__(self):
        self.sent = []

    def __call__(self, text, blocks=None):
        self.sent.append((text, blocks))


def listed(user=APPROVER):
    """A connected repo with its three cards posted, and one /dpdp findings page open. Returns (ctx, slack, st, pid)."""
    ctx, slack, st = make_ctx()
    commands.run_command(ctx, "connect acme/tutornest", APPROVER, CHANNEL, lambda *a, **k: None)
    r = Reply()
    commands.run_command(ctx, "findings", user, CHANNEL, r)
    pid = next(b["block_id"].split(":")[1] for b in r.sent[0][1] if b["type"] == "actions")
    return ctx, slack, st, pid


def responses(slack):
    return slack.of("respond")


def alltext(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


def row_status_text(blocks, hid):
    """The context line of a row."""
    i = next(i for i, b in enumerate(blocks) if b["type"] == "actions" and b["block_id"].endswith(":" + hid))
    return blocks[i - 1]["elements"][0]["text"]


# ---- View Details

def test_details_from_a_row_is_an_ephemeral_message_with_the_card_content_and_the_fix_button():
    ctx, slack, st, pid = listed()
    rows.row_details(ctx, APPROVER, CHANNEL, "DPDP-001", URL)
    (r,) = responses(slack)
    assert r["url"] == URL and r["replace_original"] is False and r["response_type"] == "ephemeral"
    text = "\n".join(b["text"]["text"] for b in r["blocks"] if b["type"] == "section")
    assert "*DPDP-001: Personal data written to a log*  ·  Static check" in text  # the proof tag
    assert "Signup logs the email and Aadhaar" in text and "_Why high:_ built from scan facts" in text
    assert "• Likely does not meet Act s8(5): reasonable security safeguards" in text
    assert "*Evidence:* seen in code\n```aadhaar XXXX XXXX 1234, email a***@x.com```" in text  # masked, in a code block
    assert "*Recommendation:* Remove the personal data from the log call." in text
    assert [b["type"] for b in r["blocks"]][-2:] == ["actions", "context"]
    button = r["blocks"][-2]["elements"][0]
    assert (button["text"]["text"], button["action_id"], button["value"]) == ("Fix and verify", "dpdp_row_fix", "DPDP-001")
    assert r["blocks"][-1]["elements"][0]["text"] == "<http://dash.test/?finding=DPDP-001|Open in dashboard>"  # a small line at the bottom
    assert "?finding=" not in alltext([b for b in r["blocks"] if b["type"] == "section"])  # never the main action
    assert slack.of("post") and not [c for c in slack.of("post") if c.get("thread_ts")]  # no thread was needed


def test_details_has_no_fix_button_without_a_fix_for_a_non_approver_or_a_repo_that_does_not_allow_it():
    ctx, slack, st, pid = listed()
    rows.row_details(ctx, APPROVER, CHANNEL, "DPDP-002", URL)  # no fix template
    rows.row_details(ctx, OTHER, CHANNEL, "DPDP-001", URL)  # not an approver: may read, may not fix
    assert all(b["type"] != "actions" for r in responses(slack) for b in r["blocks"])
    ctx2, slack2, st2, _ = (lambda c: (c[0], c[1], c[2], None))(make_ctx(fix_repos=()))
    commands.run_command(ctx2, "connect acme/tutornest", APPROVER, CHANNEL, lambda *a, **k: None)
    rows.row_details(ctx2, APPROVER, CHANNEL, "DPDP-001", URL)
    assert all(b["type"] != "actions" for b in responses(slack2)[0]["blocks"])


def test_details_shows_the_fix_result_lines_once_a_fix_was_run():
    rec = {"human_id": "DPDP-001", "severity": "high", "proof": "static", "status": "fixed", "finding": {
        "title": "Personal data written to a log", "explanation": "x", "clauses": [], "evidence": {"summary": "s"},
        "fix": {"verified": True, "rescan_passed": True, "tests_passed": None}}}
    _, blocks = cards.details(rec)
    text = "\n".join(b["text"]["text"] for b in blocks)
    assert ":white_check_mark: *Verified fix*" in text and "App tests: not run" in text
    assert "*Verified:* the re-scan of the fixed sandbox copy no longer finds this (passed)" in text and "*Not verified, you still must:* your repository itself was not changed" in text
    rec["status"], rec["finding"]["fix"] = "open", {"verified": False, "rescan_passed": False, "tests_passed": False}
    text = "\n".join(b["text"]["text"] for b in cards.details(rec)[1])
    assert ":x: *Not verified*" in text and "*Not verified:* the fix did not pass" in text and "Verified fix" not in text
    rec["finding"]["fix"] = {}
    assert "Not verified" not in "\n".join(b["text"]["text"] for b in cards.details(rec)[1])  # no fix was run: no fix lines


def test_the_thread_reply_of_a_public_card_keeps_working_and_carries_the_small_dashboard_line():
    ctx, slack, st, pid = listed()
    ts = st.findings["DPDP-001"]["slack"]["ts"]
    actions.view_details(ctx, OTHER, CHANNEL, ts, "DPDP-001")
    reply = slack.of("post")[-1]
    assert reply["thread_ts"] == ts and reply["blocks"][-1]["type"] == "context" and "Open in dashboard" in alltext(reply["blocks"][-1])
    assert "?finding=" not in alltext(st.record(st.findings["DPDP-001"])["location"]) and "dpdp_row_fix" not in alltext(reply["blocks"])
    card = slack.of("post")[2]
    assert "<http" not in card["blocks"][0]["text"]["text"]  # block 12: the card's id is plain text


# ---- Change Status

def test_change_status_from_a_row_updates_the_row_the_public_card_and_the_engine():
    ctx, slack, st, pid = listed()
    card_ts = st.findings["DPDP-001"]["slack"]["ts"]
    rows.row_status(ctx, APPROVER, CHANNEL, pid, "DPDP-001|in_progress", "trig", lambda **k: pytest.fail("no modal for in progress"), URL)
    assert st.status_calls == [{"status": "in_progress", "reason": "", "actor": APPROVER}] and st.findings["DPDP-001"]["status"] == "in_progress"
    (r,) = responses(slack)
    assert r["replace_original"] is True and r["url"] == URL
    assert "Status: *In Progress*" in row_status_text(r["blocks"], "DPDP-001") and "Status: *Open*" in row_status_text(r["blocks"], "DPDP-002")
    sel = next(b for b in r["blocks"] if b["type"] == "actions" and b["block_id"].endswith("DPDP-001"))["elements"][1]
    assert sel["initial_option"]["value"] == "DPDP-001|in_progress"
    (upd,) = [c for c in slack.of("update") if c["ts"] == card_ts]  # the public card follows
    assert "Status: *In Progress*" in upd["blocks"][0]["text"]["text"]


def test_false_positive_from_a_row_asks_for_a_reason_then_updates_row_and_card():
    ctx, slack, st, pid = listed()
    opened = []
    rows.row_status(ctx, APPROVER, CHANNEL, pid, "DPDP-002|false_positive", "trig", lambda **k: opened.append(k), URL)
    assert st.status_calls == [] and opened[0]["view"]["callback_id"] == "dpdp_reason" and opened[0]["trigger_id"] == "trig"
    meta = opened[0]["view"]["private_metadata"]
    assert actions.submit_reason(ctx, APPROVER, meta, "   ") == "Give a reason of 1 to 300 characters."  # a reason is required
    assert actions.submit_reason(ctx, APPROVER, meta, "x" * 301) == "Give a reason of 1 to 300 characters."
    assert st.status_calls == [] and responses(slack) == []
    assert actions.submit_reason(ctx, APPROVER, meta, "test data only") is None
    assert st.findings["DPDP-002"]["status"] == "false_positive" and st.findings["DPDP-002"]["reason"] == "test data only"
    (r,) = responses(slack)
    assert r["replace_original"] is True and r["url"] == URL and "Status: *False Positive* (suppressed)" in row_status_text(r["blocks"], "DPDP-002")
    assert [c for c in slack.of("update") if c["ts"] == st.findings["DPDP-002"]["slack"]["ts"]]  # and the card


def test_an_engine_refusal_in_the_reason_is_shown_in_the_modal():
    ctx, slack, st, pid = listed()
    opened = []
    rows.row_status(ctx, APPROVER, CHANNEL, pid, "DPDP-002|wont_fix", "trig", lambda **k: opened.append(k), URL)
    err = actions.submit_reason(ctx, APPROVER, opened[0]["view"]["private_metadata"], "aadhaar 2345 6789 0123")
    assert err and "personal data" in err and responses(slack) == []


def test_a_non_approver_cannot_change_a_status_from_a_row_and_the_row_is_reset():
    ctx, slack, st, pid = listed(OTHER)
    rows.row_status(ctx, OTHER, CHANNEL, pid, "DPDP-001|wont_fix", "trig", lambda **k: pytest.fail("no modal"), URL)
    assert st.status_calls == [] and "Not allowed" in alltext(slack.of("ephemeral"))
    (r,) = responses(slack)
    assert r["replace_original"] is True and "Status: *Open*" in row_status_text(r["blocks"], "DPDP-001")  # the select is put back


def test_a_row_of_an_old_page_says_so_instead_of_failing():
    ctx, slack, st, pid = listed()
    rows.row_status(ctx, APPROVER, CHANNEL, "deadbeef", "DPDP-001|in_progress", "trig", lambda **k: None, URL)
    assert st.findings["DPDP-001"]["status"] == "in_progress" and "out of date" in responses(slack)[0]["text"]


# ---- Fix and verify

def test_fix_from_a_row_shows_progress_then_the_engines_verified_result_and_updates_row_and_card():
    ctx, slack, st, pid = listed()
    rows.row_fix(ctx, APPROVER, CHANNEL, pid, "DPDP-001", URL)
    first, result, replaced = responses(slack)
    assert first["text"] == "Fixing DPDP-001 in a sandbox copy, up to 90 seconds. The repo itself is not changed." and first["replace_original"] is False
    text = result["blocks"][0]["text"]["text"]
    assert text.startswith(":white_check_mark: *DPDP-001: VERIFIED by a live sandbox run*") and "Re-scan of the fixed copy: passed · App tests: passed" in text
    assert "Score 13 to 31" in text and "Status is now *Fixed*." in text and "*Not verified, you still must:*" in text and "*Verified:*" in text
    assert "```--- a/main.py\n+++ b/main.py\n-    logger.info(aadhaar)\n+    logger.info('signup')```" in result["blocks"][1]["text"]["text"]
    assert replaced["replace_original"] is True and "Status: *Fixed*" in row_status_text(replaced["blocks"], "DPDP-001")
    row = next(b for b in replaced["blocks"] if b["type"] == "actions" and b["block_id"].endswith("DPDP-001"))
    assert "dpdp_row_fix" not in [e["action_id"] for e in row["elements"]]
    assert st.fix_calls[0][0] == "DPDP-001" and st.fix_calls[0][2] == {"actor": APPROVER}
    assert [c for c in slack.of("update") if "Status: *Fixed*" in c["blocks"][0]["text"]["text"]]  # the public card too
    assert len(responses(slack)) <= 5  # a response_url allows five answers


def test_a_cached_replay_is_labelled_and_a_fallback_reason_is_shown():
    ctx, slack, st, pid = listed()
    st.fix_response = verified_fix(mode="cached_golden", fallback="no network")
    rows.row_fix(ctx, APPROVER, CHANNEL, pid, "DPDP-001", URL)
    text = responses(slack)[1]["blocks"][0]["text"]["text"]
    assert "Cached verified patch (replay) (the live run could not start: no network)" in text and "VERIFIED by a live" not in text


def test_not_verified_is_never_called_verified_and_the_row_stays_open():
    ctx, slack, st, pid = listed()
    st.fix_response = verified_fix(verified=False, rescan=False, tests=False)
    rows.row_fix(ctx, APPROVER, CHANNEL, pid, "DPDP-001", URL)
    result = responses(slack)[1]["blocks"][0]["text"]["text"]
    assert ":x: *DPDP-001: Not verified*" in result and "VERIFIED" not in result and "Re-scan of the fixed copy: failed · App tests: failed" in result
    assert "*Not verified:* the fix did not pass" in result and "Status is now *Open*." in result
    assert st.findings["DPDP-001"]["status"] == "open"
    # a verified flag with a status that is not verified_fixed is also not verified
    ctx2, slack2, st2, pid2 = listed()
    odd = verified_fix()
    odd["finding"]["status"] = "open"
    st2.fix_response = odd
    rows.row_fix(ctx2, APPROVER, CHANNEL, pid2, "DPDP-001", URL)
    assert "Not verified" in responses(slack2)[1]["blocks"][0]["text"]["text"]


def test_a_long_diff_is_trimmed_to_whole_lines_with_a_note():
    ctx, slack, st, pid = listed()
    body = [f"+    line number {i:03d} " + "x" * 40 for i in range(120)]
    st.fix_response = verified_fix()
    st.fix_response["finding"]["fix"]["diff"] = "\n".join(body)
    rows.row_fix(ctx, APPROVER, CHANNEL, pid, "DPDP-001", URL)
    section = responses(slack)[1]["blocks"][1]["text"]["text"]
    shown = section.split("```")[1].split("\n")
    assert len(section) <= 3000 and shown and all(line in body for line in shown)  # only whole, unchanged lines
    assert f"{120 - len(shown)} more lines not shown" in section
    assert cards.whole_lines("a\n" + "b" * 50, 10) == ("a", 1)  # a line that does not fit is left out, not cut


def test_fix_is_for_approvers_and_an_engine_error_is_shown_to_the_person_who_clicked():
    ctx, slack, st, pid = listed(OTHER)
    rows.row_fix(ctx, OTHER, CHANNEL, pid, "DPDP-001", URL)
    assert st.fix_calls == [] and responses(slack) == [] and "Not allowed" in alltext(slack.of("ephemeral"))
    st.fix_error = (403, "acme/tutornest is not in DPDP_FIX_REPOS, so its code is never run")
    rows.row_fix(ctx, APPROVER, CHANNEL, pid, "DPDP-001", URL)
    assert "Not verified. The fix did not run: acme/tutornest is not in DPDP_FIX_REPOS" in responses(slack)[-1]["text"]
    assert st.findings["DPDP-001"]["status"] == "open"


def test_fix_from_a_details_message_shows_the_result_and_replaces_the_details():
    ctx, slack, st, pid = listed()
    rows.row_details(ctx, APPROVER, CHANNEL, "DPDP-001", URL)
    rows.row_fix(ctx, APPROVER, CHANNEL, "", "DPDP-001", URL + "2")
    first, result, replaced = responses(slack)[1:]
    assert "Fixing DPDP-001" in first["text"] and "VERIFIED by a live sandbox run" in result["text"] and replaced["replace_original"] is True
    assert [c for c in slack.of("update") if "Status: *Fixed*" in c["blocks"][0]["text"]["text"]]


# ---- redaction and retry

def test_every_payload_of_the_row_flows_is_free_of_tokens_urls_and_personal_data():
    ctx, slack, st, pid = listed()
    rows.row_details(ctx, APPROVER, CHANNEL, "DPDP-001", URL)
    rows.row_status(ctx, APPROVER, CHANNEL, pid, "DPDP-001|in_progress", "t", lambda **k: None, URL)
    rows.row_fix(ctx, APPROVER, CHANNEL, pid, "DPDP-003", URL)
    payloads = alltext([{k: v for k, v in r.items() if k != "url"} for r in responses(slack)]) + slack.texts().replace(URL, "")
    for secret in ("xoxb-", "ghs_", "eyJ", "hooks.slack.com", "secretpart"):
        assert secret not in payloads
    assert not PII.search(payloads)


def test_a_429_on_a_response_url_is_retried_after_retry_after():
    slack, waits = FakeSlack(), []
    poster = Poster(slack, interval=0, sleep=waits.append, webhook=slack.webhook)
    slack.fail_webhook = [429, 429]
    poster.respond(URL, "hello", replace=True)
    assert waits == [1.0, 1.0] and responses(slack)[0]["text"] == "hello" and len(responses(slack)) == 1
    slack.fail_webhook = [500]
    with pytest.raises(RuntimeError):
        poster.respond(URL, "boom")


def test_the_response_url_is_redacted_from_logs_and_errors():
    from dpdp_lens.slackbot.redact import redact
    assert "hooks.slack.com" not in redact(f"failed for {URL} twice") and "secretpart" not in redact(f"failed for {URL} twice")


# ---- Bolt wiring: the real listeners, a real response_url (a local sink)

def _bolt_click(url, action_id, block_id, user=APPROVER, **extra):
    from slack_bolt import BoltRequest
    return BoltRequest(mode="socket_mode", body={
        "type": "block_actions", "user": {"id": user}, "team": {"id": "T1"}, "channel": {"id": CHANNEL}, "trigger_id": "trig",
        "container": {"type": "message", "message_ts": "1700000000.000002", "is_ephemeral": True}, "response_url": url + "/resp",
        "actions": [{"action_id": action_id, "block_id": block_id, "type": "button", **extra}]})


def test_the_row_buttons_are_wired_through_bolt(wired):
    from test_slackbot_bolt import command, wait_for
    app, ctx, slack, st, got, url = wired
    app.dispatch(command("connect acme/tutornest", url=url))
    assert wait_for(lambda: len(slack.of("post")) >= 5)
    app.dispatch(command("findings", url=url))
    assert wait_for(lambda: got and any(b["type"] == "actions" for b in got[-1]["blocks"]))
    page = got[-1]
    block_id = next(b["block_id"] for b in page["blocks"] if b["type"] == "actions")
    hid = block_id.split(":")[2]
    got.clear()
    assert app.dispatch(_bolt_click(url, "dpdp_row_details", block_id, value=hid)).status == 200
    assert wait_for(lambda: got) and got[0]["response_type"] == "ephemeral" and "Open in dashboard" in alltext(got[0]["blocks"])
    got.clear()
    sel = _bolt_click(url, "dpdp_row_status", block_id, type="static_select", selected_option={"value": f"{hid}|in_progress"})
    assert app.dispatch(sel).status == 200
    assert wait_for(lambda: st.status_calls and got) and st.status_calls[0]["actor"] == APPROVER and got[0].get("replace_original") is True
    got.clear()
    fixable = next(h for h, f in st.findings.items() if f["fix"])
    assert app.dispatch(_bolt_click(url, "dpdp_row_fix", block_id, value=fixable)).status == 200
    assert wait_for(lambda: len(got) >= 2) and "Fixing" in got[0]["text"] and st.fix_calls and st.fix_calls[0][0] == fixable
