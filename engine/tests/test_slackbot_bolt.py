"""Block 03: the Bolt wiring. Real slack_bolt App, payloads dispatched by hand (no Slack, no network), fake engine on a local port."""
import json
import time

import pytest
from fastapi import Body, FastAPI
from slack_bolt import App, BoltRequest
from slack_bolt.authorization import AuthorizeResult

from dpdp_lens.slackbot import app as bot
from dpdp_lens.slackbot.api import Engine
from dpdp_lens.slackbot.config import Config
from slackbot_fakes import APPROVER, CHANNEL, OTHER, TOKEN, FakeSlack, make_engine_app, serve, stop_servers


@pytest.fixture(autouse=True)
def _stop_servers():
    yield
    stop_servers()


def wait_for(cond, seconds=5):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def wired():
    """Bolt app + ctx on the fake engine, plus a local URL that stands in for Slack's response_url."""
    sink = FastAPI()
    got: list = []

    @sink.post("/resp")
    def resp(body: dict = Body(...)):
        got.append(body)
        return "ok"

    sink_url = serve(sink)
    engine_app, st = make_engine_app()
    cfg = Config(engine_url=serve(engine_app), dashboard_url="http://dash.test", api_token=TOKEN, channel=CHANNEL,
                 allowed_channels=frozenset({CHANNEL}), approvers=frozenset({APPROVER}), fix_repos=frozenset({"acme/tutornest"}))
    slack = FakeSlack()
    authorize = lambda **kw: AuthorizeResult(enterprise_id=None, team_id="T1", bot_token="xoxb-test", bot_id="B1", bot_user_id="UBOT")  # noqa: E731
    bolt = App(authorize=authorize, request_verification_enabled=False, token_verification_enabled=False)
    app, ctx = bot.build(cfg, app=bolt, engine=Engine(cfg.engine_url, TOKEN), slack=slack)
    return app, ctx, slack, st, got, sink_url


def command(text, user=APPROVER, channel=CHANNEL, url=""):
    return BoltRequest(mode="socket_mode", body={"command": "/dpdp", "text": text, "user_id": user, "channel_id": channel, "team_id": "T1",
                                                 "trigger_id": "trig", "response_url": url + "/resp"})


def test_slash_command_is_acked_at_once_and_answered_ephemeral(wired):
    app, ctx, slack, st, got, url = wired
    res = app.dispatch(command("help", url=url))
    assert res.status == 200
    assert wait_for(lambda: got) and got[0]["response_type"] == "ephemeral" and "/dpdp connect" in got[0]["text"]


def test_slash_command_connect_runs_the_whole_flow_through_bolt(wired):
    app, ctx, slack, st, got, url = wired
    assert app.dispatch(command("connect acme/tutornest", url=url)).status == 200
    assert wait_for(lambda: len(slack.of("post")) >= 5)
    assert slack.of("post")[0]["text"] == "Scanning acme/tutornest (static checks only)" and len(st.findings) == 3


def action(action_id, **extra):
    return BoltRequest(mode="socket_mode", body={
        "type": "block_actions", "user": {"id": extra.pop("user", APPROVER)}, "team": {"id": "T1"}, "channel": {"id": CHANNEL}, "trigger_id": "trig",
        "container": {"message_ts": "1700000000.000002"}, "message": {"ts": "1700000000.000002"},
        "actions": [{"action_id": action_id, "block_id": "b", "type": "button", **extra}]})


def test_status_select_and_details_button_go_through_bolt(wired):
    app, ctx, slack, st, got, url = wired
    app.dispatch(command("connect acme/tutornest", url=url))
    assert wait_for(lambda: len(slack.of("post")) >= 5)
    ts = st.findings["DPDP-001"]["slack"]["ts"]
    sel = action("dpdp_status", type="static_select", selected_option={"value": "DPDP-001|in_progress"})
    sel.body["message"]["ts"] = sel.body["container"]["message_ts"] = ts
    assert app.dispatch(sel).status == 200
    assert wait_for(lambda: st.status_calls) and st.status_calls[0]["actor"] == APPROVER
    assert wait_for(lambda: slack.of("update"))
    det = action("dpdp_details", value="DPDP-001", user=OTHER)
    assert app.dispatch(det).status == 200
    assert wait_for(lambda: any(p.get("thread_ts") for p in slack.of("post")))


def test_modal_submit_shows_engine_errors_in_the_modal_and_saves_valid_reasons(wired):
    app, ctx, slack, st, got, url = wired
    app.dispatch(command("connect acme/tutornest", url=url))
    assert wait_for(lambda: len(slack.of("post")) >= 5)
    meta = json.dumps({"h": "DPDP-001", "s": "wont_fix", "c": CHANNEL, "t": st.findings["DPDP-001"]["slack"]["ts"]})

    def submit(text, user=APPROVER):
        return app.dispatch(BoltRequest(mode="socket_mode", body={
            "type": "view_submission", "user": {"id": user}, "team": {"id": "T1"},
            "view": {"type": "modal", "callback_id": "dpdp_reason", "private_metadata": meta, "state": {"values": {"reason": {"text": {"value": text}}}}}}))

    bad = submit("call 9876543210 for details")
    assert json.loads(bad.body)["errors"]["reason"].startswith("the reason must not contain personal data")
    assert st.status_calls == []
    assert json.loads(submit("legacy module, retired").body or "{}") == {} and st.status_calls[0]["reason"] == "legacy module, retired"
    assert "errors" in json.loads(submit("x", user=OTHER).body) and len(st.status_calls) == 1


def test_main_refuses_to_start_without_its_tokens(monkeypatch, capsys):
    for name in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "DPDP_API_TOKEN", "SLACK_CHANNEL", "SLACK_ALLOWED_CHANNELS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret-value")
    assert bot.main() == 2
    err = capsys.readouterr().err
    assert "SLACK_APP_TOKEN" in err and "DPDP_API_TOKEN" in err and "SLACK_CHANNEL" in err and "xoxb-secret-value" not in err


def test_config_reads_the_environment():
    cfg = Config.from_env({"SLACK_CHANNEL": "C9", "SLACK_APPROVERS": "U1, U2", "DPDP_FIX_REPOS": "Acme/Tutornest", "ENGINE_URL": "http://e:1/",
                           "SLACK_BOT_TOKEN": "a", "SLACK_APP_TOKEN": "b", "DPDP_API_TOKEN": "c"})
    assert cfg.allowed_channels == {"C9"} and cfg.approvers == {"U1", "U2"} and cfg.fix_repos == {"acme/tutornest"}
    assert cfg.engine_url == "http://e:1" and cfg.missing() == []
    assert Config.from_env({"SLACK_CHANNEL": "C9", "SLACK_ALLOWED_CHANNELS": "C1,C2"}).allowed_channels == {"C1", "C2"}
    assert "SLACK_CHANNEL" in Config.from_env({}).missing()
