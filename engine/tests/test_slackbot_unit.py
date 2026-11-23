"""Block 03: the Slack bot against a fake Slack client and a small fake engine API (no network, no real Slack)."""
import json
import logging

import pytest
from slack_sdk.errors import SlackApiError

from dpdp_lens.slackbot import actions, cards, commands
from dpdp_lens.slackbot.api import EngineError
from dpdp_lens.slackbot.outbox import Poller
from dpdp_lens.slackbot.poster import Poster
from dpdp_lens.slackbot.redact import RedactFilter, redact
from slackbot_fakes import APPROVER, CHANNEL, OTHER, PII, TOKEN, FakeSlack, make_ctx, stop_servers, verified_fix


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
        return "\n".join(t for t, _ in self.sent)


def connect(ctx, reply=None, text="connect acme/tutornest"):
    reply = reply or Reply()
    commands.run_command(ctx, text, APPROVER, CHANNEL, reply)
    return reply


# ---- redaction

def test_redact_strips_every_token_kind_and_the_api_token(monkeypatch):
    monkeypatch.setenv("DPDP_API_TOKEN", "engine-secret-1234")
    raw = "a xoxb-123-abc b xapp-1-A0-xyz c ghp_abcdefghijkl d github_pat_11AAA_bbb e engine-secret-1234 f"
    out = redact(raw)
    for secret in ("xoxb-", "xapp-", "ghp_", "github_pat_", "engine-secret-1234", "abcdefghijkl"):
        assert secret not in out
    assert out.count("[redacted]") == 5


def test_log_records_are_redacted(monkeypatch, caplog):
    monkeypatch.setenv("DPDP_API_TOKEN", "engine-secret-1234")
    rec = logging.LogRecord("x", logging.WARNING, "f", 1, "bad %s %s", ("xoxb-1-2-3", "engine-secret-1234"), None)
    RedactFilter().filter(rec)
    assert "xoxb" not in rec.getMessage() and "engine-secret" not in rec.getMessage()


def test_engine_errors_shown_in_slack_hide_tokens():
    ctx, slack, st = make_ctx()
    e = EngineError(502, f"clone failed for https://x-access-token:ghp_abcdefghijklmnop@github.com using {TOKEN}")
    assert "ghp_" not in e.detail and TOKEN not in e.detail
    ctx.engine.repos = lambda: (_ for _ in ()).throw(e)
    r = Reply()
    commands.run_command(ctx, "status", APPROVER, CHANNEL, r)
    assert "ghp_" not in r.text and TOKEN not in r.text and "The engine said" in r.text


# ---- poster

def _429(retry_after="2"):
    class R:
        status_code = 429
        headers = {"retry-after": retry_after}
    return SlackApiError("ratelimited", R())


def test_poster_waits_retry_after_on_429_then_succeeds():
    slack, slept = FakeSlack(), []
    slack.fail_next = [_429("3"), _429("1")]
    ts = Poster(slack, interval=0, sleep=slept.append).post(CHANNEL, "hi")
    assert ts.startswith("1700000000.") and slept == [3.0, 1.0] and len(slack.of("post")) == 1


def test_poster_gives_up_after_its_retries_and_other_errors_are_not_retried():
    slack, slept = FakeSlack(), []
    slack.fail_next = [_429()] * 10
    with pytest.raises(SlackApiError):
        Poster(slack, interval=0, sleep=slept.append, retries=2).post(CHANNEL, "hi")
    assert len(slept) == 2

    class Bad:
        status_code, headers = 400, {}
    slack.fail_next = [SlackApiError("bad", Bad())]
    with pytest.raises(SlackApiError):
        Poster(slack, interval=0, sleep=slept.append).post(CHANNEL, "hi")
    assert len(slept) == 2  # no wait for a 400


def test_poster_spaces_posts_in_one_channel_about_one_second_apart():
    now, slept = [100.0], []
    p = Poster(FakeSlack(), interval=1.0, sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)), clock=lambda: now[0])
    p.post("C1", "a")
    p.post("C1", "b")
    p.post("C2", "other channel")
    assert slept == [1.0]


# ---- cards

REC = {"human_id": "DPDP-014", "repo": "acme/tutornest", "branch": "main", "check": "log_pii", "severity": "high", "title": "Personal data in a log",
       "proof": "static", "status": "open", "status_reason": "", "location": {"file": "backend/app/main.py", "line": 87, "url": ""},
       "fix_available": True, "slack": None}


def test_card_snapshot():
    text, blocks = cards.finding_card(REC, "http://dash.test/", can_fix=True)
    assert text == "DPDP-014 HIGH Open: Personal data in a log"
    assert blocks[0]["text"]["text"] == "<http://dash.test/?finding=DPDP-014|DPDP-014>   :large_orange_circle: *HIGH*   ·   Status: *Open*"
    assert blocks[1]["text"]["text"] == "*Personal data in a log*"
    assert [e["text"] for e in blocks[2]["elements"]] == ["`backend/app/main.py:87`", "acme/tutornest@main", "Static check"]
    acts = blocks[3]["elements"]
    assert [a["action_id"] for a in acts] == ["dpdp_details", "dpdp_status", "dpdp_fix"]
    assert [o["text"]["text"] for o in acts[1]["options"]] == ["Open", "In Progress", "False Positive", "Won't Fix"]
    assert acts[1]["initial_option"]["value"] == "DPDP-014|open" and acts[0]["value"] == "DPDP-014"


def test_card_variants():
    probed = {**REC, "proof": "probed", "location": {"file": "", "line": 0, "url": "/api/students"}}
    _, b = cards.finding_card(probed, "http://d", can_fix=False)
    assert b[2]["elements"][0]["text"] == "`/api/students`" and b[2]["elements"][2]["text"] == "Behaviour confirmed by a live request"
    assert [a["action_id"] for a in b[3]["elements"]] == ["dpdp_details", "dpdp_status"]  # repo not in DPDP_FIX_REPOS: no fix button
    fixed = {**REC, "status": "fixed", "status_reason": "verified fix"}
    text, b = cards.finding_card(fixed, "http://d", can_fix=True)
    assert "Status: *Fixed*" in b[0]["text"]["text"] and "Reason: verified fix" in b[2]["elements"][-1]["text"]
    assert [a["action_id"] for a in b[3]["elements"]] == ["dpdp_details", "dpdp_status"] and "initial_option" not in b[3]["elements"][1]
    no_fix = {**REC, "fix_available": False}
    assert "dpdp_fix" not in [a["action_id"] for a in cards.finding_card(no_fix, "http://d", can_fix=True)[1][3]["elements"]]
    odd = {**REC, "title": "a <b> & c"}
    assert "a &lt;b&gt; &amp; c" in cards.finding_card(odd, "http://d", True)[1][1]["text"]["text"]


def test_modal_has_a_required_300_char_reason():
    v = cards.reason_modal("DPDP-014", "false_positive", "meta")
    el = v["blocks"][0]
    assert v["callback_id"] == "dpdp_reason" and el["element"]["max_length"] == 300 and not el.get("optional")


# ---- /dpdp connect, scan, dedup, summary

def test_connect_posts_scanning_summary_and_one_card_per_finding_critical_first():
    ctx, slack, st = make_ctx()
    r = connect(ctx)
    posts = slack.of("post")
    assert posts[0]["text"] == "Scanning acme/tutornest (static checks only)"
    assert "New 3 · Resolved 0" in posts[1]["text"] or "scan S-001 complete" in posts[1]["text"]
    summary_text = json.dumps(posts[1]["blocks"])
    assert "Coverage: static checks only (11 of 19)" in summary_text and "Health: *At risk*" in summary_text
    card_titles = [p["text"] for p in posts[2:]]
    assert [t.split()[0:2] for t in card_titles] == [["DPDP-003", "CRITICAL"], ["DPDP-001", "HIGH"], ["DPDP-002", "MEDIUM"]]
    assert all(f["slack"] for f in st.findings.values()) and r.sent == []  # nothing ephemeral on success
    assert st.findings["DPDP-001"]["slack"]["channel"] == CHANNEL


def test_rescan_does_not_repost_cards_for_unchanged_findings():
    ctx, slack, st = make_ctx()
    connect(ctx)
    n = len(slack.of("post"))
    commands.run_command(ctx, "scan", APPROVER, CHANNEL, Reply())  # repo found from the channel
    new_posts = slack.of("post")[n:]
    assert len(new_posts) == 2 and "Persistent 3" in json.dumps(new_posts[1]["blocks"])  # "Scanning ..." and the summary, no cards


def test_incomplete_scan_is_never_green():
    ctx, slack, st = make_ctx()
    st.complete = False
    st.scan_errors = [{"scanner": "log_scan", "kind": "timeout", "message": "took too long"}]
    st.health = {"status": "healthy", "reasons": [], "last_complete_scan_at": None, "last_scan_status": "incomplete", "counts": {}}  # a wrong engine answer
    connect(ctx)
    summary = slack.of("post")[1]
    assert summary["text"].startswith("*Scan incomplete: results are partial*")
    body = json.dumps(summary["blocks"])
    assert body.index("Scan incomplete: results are partial") < body.index("Health")
    assert "Health: *Unknown*" in body and "white_check_mark" not in body and "Healthy" not in body
    assert "log_scan timeout: took too long" in body


def test_failed_scan_says_failed_and_unknown():
    ctx, slack, st = make_ctx()
    st.scan_fails = True
    connect(ctx)
    ctx.sleep = lambda s: None
    msg = json.dumps(slack.of("post")[-1]["blocks"])
    assert "Scan failed: no results for acme/tutornest" in msg and "RepoError: clone failed" in msg
    assert "Unknown" in json.dumps(slack.of("post")[-1]["blocks"]) and "white_check_mark" not in json.dumps(slack.of("post")[-1]["blocks"])
    assert slack.of("post")[-1]["blocks"] and len(slack.of("post")) == 2  # "Scanning ..." and the failure, no cards


def test_connect_errors_are_answered_ephemeral():
    ctx, slack, st = make_ctx()
    r = connect(ctx, text="connect evil/repo")
    assert "DPDP_ALLOWED_REPOS" in r.text and slack.of("post") == []
    assert "Usage" in connect(ctx, text="connect").text


def test_commands_only_work_in_allowed_channels_and_unknown_gets_help():
    ctx, slack, st = make_ctx()
    r = Reply()
    commands.run_command(ctx, "connect acme/tutornest", APPROVER, "C_OTHER", r)
    assert "does not take commands" in r.text and st.repos == []
    r = Reply()
    commands.run_command(ctx, "", APPROVER, CHANNEL, r)
    assert "/dpdp connect" in r.text and "not a compliance certificate" in r.text
    assert "/dpdp connect" in connect(ctx, text="bogus").text


def test_status_diff_baseline_watch():
    ctx, slack, st = make_ctx()
    connect(ctx)
    r = Reply()
    commands.run_command(ctx, "status", OTHER, CHANNEL, r)
    assert "Health: *At risk*" in r.text and "static checks only (11 of 19)" in r.text and "Open 3" in r.text
    r = Reply()
    commands.run_command(ctx, "diff", OTHER, CHANNEL, r)
    assert "S-001" in r.text
    for sub in ("baseline", "watch 15", "watch off"):  # approvers only
        r = Reply()
        commands.run_command(ctx, sub, OTHER, CHANNEL, r)
        assert "Not allowed" in r.text
    assert st.baseline_calls == [] and st.watch_calls == []
    r = Reply()
    commands.run_command(ctx, "baseline", APPROVER, CHANNEL, r)
    commands.run_command(ctx, "watch 15", APPROVER, CHANNEL, r)
    commands.run_command(ctx, "watch off", APPROVER, CHANNEL, r)
    assert st.baseline_calls == [{"actor": APPROVER}] and [w["minutes"] for w in st.watch_calls] == [15, None]
    assert "not real-time" in r.text and "Usage" in connect(ctx, text="watch soon").text


# ---- details

def test_view_details_replies_in_the_thread_with_clauses_and_masked_evidence():
    ctx, slack, st = make_ctx()
    connect(ctx)
    ts = st.findings["DPDP-001"]["slack"]["ts"]
    actions.view_details(ctx, OTHER, CHANNEL, ts, "DPDP-001")  # anyone in the channel may read
    post = slack.of("post")[-1]
    body = json.dumps(post["blocks"])
    assert post["thread_ts"] == ts and "Likely does not meet Act s8(5)" in body and "XXXX XXXX 1234" in body
    assert "Remove the personal data" in body and "built from scan facts" in body
    actions.view_details(ctx, OTHER, "C_OTHER", ts, "DPDP-001")
    assert len(slack.of("post")) == len([p for p in slack.of("post")])  # outside an allowed channel: nothing more is sent
    n = len(slack.of("post"))
    actions.view_details(ctx, OTHER, "C_OTHER", ts, "DPDP-001")
    assert len(slack.of("post")) == n


# ---- change status

def select(ctx, slack, st, user, status, hid="DPDP-001"):
    ts = st.findings[hid]["slack"]["ts"]
    actions.change_status(ctx, user, CHANNEL, ts, f"{hid}|{status}", "trig", slack.views_open)
    return ts


def test_status_change_without_reason_updates_the_card_and_records_the_actor():
    ctx, slack, st = make_ctx()
    connect(ctx)
    ts = select(ctx, slack, st, APPROVER, "in_progress")
    assert st.status_calls == [{"status": "in_progress", "reason": "", "actor": APPROVER}]
    upd = slack.of("update")[-1]
    assert upd["ts"] == ts and upd["channel"] == CHANNEL and "Status: *In Progress*" in json.dumps(upd["blocks"])


def test_false_positive_opens_a_modal_and_only_the_reason_submit_patches():
    ctx, slack, st = make_ctx()
    connect(ctx)
    select(ctx, slack, st, APPROVER, "false_positive")
    view = slack.of("view")[0]
    assert view["trigger_id"] == "trig" and view["view"]["callback_id"] == "dpdp_reason" and st.status_calls == []
    meta = view["view"]["private_metadata"]
    assert actions.submit_reason(ctx, APPROVER, meta, "   ") == "Give a reason of 1 to 300 characters."
    assert actions.submit_reason(ctx, APPROVER, meta, "x" * 301) == "Give a reason of 1 to 300 characters."
    assert "personal data" in actions.submit_reason(ctx, APPROVER, meta, "aadhaar 2345 6789 0123")  # the engine's 422 goes back into the modal
    assert st.status_calls == []
    assert actions.submit_reason(ctx, APPROVER, meta, "test fixture data") is None
    assert st.status_calls == [{"status": "false_positive", "reason": "test fixture data", "actor": APPROVER}]
    assert "Reason: test fixture data" in json.dumps(slack.of("update")[-1]["blocks"])
    assert actions.submit_reason(ctx, OTHER, meta, "sneaky") == actions.NOT_ALLOWED and len(st.status_calls) == 1  # the submit is gated too


def test_non_approver_cannot_change_status_and_card_is_reset():
    ctx, slack, st = make_ctx()
    connect(ctx)
    select(ctx, slack, st, OTHER, "wont_fix")
    assert st.status_calls == [] and slack.of("view") == []
    eph = slack.of("ephemeral")[0]
    assert eph["user"] == OTHER and "Not allowed" in eph["text"]
    assert "Status: *Open*" in json.dumps(slack.of("update")[-1]["blocks"])  # the select is put back


# ---- fix and verify

def test_fix_verified_live_shows_verified_diff_and_fixed_card():
    ctx, slack, st = make_ctx()
    connect(ctx)
    ts = st.findings["DPDP-001"]["slack"]["ts"]
    actions.fix_and_verify(ctx, APPROVER, CHANNEL, ts, "DPDP-001")
    threads = [p for p in slack.of("post") if p.get("thread_ts") == ts]
    assert threads[0]["text"] == "Fixing DPDP-001 in a sandbox copy. The repo itself is not changed."
    assert "VERIFIED by a live sandbox run" in threads[1]["text"] and "Re-scan of the fixed copy: passed · App tests: passed" in threads[1]["text"]
    assert "Score 13 to 31" in threads[1]["text"] and "logger.info('signup')" in json.dumps(threads[2]["blocks"]) and "```" in json.dumps(threads[2]["blocks"])
    assert st.fix_calls == [("DPDP-001", "live", {"actor": APPROVER})]
    assert "Status: *Fixed*" in json.dumps(slack.of("update")[-1]["blocks"])


def test_fix_cached_is_labelled_a_replay():
    ctx, slack, st = make_ctx()
    connect(ctx)
    st.fix_response = verified_fix(mode="cached_golden", fallback="RuntimeError: seed failed")
    actions.fix_and_verify(ctx, APPROVER, CHANNEL, st.findings["DPDP-001"]["slack"]["ts"], "DPDP-001")
    text = slack.of("post")[-2]["text"]
    assert "Cached verified patch (replay)" in text and "seed failed" in text and "VERIFIED" not in text


def test_fix_not_verified_never_says_verified():
    ctx, slack, st = make_ctx()
    connect(ctx)
    ts = st.findings["DPDP-001"]["slack"]["ts"]
    st.fix_response = verified_fix(verified=False, rescan=True, tests=False)
    actions.fix_and_verify(ctx, APPROVER, CHANNEL, ts, "DPDP-001")
    reply = [p for p in slack.of("post") if p.get("thread_ts") == ts][1]
    assert "Not verified" in reply["text"] and "App tests: failed" in reply["text"] and "VERIFIED" not in reply["text"] and "Verified" not in reply["text"]
    assert "Status: *Fixed*" not in json.dumps(slack.of("update")[-1]["blocks"]) if slack.of("update") else True
    st.fix_error = (403, "acme/tutornest is not in DPDP_FIX_REPOS, so its code is never run")
    actions.fix_and_verify(ctx, APPROVER, CHANNEL, ts, "DPDP-001")
    last = slack.of("post")[-1]["text"]
    assert last.startswith("Not verified. The fix did not run:") and "DPDP_FIX_REPOS" in last


def test_a_verified_flag_with_a_wrong_status_is_not_trusted():
    ctx, slack, st = make_ctx()
    connect(ctx)
    out = verified_fix()
    out["finding"]["status"] = "open"  # the engine says verified but did not mark it fixed: be careful, say nothing positive
    st.fix_response = out
    actions.fix_and_verify(ctx, APPROVER, CHANNEL, st.findings["DPDP-001"]["slack"]["ts"], "DPDP-001")
    assert "Not verified" in slack.of("post")[-2]["text"]


def test_non_approver_cannot_fix():
    ctx, slack, st = make_ctx()
    connect(ctx)
    actions.fix_and_verify(ctx, OTHER, CHANNEL, "1.1", "DPDP-001")
    assert st.fix_calls == [] and "Not allowed" in slack.of("ephemeral")[0]["text"]


def test_fix_button_only_for_fix_repos():
    ctx, slack, st = make_ctx(fix_repos=())
    connect(ctx)
    cards_posted = slack.of("post")[2:]
    assert all("dpdp_fix" not in json.dumps(p["blocks"]) for p in cards_posted)
    ctx2, slack2, _ = make_ctx()
    connect(ctx2)
    assert sum("dpdp_fix" in json.dumps(p["blocks"]) for p in slack2.of("post")[2:]) == 2  # log_pii and api_pii_exposure, not the config one


# ---- outbox

def test_outbox_updates_cards_and_ignores_unknown_kinds_and_old_rows():
    ctx, slack, st = make_ctx()
    connect(ctx)
    st.outbox.append({"id": 1, "kind": "status_changed", "human_id": "DPDP-001", "repo_id": None, "scan_id": ""})
    poller = Poller(ctx)
    assert poller.poll_once() == 0 and poller.cursor == 1 and slack.of("update") == []  # first poll only finds the end
    st.findings["DPDP-001"]["status"] = "wont_fix"  # changed in the dashboard
    st.outbox += [{"id": 2, "kind": "something_new", "human_id": "", "repo_id": 1, "scan_id": "S-9"},
                  {"id": 3, "kind": "status_changed", "human_id": "DPDP-001", "repo_id": None, "scan_id": ""},
                  {"id": 4, "kind": "status_changed", "human_id": "DPDP-404", "repo_id": None, "scan_id": ""}]  # 404: logged and skipped
    assert poller.poll_once() == 1 and poller.cursor == 4
    upd = slack.of("update")
    assert len(upd) == 1 and "Status: *Won't Fix*" in json.dumps(upd[0]["blocks"])
    assert poller.poll_once() == 0


def test_outbox_row_without_a_card_changes_nothing():
    ctx, slack, st = make_ctx()
    connect(ctx)
    st.findings["DPDP-002"]["slack"] = None
    poller = Poller(ctx)
    poller.poll_once()
    st.outbox.append({"id": 1, "kind": "status_changed", "human_id": "DPDP-002", "repo_id": None, "scan_id": ""})
    assert poller.poll_once() == 1 and slack.of("update") == []


def test_health_changed_alerts_once_and_again_only_after_recovery():
    ctx, slack, st = make_ctx()
    connect(ctx)
    poller = Poller(ctx)
    poller.poll_once()
    n = len(slack.of("post"))
    row = lambda i: st.outbox.append({"id": i, "kind": "health_changed", "human_id": "", "repo_id": 1, "scan_id": ""})  # noqa: E731
    st.health = {"status": "unknown", "reasons": ["latest scan S-002 is incomplete"], "counts": {}}
    row(1), row(2)
    poller.poll_once()
    alerts = slack.of("post")[n:]
    assert len(alerts) == 1 and "health is Unknown" in alerts[0]["text"] and "not a pass" in json.dumps(alerts[0]["blocks"])
    st.health = {"status": "at_risk", "reasons": ["1 blocking finding(s) open"], "counts": {}}
    row(3)
    poller.poll_once()
    assert len(slack.of("post")) == n + 1  # still bad: no second alert
    st.health = {"status": "healthy", "reasons": [], "counts": {}}
    row(4)
    poller.poll_once()
    assert "recovered, now Healthy" in slack.of("post")[-1]["text"] and len(slack.of("post")) == n + 2
    st.health = {"status": "unknown", "reasons": ["x"], "counts": {}}
    row(5)
    poller.poll_once()
    assert len(slack.of("post")) == n + 3  # a new alert after the recovery


def test_scan_delta_row_posts_a_summary_and_cards_for_new_findings():
    ctx, slack, st = make_ctx()
    connect(ctx)
    poller = Poller(ctx)
    poller.poll_once()
    st.findings["DPDP-009"] = {**st.findings["DPDP-001"], "human_id": "DPDP-009", "slack": None, "title": "Brand new"}
    st.scans["S-002"] = {"id": "S-002", "repo": 1, "failed": False, "new": ["DPDP-009"], "persistent": 3, "complete": True}
    n = len(slack.of("post"))
    st.outbox.append({"id": 1, "kind": "scan_delta", "human_id": "", "repo_id": 1, "scan_id": "S-002"})
    assert poller.poll_once() == 1
    posts = slack.of("post")[n:]
    assert len(posts) == 2 and posts[0]["channel"] == CHANNEL and "DPDP-009" in posts[1]["text"]


# ---- no raw PII in anything the bot sends

def test_no_raw_pii_in_any_slack_payload():
    ctx, slack, st = make_ctx()
    connect(ctx)
    ts = st.findings["DPDP-001"]["slack"]["ts"]
    for hid in st.findings:
        actions.view_details(ctx, APPROVER, CHANNEL, ts, hid)
    actions.fix_and_verify(ctx, APPROVER, CHANNEL, ts, "DPDP-001")
    payload = slack.texts()
    assert len(slack.calls) > 10 and not PII.findall(payload)
    assert "XXXX XXXX 1234" in payload  # the masked form is what is shown
    assert PII.search("aadhaar 2345 6789 0123") and PII.search("PAN ABCDE1234F") and PII.search("call 9876543210")  # the check itself works
