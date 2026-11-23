"""Block 03: the same flow against the REAL engine (api.py + api_v2.py, a real SQLite store) on port 8200, with a local bare git repo of
TutorNest as the "GitHub". Slack is still the fake client. Nothing here touches port 8000, 5173 or 8100."""
import json
import shutil
import time

import httpx
import pytest
from stdnum import verhoeff

from dpdp_lens import repo_scan
from dpdp_lens.api import create_app
from dpdp_lens.fixer.verify import GOLDEN_DIR
from dpdp_lens.slackbot import actions, commands
from dpdp_lens.slackbot.outbox import Poller
from dpdp_lens.store import Store
from remote import make_remote
from slackbot_fakes import APPROVER, CHANNEL, OTHER, PII, make_ctx, serve, stop_servers

PORT = 8200
TOKEN = "real-engine-token"
H = {"X-DPDP-Token": TOKEN}
FAKE_AADHAAR = "23456789012" + verhoeff.calc_check_digit("23456789012")  # synthetic, passes the Verhoeff check the engine uses


class Reply(list):
    blocks = None

    def __call__(self, text, blocks=None):
        self.append(text)
        self.blocks = blocks


@pytest.fixture(scope="module")
def remote(tmp_path_factory):
    base = tmp_path_factory.mktemp("slackbot-remote")
    make_remote(base)
    return base


@pytest.fixture
def real(remote, tmp_path, monkeypatch, with_late_scanners):
    monkeypatch.setattr(repo_scan, "GIT_BASE", f"file://{remote}")
    monkeypatch.setattr(repo_scan, "ALLOW_FILE", True)
    monkeypatch.setenv("DPDP_API_TOKEN", TOKEN)
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", "acme/tutornest,acme/missing")
    monkeypatch.setenv("DPDP_FIX_REPOS", "acme/tutornest")
    shutil.copytree(GOLDEN_DIR, tmp_path / "golden")  # a live fix saves its golden file: never into the real data folder
    app = create_app(repo_root=tmp_path, state_dir=tmp_path / "state", store=Store(tmp_path / "dpdp.db"), golden_dir=tmp_path / "golden")
    url = serve(app, PORT)
    ctx, slack, _ = make_ctx(engine_url=url, token=TOKEN)
    ctx.sleep = lambda s: time.sleep(0.2)
    yield ctx, slack, url
    stop_servers()


def get(url, path, **params):
    r = httpx.get(url + path, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_real_engine_connect_cards_status_outbox_fix_and_audit(real):
    ctx, slack, url = real
    reply = Reply()
    commands.run_command(ctx, "connect acme/tutornest", APPROVER, CHANNEL, reply)
    assert reply == []  # no error answers

    # summary and cards
    posts = slack.of("post")
    assert posts[0]["text"] == "Scanning acme/tutornest (static checks only)"
    found = get(url, "/findings", limit=500)
    total = found["total"]
    assert total >= 9 and len(posts) == 2 + total
    summary = json.dumps(posts[1]["blocks"])
    assert "Scan incomplete" not in summary and "Coverage: static checks only (" in summary and " of 19)" in summary
    assert f"New {total}" in summary
    assert all(i["slack"] for i in found["items"])  # every card's ts is stored in the engine

    # a second scan reposts nothing for unchanged findings
    before = len(slack.of("post"))
    commands.run_command(ctx, "scan", APPROVER, CHANNEL, reply)
    assert len(slack.of("post")) == before + 2 and reply == []
    commands.run_command(ctx, "diff", APPROVER, CHANNEL, reply)  # the real /repos/{id}/diff: the second scan against the baseline S-001
    assert reply == ["acme/tutornest: scan S-002 against baseline S-001"] and f"New 0 · Resolved 0 · Persistent {total}" in json.dumps(reply.blocks, ensure_ascii=False)
    reply.clear()

    # status change by an approver, with the actor in the audit trail
    log = next(i for i in found["items"] if i["check"] == "log_pii")
    hid, card_ts = log["human_id"], log["slack"]["ts"]
    actions.change_status(ctx, APPROVER, CHANNEL, card_ts, f"{hid}|in_progress", "trig", slack.views_open)
    assert get(url, f"/findings/{hid}")["status"] == "in_progress"
    assert get(url, f"/findings/{hid}")["status_by"] == APPROVER
    assert "Status: *In Progress*" in json.dumps(slack.of("update")[-1]["blocks"])

    # a modal reason, and a person who is not an approver
    other = next(i for i in found["items"] if i["check"] == "config_secret_committed")
    actions.change_status(ctx, APPROVER, CHANNEL, other["slack"]["ts"], f"{other['human_id']}|wont_fix", "trig", slack.views_open)
    meta = slack.of("view")[-1]["view"]["private_metadata"]
    assert actions.submit_reason(ctx, OTHER, meta, "not mine") == actions.NOT_ALLOWED
    assert "personal data" in actions.submit_reason(ctx, APPROVER, meta, f"aadhaar {FAKE_AADHAAR}")
    assert actions.submit_reason(ctx, APPROVER, meta, "demo key, rotated") is None
    rec = get(url, f"/findings/{other['human_id']}")
    assert rec["status"] == "wont_fix" and rec["status_reason"] == "demo key, rotated" and rec["status_by"] == APPROVER
    actions.change_status(ctx, OTHER, CHANNEL, card_ts, f"{hid}|open", "trig", slack.views_open)
    assert get(url, f"/findings/{hid}")["status"] == "in_progress" and "Not allowed" in slack.of("ephemeral")[-1]["text"]

    # a change made outside Slack (the dashboard) reaches the card through the outbox
    poller = Poller(ctx)
    poller.poll_once()
    n = len(slack.of("update"))
    r = httpx.patch(f"{url}/findings/{hid}/status", json={"status": "open", "actor": "dashboard-user"}, headers=H)
    assert r.status_code == 200
    assert poller.poll_once() == 1 and len(slack.of("update")) == n + 1
    assert "Status: *Open*" in json.dumps(slack.of("update")[-1]["blocks"])

    # details
    actions.view_details(ctx, OTHER, CHANNEL, card_ts, hid)
    assert "Likely does not meet" in json.dumps(slack.of("post")[-1]["blocks"])

    # fix and verify: the card says what the engine said, nothing more
    actions.fix_and_verify(ctx, OTHER, CHANNEL, card_ts, hid)
    assert get(url, f"/findings/{hid}")["status"] == "open"  # a non-approver changed nothing
    actions.fix_and_verify(ctx, APPROVER, CHANNEL, card_ts, hid)
    thread = [p for p in slack.of("post") if p.get("thread_ts") == card_ts][-3:]
    fixed = get(url, f"/findings/{hid}")
    events = get(url, "/audit/events", type="fix_verified", limit=5)
    assert fixed["status"] == "fixed" and events and events[0]["actor"] == APPROVER
    mode = events[0]["meta"]["mode"]
    label = "Cached verified patch (replay)" if mode == "cached_golden" else "VERIFIED by a live sandbox run"
    assert thread[0]["text"].startswith("Fixing ") and label in thread[1]["text"] and "logger" in json.dumps(thread[2]["blocks"])
    assert "Status: *Fixed*" in json.dumps(slack.of("update")[-1]["blocks"])
    assert poller.poll_once() >= 1  # the fix's own outbox row refreshes the card again

    # nothing raw anywhere
    assert not PII.findall(slack.texts())
    audit = get(url, "/audit/verify")
    assert audit["ok"] and audit["checked"] > 10


def test_real_engine_failed_clone_is_reported_as_failed_not_clean(real):
    ctx, slack, url = real
    reply = Reply()
    commands.run_command(ctx, "connect acme/missing", APPROVER, CHANNEL, reply)  # allowlisted, but the remote has no such repo
    last = slack.of("post")[-1]
    blocks = json.dumps(last["blocks"])
    assert "Scan failed: no results for acme/missing" in blocks and "Health: *Unknown*" in blocks and "white_check_mark" not in blocks
    assert get(url, "/repos/1/health")["status"] == "unknown"
    commands.run_command(ctx, "status", APPROVER, CHANNEL, reply)
    assert "Health: *Unknown*" in reply[-1]
