"""Block 08: the Slack side of the GitHub App flow, against the fake Slack client and the fake engine (no network, no real Slack)."""
import json

import pytest
from slack_bolt import BoltRequest

from dpdp_lens.slackbot import actions, commands
from dpdp_lens.slackbot.api import EngineError
from dpdp_lens.slackbot.outbox import Poller
from slackbot_fakes import APPROVER, CHANNEL, OTHER, PII, FakeSlack, make_ctx, stop_servers
from test_slackbot_bolt import action, command, wait_for, wired  # noqa: F401  (the Bolt fixture and payload builders)

INSTALL = {"installation_id": 1, "account_login": "octo", "account_type": "User", "created_at": "t"}
REPOS = [{"full_name": "acme/tutornest", "private": True, "default_branch": "main"}, {"full_name": "acme/other", "private": False, "default_branch": "main"}]


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
        return json.dumps(self.sent, ensure_ascii=False)


def run(ctx, text, user=APPROVER):
    reply = Reply()
    commands.run_command(ctx, text, user, CHANNEL, reply)
    return reply


def with_install(repos=REPOS):
    ctx, slack, st = make_ctx()
    st.installs, st.gh_repos = [INSTALL], {1: repos}
    return ctx, slack, st


def elements(reply):
    return [e for _, blocks in reply.sent for b in blocks or [] if b["type"] == "actions" for e in b["elements"]]


# ---- /dpdp connect with no argument

def test_connect_with_no_installation_offers_a_link_button_and_posts_no_secret():
    ctx, slack, st = make_ctx()
    st.installs = []
    r = run(ctx, "connect")
    (button,) = elements(r)
    assert button["type"] == "button" and button["url"] == ctx.cfg.engine_url + "/github/connect" and button["text"]["text"] == "Connect GitHub"
    assert "state" not in r.text.lower() and "eyJ" not in r.text and "ghs_" not in r.text  # the signed state is made when the link is clicked
    assert slack.calls == [] and st.connect_calls == []


def test_connect_with_no_argument_is_for_approvers_only():
    ctx, slack, st = with_install()
    r = run(ctx, "connect", user=OTHER)
    assert "Not allowed" in r.text and elements(r) == []


def test_connect_with_no_argument_when_the_engine_has_no_app_says_so():
    ctx, slack, st = make_ctx()  # st.installs is None: the fake answers 503 like the engine
    assert "GitHub App is not set up" in run(ctx, "connect").text


def test_connect_lists_the_shared_repos_and_marks_the_connected_ones():
    ctx, slack, st = with_install()
    run(ctx, "connect acme/tutornest")  # connected the old way
    st.connect_calls.clear()
    r = run(ctx, "connect")
    select, button = elements(r)
    assert select["type"] == "static_select" and select["action_id"] == "dpdp_repo_pick" and button["action_id"] == "dpdp_repo_connect"
    assert [(o["text"]["text"], o["value"]) for o in select["options"]] == [("acme/tutornest (connected)", "1|acme/tutornest"), ("acme/other", "1|acme/other")]
    assert r.sent[0][1][1]["block_id"] == "repo_pick"
    assert all("ghs_" not in o["value"] for o in select["options"])


def test_the_picker_holds_at_most_100_options_and_says_so():
    ctx, slack, st = with_install([{"full_name": f"acme/r{n:03d}", "private": True, "default_branch": "main"} for n in range(150)])
    r = run(ctx, "connect")
    assert len(elements(r)[0]["options"]) == 100 and "showing 100 of 150" in r.sent[0][0]


def test_an_app_that_shares_nothing_says_so():
    ctx, slack, st = with_install([])
    assert "shares no repository" in run(ctx, "connect").text


def test_connect_with_a_repo_name_works_as_before_and_names_no_installation():
    ctx, slack, st = with_install()
    run(ctx, "connect acme/tutornest main")
    assert st.connect_calls == [{"full_name": "acme/tutornest", "branch": "main", "slack_channel": CHANNEL, "actor": APPROVER}]
    assert slack.of("post")[0]["text"] == "Scanning acme/tutornest (static checks only)" and len(st.findings) == 3


# ---- the Connect button

def test_picking_a_repo_connects_it_with_its_installation_and_scans_like_connect():
    ctx, slack, st = with_install()
    reply = Reply()
    actions.connect_picked(ctx, APPROVER, CHANNEL, "1|acme/other", reply)
    assert st.connect_calls[0]["installation_id"] == 1 and st.connect_calls[0]["full_name"] == "acme/other"
    assert "Connecting acme/other" in reply.text
    assert slack.of("post")[0]["text"] == "Scanning acme/other (static checks only)" and len(slack.of("post")) >= 5  # summary and the cards


def test_the_connect_button_needs_an_approver_a_choice_and_an_allowed_channel():
    ctx, slack, st = with_install()
    reply = Reply()
    actions.connect_picked(ctx, OTHER, CHANNEL, "1|acme/other", reply)
    assert st.connect_calls == [] and "Not allowed" in json.dumps(slack.of("ephemeral"))
    actions.connect_picked(ctx, APPROVER, CHANNEL, "", reply)
    assert "Pick a repository first" in reply.text and st.connect_calls == []
    actions.connect_picked(ctx, APPROVER, "C_ELSEWHERE", "1|acme/other", reply)
    assert st.connect_calls == []


def test_an_engine_refusal_is_shown_to_the_person_who_clicked():
    ctx, slack, st = with_install()
    reply = Reply()
    actions.connect_picked(ctx, APPROVER, CHANNEL, "x|acme/other", reply)  # a value that is not an installation id
    assert "Pick a repository first" in reply.text and st.connect_calls == []
    ctx.engine.connect = lambda *a, **k: (_ for _ in ()).throw(EngineError(403, "acme/x is not shared"))
    reply = Reply()
    actions.connect_picked(ctx, APPROVER, CHANNEL, "1|acme/x", reply)
    assert "The engine said: acme/x is not shared" in reply.text


# ---- /dpdp repos

def test_repos_lists_shared_repos_with_connected_status_for_approvers_only():
    ctx, slack, st = with_install()
    run(ctx, "connect acme/tutornest")
    r = run(ctx, "repos")
    assert "acme/tutornest (connected)" in r.text and "• acme/other" in r.text and "(connected)" not in r.text.split("acme/other")[1][:30]
    assert "Not allowed" in run(ctx, "repos", user=OTHER).text


def test_help_mentions_the_new_commands():
    ctx, slack, st = make_ctx()
    text = run(ctx, "help").text
    assert "/dpdp connect`: connect through the GitHub App" in text and "/dpdp repos" in text


# ---- the outbox row after the browser step

def test_github_installed_posts_one_short_message_in_the_channel():
    ctx, slack, st = with_install()
    st.outbox.append({"id": 1, "kind": "github_installed", "human_id": "1", "repo_id": None, "scan_id": ""})
    poller = Poller(ctx)
    poller.cursor = 0
    assert poller.poll_once() == 1
    (post,) = slack.of("post")
    assert post["channel"] == CHANNEL and post["text"] == "GitHub connected: octo, 2 repositories shared" and post.get("blocks") is None
    assert poller.poll_once() == 0 and len(slack.of("post")) == 1  # once


def test_no_slack_payload_holds_a_token_a_key_or_pii():
    ctx, slack, st = with_install()
    st.outbox.append({"id": 1, "kind": "github_installed", "human_id": "1", "repo_id": None, "scan_id": ""})
    poller = Poller(ctx)
    poller.cursor = 0
    poller.poll_once()
    reply = run(ctx, "connect")
    run(ctx, "repos")
    everything = slack.texts() + reply.text
    for secret in ("ghs_", "eyJ", "BEGIN", "xoxb-", "state="):
        assert secret not in everything
    assert not PII.search(everything)


# ---- Bolt wiring

def test_the_connect_button_goes_through_bolt_and_reads_the_select_state(wired):  # noqa: F811
    app, ctx, slack, st, got, url = wired
    st.installs, st.gh_repos = [INSTALL], {1: REPOS}
    assert app.dispatch(command("connect", url=url)).status == 200
    assert wait_for(lambda: got) and got[0]["response_type"] == "ephemeral" and any(b["type"] == "actions" for b in got[0]["blocks"])
    body = action("dpdp_repo_connect").body  # Slack puts the select's state and a response_url in the payload of a button click
    body["state"] = {"values": {"repo_pick": {"dpdp_repo_pick": {"type": "static_select", "selected_option": {"value": "1|acme/other"}}}}}
    body["response_url"] = url + "/resp"
    assert app.dispatch(BoltRequest(mode="socket_mode", body=body)).status == 200
    assert wait_for(lambda: st.connect_calls and len(slack.of("post")) >= 5)
    assert st.connect_calls[0]["installation_id"] == 1 and st.connect_calls[0]["full_name"] == "acme/other"


def test_the_picker_and_link_events_are_acked(wired):  # noqa: F811
    app, ctx, slack, st, got, url = wired
    assert app.dispatch(action("dpdp_repo_pick", type="static_select", selected_option={"value": "1|acme/other"})).status == 200
    assert app.dispatch(action("dpdp_github_link")).status == 200
    assert st.connect_calls == []
