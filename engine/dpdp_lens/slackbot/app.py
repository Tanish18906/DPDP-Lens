"""Bolt wiring (Socket Mode, no public URL). Every listener acks first, then does its work, so Slack's 3 second limit holds.
The logic is in commands.py, actions.py and outbox.py. This file only translates Slack payloads into plain arguments."""
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from . import actions, commands
from .api import Engine
from .config import Config
from .flow import Ctx
from .outbox import Poller
from .poster import Poster
from .redact import install_log_filter, redact

log = logging.getLogger("dpdp_lens.slackbot")


def register(app, ctx: Ctx, pool: ThreadPoolExecutor) -> None:
    def safe(fn, *a):
        try:
            fn(*a)
        except Exception as e:  # a handler must never kill the pool thread silently
            log.warning("%s failed: %s: %s", getattr(fn, "__name__", fn), type(e).__name__, redact(e))

    def where(body) -> tuple[str, str]:
        return body["channel"]["id"], (body.get("message") or body.get("container") or {}).get("ts", "")

    @app.command("/dpdp")
    def on_command(ack, command, respond):
        ack()
        reply = lambda text, blocks=None: respond(text=text, blocks=blocks, response_type="ephemeral")  # noqa: E731
        pool.submit(safe, commands.run_command, ctx, command.get("text", ""), command["user_id"], command["channel_id"], reply)

    @app.action("dpdp_details")
    def on_details(ack, body, action):
        ack()
        channel, ts = where(body)
        pool.submit(safe, actions.view_details, ctx, body["user"]["id"], channel, ts, action["value"])

    @app.action("dpdp_status")
    def on_status(ack, body, action, client):
        ack()
        channel, ts = where(body)
        actions.change_status(ctx, body["user"]["id"], channel, ts, action["selected_option"]["value"], body["trigger_id"], client.views_open)

    @app.action("dpdp_fix")
    def on_fix(ack, body, action):
        ack()
        channel, ts = where(body)
        pool.submit(safe, actions.fix_and_verify, ctx, body["user"]["id"], channel, ts, action["value"])

    @app.view("dpdp_reason")
    def on_reason(ack, body, view):
        text = view["state"]["values"]["reason"]["text"]["value"]
        error = actions.submit_reason(ctx, body["user"]["id"], view["private_metadata"], text)  # before the ack, so the modal can show the error
        ack(response_action="errors", errors={"reason": error}) if error else ack()


def build(cfg: Config, app=None, engine: Engine | None = None, slack=None) -> tuple:
    """Returns (bolt app, ctx). The arguments are for tests."""
    from slack_bolt import App
    app = app or App(token=cfg.bot_token)
    ctx = Ctx(cfg, engine or Engine(cfg.engine_url, cfg.api_token), slack or app.client, Poster(slack or app.client))
    register(app, ctx, ThreadPoolExecutor(max_workers=8, thread_name_prefix="dpdp-bot"))
    return app, ctx


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    install_log_filter()
    cfg = Config.from_env()
    if missing := cfg.missing():
        print("Missing environment: " + ", ".join(missing), file=sys.stderr)
        return 2
    from slack_bolt.adapter.socket_mode import SocketModeHandler
    app, ctx = build(cfg)
    stop = threading.Event()
    threading.Thread(target=Poller(ctx).run, args=(stop,), name="dpdp-outbox", daemon=True).start()
    try:
        SocketModeHandler(app, cfg.app_token).start()
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
