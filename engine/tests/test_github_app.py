"""Block 08: GitHub App access. A freshly generated test RSA key (never the real one) and a fake GitHub API on a local port.
No network, no real GitHub. The repos come from a local bare git repo, as in test_api_v2."""
import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from dpdp_lens import audit, github_app, repo_scan
from dpdp_lens.api import create_app
from dpdp_lens.github_app import GitHubApp, GitHubAppError
from dpdp_lens.slackbot import redact as slack_redact
from dpdp_lens.store import SCHEMA_VERSION, Store
from github_fakes import APP_ID, SLUG, make_github, make_key
from remote import make_remote
from slackbot_fakes import serve, stop_servers

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("preflight", ROOT / "scripts" / "preflight.py")
pf = importlib.util.module_from_spec(spec)
sys.modules["preflight"] = pf
spec.loader.exec_module(pf)

TOKEN = {"X-DPDP-Token": "test-token"}
GHS = "ghs_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"
JWT = "eyJ" + "hbGciOiJSUzI1NiJ9." + "eyJpYXQiOjE3MDAwMDAwMDB9." + "c2lnbmF0dXJlLWJ5dGVzLWhlcmU"


@pytest.fixture(autouse=True)
def _stop_servers():
    yield
    stop_servers()


@pytest.fixture
def gh(tmp_path):
    """The fake GitHub, a test key, and a GitHubApp pointed at them. `clock` is a one item list the test can move forward."""
    key = tmp_path / "app.pem"
    public = make_key(key)
    app, st = make_github(public)
    st.installs[1] = {"login": "octo", "type": "User", "repos": ["acme/tutornest", "acme/other"]}
    clock = [time.time()]
    st.clock = lambda: clock[0]
    ghapp = GitHubApp(APP_ID, str(key), SLUG, api=serve(app), clock=lambda: clock[0])
    return SimpleNamespace(app=ghapp, st=st, clock=clock, key=key, public=public)


# ---- the app JWT and the key file

def test_app_jwt_is_rs256_with_the_documented_claims(gh):
    now = time.time()
    token = github_app.build_jwt(APP_ID, github_app.read_key(str(gh.key)), now)
    claims = jwt.decode(token, gh.public, algorithms=["RS256"], issuer=APP_ID, leeway=5)
    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    assert claims["iat"] == int(now) - 60 and claims["exp"] == int(now) + 9 * 60 and claims["iss"] == APP_ID


def test_a_jwt_signed_with_another_key_is_refused_by_github(gh, tmp_path):
    other = tmp_path / "other.pem"
    make_key(other)
    bad = GitHubApp(APP_ID, str(other), SLUG, api=gh.app.api)
    with pytest.raises(GitHubAppError) as e:
        bad.installation(1)
    assert e.value.kind == "auth" and "401" in str(e.value)


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660])
def test_a_key_file_that_group_or_others_can_read_is_refused(tmp_path, mode):
    key = tmp_path / "k.pem"
    make_key(key, mode)
    with pytest.raises(GitHubAppError, match="group or others"):
        github_app.read_key(str(key))


def test_a_missing_or_garbage_key_file_is_refused_without_quoting_it(tmp_path):
    with pytest.raises(GitHubAppError, match="cannot read"):
        github_app.read_key(str(tmp_path / "nope.pem"))
    junk = tmp_path / "junk.pem"
    junk.write_text("not a key SECRET-LOOKING-TEXT")
    junk.chmod(0o600)
    with pytest.raises(GitHubAppError) as e:
        github_app.read_key(str(junk))
    assert "SECRET-LOOKING-TEXT" not in str(e.value)


def test_from_env_needs_all_three_settings(gh, monkeypatch):
    env = {"GITHUB_APP_ID": APP_ID, "GITHUB_APP_PRIVATE_KEY_PATH": str(gh.key), "GITHUB_APP_SLUG": SLUG}
    assert GitHubApp.from_env(env).slug == SLUG
    for name in env:
        assert GitHubApp.from_env({k: v for k, v in env.items() if k != name}) is None
    assert GitHubApp.from_env({}) is None


# ---- GitHub calls

def test_installation_lookup_and_missing_installation(gh):
    assert gh.app.installation(1) == {"installation_id": 1, "account_login": "octo", "account_type": "User"}
    with pytest.raises(GitHubAppError) as e:
        gh.app.installation(99)
    assert e.value.kind == "notfound"
    assert all(c["iss"] == APP_ID for c in gh.st.jwts)  # every call carried a valid app JWT


def test_installation_token_is_cached_until_five_minutes_before_expiry(gh):
    first = gh.app.token(1)
    assert first.startswith("ghs_") and gh.app.token(1) == first and gh.st.token_calls == 1
    gh.clock[0] += 3600 - 6 * 60  # still 6 minutes left: cached
    assert gh.app.token(1) == first and gh.st.token_calls == 1
    gh.clock[0] += 2 * 60  # 4 minutes left: inside the margin, so a new one
    second = gh.app.token(1)
    assert second != first and gh.st.token_calls == 2


def test_repos_are_paginated_and_sorted(gh):
    gh.st.installs[1]["repos"] = [f"acme/r{n:03d}" for n in range(250, 0, -1)]
    repos = gh.app.repos(1)
    assert [r["full_name"] for r in repos] == [f"acme/r{n:03d}" for n in range(1, 251)]
    assert repos[0] == {"full_name": "acme/r001", "private": True, "default_branch": "main"}
    assert gh.st.token_calls == 1  # one token for all three pages


def test_a_token_refusal_is_an_error_that_holds_no_secret(gh):
    gh.st.fail = 403
    with pytest.raises(GitHubAppError) as e:
        gh.app.token(1)
    text = str(e.value)
    assert e.value.kind == "auth" and "403" in text and "BEGIN" not in text and "eyJ" not in text


def test_unreachable_github_is_a_network_error(gh):
    dead = GitHubApp(APP_ID, str(gh.key), SLUG, api="http://127.0.0.1:1")
    with pytest.raises(GitHubAppError) as e:
        dead.installation(1)
    assert e.value.kind == "network"


# ---- the signed state

def test_state_roundtrip_expiry_and_tampering():
    state = github_app.sign_state("secret-a", now=1000)
    assert github_app.check_state("secret-a", state, now=1000 + 14 * 60)
    assert not github_app.check_state("secret-a", state, now=1000 + 15 * 60 + 1)  # expired
    assert not github_app.check_state("secret-b", state, now=1000)  # another secret
    payload, sig = state.split(".")
    assert not github_app.check_state("secret-a", payload + "." + "0" * 64, now=1000)
    other = github_app.sign_state("secret-a", now=1000).split(".")[0]
    assert not github_app.check_state("secret-a", other + "." + sig, now=1000)  # a payload with the wrong signature
    for bad in ("", "x", "a.b", payload, "." + sig):
        assert not github_app.check_state("secret-a", bad, now=1000)
    assert not github_app.check_state("", github_app.sign_state("", now=1000), now=1000)  # an empty secret never validates


# ---- the engine routes

@pytest.fixture(scope="module")
def remote(tmp_path_factory):
    base = tmp_path_factory.mktemp("remote8")
    return base, make_remote(base)


def build_api(remote, tmp_path, monkeypatch, github, allowed="acme/listed"):
    base, _ = remote
    monkeypatch.setattr(repo_scan, "GIT_BASE", f"file://{base}")
    monkeypatch.setattr(repo_scan, "ALLOW_FILE", True)
    monkeypatch.setenv("DPDP_API_TOKEN", "test-token")
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", allowed)
    monkeypatch.setenv("DPDP_FIX_REPOS", "acme/fixme")
    for name in ("GITHUB_TOKEN", "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH", "GITHUB_APP_SLUG"):
        monkeypatch.delenv(name, raising=False)
    seen = []  # (repo, token) for every checkout
    real = repo_scan.checkout

    def spy(full_name, ref=None, token=None, env_name="DPDP_ALLOWED_REPOS", **kw):
        seen.append((full_name, token))
        return real(full_name, ref, token, env_name, **kw)

    monkeypatch.setattr(repo_scan, "checkout", spy)
    app = create_app(repo_root=tmp_path, state_dir=tmp_path / "state", store=Store(tmp_path / "dpdp.db"), github=github)
    client = TestClient(app)
    client.seen, client.db = seen, tmp_path / "dpdp.db"
    return client


@pytest.fixture
def api(remote, gh, tmp_path, monkeypatch, with_late_scanners):
    return build_api(remote, tmp_path, monkeypatch, gh.app)


@pytest.fixture
def api_without_app(remote, tmp_path, monkeypatch, with_late_scanners):
    return build_api(remote, tmp_path, monkeypatch, None)


def install(api, installation_id=1, state=None):
    if state is None:
        url = api.get("/github/install-url", headers=TOKEN).json()["url"]
        assert url.startswith(f"https://github.com/apps/{SLUG}/installations/new?state=")
        state = url.split("state=")[1]
    return api.get("/github/setup", params={"installation_id": installation_id, "setup_action": "install", "state": state})


def connect(api, name="acme/tutornest", **extra):
    return api.post("/repos", json={"full_name": name, "actor": "U1", **extra}, headers=TOKEN)


def test_install_flow_stores_the_installation_audits_it_and_queues_one_outbox_row(api):
    r = install(api)
    assert r.status_code == 200 and "GitHub connected, return to Slack" in r.text and "octo" in r.text
    assert api.get("/github/installations", headers=TOKEN).json()[0]["account_login"] == "octo"
    events = api.get("/audit/events", params={"type": "github_installed"}).json()
    assert [(e["actor"], e["result"], e["meta"]["installation_id"]) for e in events] == [("github", "octo", 1)]
    assert [(o["kind"], o["human_id"]) for o in api.get("/outbox").json()] == [("github_installed", "1")]
    assert api.get("/audit/verify").json()["ok"]


def test_connect_route_redirects_to_github_with_a_fresh_signed_state(api):
    r = api.get("/github/connect", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith(f"https://github.com/apps/{SLUG}/installations/new?state=")
    assert github_app.check_state("test-token", r.headers["location"].split("state=")[1])
    assert install(api, state=r.headers["location"].split("state=")[1]).status_code == 200


def test_setup_refuses_a_missing_expired_or_tampered_state_and_stores_nothing(api, monkeypatch):
    good = api.get("/github/install-url", headers=TOKEN).json()["url"].split("state=")[1]
    expired = github_app.sign_state("test-token", now=time.time() - 3600)
    for state in ("", "junk", good[:-4] + "0000", expired):
        r = install(api, state=state)
        assert r.status_code == 400 and "expired" in r.text
    assert api.get("/github/installations", headers=TOKEN).json() == []
    assert api.get("/outbox").json() == []


def test_setup_without_an_installation_or_for_one_github_does_not_know(api):
    state = api.get("/github/install-url", headers=TOKEN).json()["url"].split("state=")[1]
    assert api.get("/github/setup", params={"setup_action": "request", "state": state}).status_code == 400
    r = install(api, installation_id=77, state=state)
    assert r.status_code == 404 and api.get("/github/installations", headers=TOKEN).json() == [] and api.get("/outbox").json() == []


def test_without_the_app_configured_the_github_routes_say_so_and_the_old_path_still_works(api_without_app, monkeypatch):
    api = api_without_app
    assert api.get("/github/install-url", headers=TOKEN).status_code == 503
    assert api.get("/github/installations", headers=TOKEN).status_code == 503
    assert api.get("/github/connect", follow_redirects=False).status_code == 503
    assert api.get("/github/setup", params={"installation_id": 1, "state": "x"}).status_code == 503
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", "acme/tutornest")
    assert connect(api).status_code == 201
    assert connect(api, "acme/other", installation_id=1).status_code == 403  # no app: an installation id cannot open anything


# The routes that reveal who installed the app or which private repos it sees are guarded reads. Every OTHER read stays open
# (test_api_v2 checks that list). /github/connect and /github/setup are open on purpose: a browser opens them, so the signed
# state is their check.
GUARDED_READS = ("/github/install-url", "/github/installations", "/github/installations/1/repos")


def test_the_github_reads_need_the_token(api):
    install(api)
    for path in GUARDED_READS:
        assert api.get(path).status_code == 401 and api.get(path, headers={"X-DPDP-Token": "wrong"}).status_code == 401
        assert api.get(path, headers=TOKEN).status_code == 200


def test_installation_repos_are_live_from_github_and_marked_connected(api, gh, monkeypatch):
    install(api)
    assert connect(api, installation_id=1).status_code == 201
    gh.st.installs[1]["repos"].append("acme/new")  # appears at once: nothing is remembered
    got = {r["full_name"]: r["connected"] for r in api.get("/github/installations/1/repos", headers=TOKEN).json()}
    assert got == {"acme/new": False, "acme/other": False, "acme/tutornest": True}
    assert api.get("/github/installations/9/repos", headers=TOKEN).status_code == 404


def test_connect_through_the_installation_scans_with_an_installation_token_and_stores_no_token(api, gh):
    install(api)
    r = connect(api, installation_id=1)
    assert r.status_code == 201
    repo = r.json()
    scan_id = api.post(f"/repos/{repo['id']}/scan", json={}, headers=TOKEN).json()["scan_id"]
    delta = api.get(f"/scans/{scan_id}/delta").json()
    assert delta["complete"] and delta["new"], api.get(f"/scan/{scan_id}").text[:600]
    (name, token), = api.seen
    assert name == "acme/tutornest" and token in gh.st.tokens and token.startswith("ghs_")
    assert api.app.state.core.store.one("SELECT installation_id FROM repos")[0] == 1
    dump = json.dumps(api.get("/audit/events", params={"limit": 1000}).json()) + json.dumps(api.get("/findings").json()) + api.get(f"/scan/{scan_id}").text
    assert token not in dump
    api.app.state.core.store.close()
    assert all(token.encode() not in p.read_bytes() for p in api.db.parent.glob("dpdp.db*"))  # nor in the SQLite file or its WAL


def test_a_repo_the_installation_does_not_share_is_refused(api, gh):
    install(api)
    for body in ({"full_name": "acme/secret", "installation_id": 1},  # not shared
                 {"full_name": "acme/tutornest", "installation_id": 99},  # an installation this engine never saw
                 {"full_name": "acme/tutornest"}):  # not on the env list, no installation named
        r = api.post("/repos", json=body, headers=TOKEN)
        assert r.status_code == 403, body
    assert api.post("/repos", json={"full_name": "nope", "installation_id": 1}, headers=TOKEN).status_code == 422
    assert api.get("/repos").json() == []
    assert "DPDP_ALLOWED_REPOS" in api.post("/repos", json={"full_name": "acme/tutornest"}, headers=TOKEN).json()["detail"]


def test_a_removed_installation_blocks_new_connects_when_github_says_so(api, gh):
    install(api)
    del gh.st.installs[1]  # uninstalled on GitHub
    r = connect(api, installation_id=1)
    assert r.status_code == 404 and api.get("/repos").json() == []


def test_the_env_allowlist_path_is_unchanged(api, monkeypatch):
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", "acme/tutornest")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "e" * 30)
    repo = connect(api).json()
    assert api.app.state.core.store.one("SELECT installation_id FROM repos")[0] is None
    api.post(f"/repos/{repo['id']}/scan", json={}, headers=TOKEN)
    assert api.seen == [("acme/tutornest", "ghp_" + "e" * 30)]  # GITHUB_TOKEN, no app involved, no token exchange needed


def test_an_allowlisted_repo_the_installation_does_not_share_still_connects_through_the_env_path(api, gh, monkeypatch):
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", "acme/tutornest")
    gh.st.installs[2] = {"login": "elsewhere", "type": "Organization", "repos": ["acme/zzz"]}
    install(api, 2)
    assert connect(api, installation_id=2).status_code == 201
    assert api.app.state.core.store.one("SELECT installation_id FROM repos")[0] is None


def test_installing_the_app_never_makes_a_repo_fix_eligible(api):
    install(api)
    repo = connect(api, installation_id=1).json()
    api.post(f"/repos/{repo['id']}/scan", json={}, headers=TOKEN)
    hid = api.get("/findings").json()["items"][0]["human_id"]
    for mode in ("cached", "live"):
        r = api.post(f"/findings/{hid}/fix", params={"mode": mode}, json={"actor": "U1"}, headers=TOKEN)
        assert r.status_code == 403 and "DPDP_FIX_REPOS" in r.json()["detail"]
    assert [e["type"] for e in api.get("/audit/events").json() if e["type"].startswith("fix")] == []


def test_a_scheduled_scan_gets_a_fresh_token_when_the_cached_one_is_old(api, gh, monkeypatch):
    install(api)
    repo = connect(api, installation_id=1).json()
    core = api.app.state.core
    monkeypatch.setattr(repo_scan, "scan_checkout", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop after the clone")))  # only the token matters
    row = lambda: core.store.one("SELECT * FROM repos WHERE id=?", (repo["id"],))  # noqa: E731
    core.scan_repo_now(row())
    core.scan_repo_now(row())  # minutes later: still the cached token
    gh.clock[0] += 3600  # an hour later, as a watch schedule would be
    core.scan_repo_now(row())
    tokens = [t for _, t in api.seen]
    assert len(tokens) == 3 and tokens[0] == tokens[1] != tokens[2] and gh.st.token_calls == 2


def test_a_failed_token_exchange_is_a_failed_scan_with_no_secret_in_it(api, gh):
    install(api)
    repo = connect(api, installation_id=1).json()
    gh.clock[0] += 3600  # the token from the connect step has expired, so this scan must exchange a new one
    gh.st.fail = 403
    scan_id = api.post(f"/repos/{repo['id']}/scan", json={}, headers=TOKEN).json()["scan_id"]
    r = api.get(f"/scan/{scan_id}")
    assert "GitHub answered 403" in r.text and "BEGIN" not in r.text and "eyJ" not in r.text
    assert api.get(f"/repos/{repo['id']}/health").json()["status"] == "unknown"  # never shown as healthy
    assert api.get("/audit/events", params={"type": "scan_failed"}).json()


# ---- store schema 3

def test_a_version_2_database_is_migrated_and_keeps_its_data(tmp_path):
    path = tmp_path / "v2.db"
    s = Store(path)
    s.run("INSERT INTO repos(full_name, created_at) VALUES ('acme/app', 'x')")
    s.run("ALTER TABLE repos DROP COLUMN installation_id")
    s.run("DROP TABLE installations")
    s.run("PRAGMA user_version=2")
    s.close()
    new = Store(path)
    assert SCHEMA_VERSION == 3 and new.one("PRAGMA user_version")[0] == 3
    assert new.one("SELECT full_name, installation_id FROM repos")[:] == ("acme/app", None)
    new.run("INSERT INTO installations VALUES (5, 'octo', 'User', 'x')")
    assert new.one("SELECT account_login FROM installations")[0] == "octo"
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 3


# ---- redaction

def test_installation_tokens_and_jwts_are_redacted_everywhere(gh):
    real_jwt = gh.app.app_jwt()
    for text in (f"clone failed with {GHS} here", f"Authorization: Bearer {JWT}", f"Bearer {real_jwt} sent"):
        for out in (audit.redact(text), slack_redact.redact(text), pf.redact(text, {})):
            assert "ghs_a1B2" not in out and "eyJ" not in out and "[redacted]" in out
    cleaned = audit.clean({"msg": f"x {GHS}", "list": [f"y {real_jwt}"]})
    assert "ghs_" not in json.dumps(cleaned) and "eyJ" not in json.dumps(cleaned)
    assert slack_redact.redact("a ghr_" + "x" * 20 + " b gho_" + "y" * 20).count("[redacted]") == 2


def test_log_records_hide_installation_tokens():
    import logging
    rec = logging.LogRecord("x", logging.WARNING, "f", 1, "git said %s", (GHS,), None)
    slack_redact.RedactFilter().filter(rec)
    assert "ghs_" not in rec.getMessage()


# ---- preflight

def app_env(gh, **extra):
    return {"DPDP_API_TOKEN": "api-token-for-tests-1234567890", "GITHUB_APP_ID": APP_ID, "GITHUB_APP_PRIVATE_KEY_PATH": str(gh.key),
            "GITHUB_APP_SLUG": SLUG, **extra}


def test_preflight_skips_every_app_check_when_the_app_is_not_set_up():
    for check in (pf.check_app_vars, pf.check_app_key, pf.check_app_jwt, pf.check_app_live):
        assert check({}).status == "SKIP"
    assert pf.run_checks({}, "env", offline=True)[-1].status == "SKIP"


def test_preflight_passes_with_a_good_app_setup(gh):
    env = app_env(gh)
    assert [c(env).status for c in (pf.check_app_vars, pf.check_app_key, pf.check_app_jwt)] == ["PASS"] * 3
    assert pf.run_checks(env, "env", offline=True)[-1].status == "SKIP"  # the live check is a network check: --offline skips it


@pytest.mark.parametrize("drop", ["GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH", "GITHUB_APP_SLUG"])
def test_preflight_fails_when_one_app_variable_is_missing(gh, drop):
    env = {k: v for k, v in app_env(gh).items() if k != drop}
    r = pf.check_app_vars(env)
    assert r.status == "FAIL" and drop in r.detail


def test_preflight_fails_on_a_key_that_is_unsafe_missing_or_not_a_key(gh, tmp_path):
    gh.key.chmod(0o644)
    r = pf.check_app_key(app_env(gh))
    assert r.status == "FAIL" and "group or others" in r.detail and pf.check_app_jwt(app_env(gh)).status == "FAIL"
    assert pf.check_app_key(app_env(gh, GITHUB_APP_PRIVATE_KEY_PATH=str(tmp_path / "gone.pem"))).status == "FAIL"
    junk = tmp_path / "junk.pem"
    junk.write_text("hello")
    junk.chmod(0o600)
    assert pf.check_app_key(app_env(gh, GITHUB_APP_PRIVATE_KEY_PATH=str(junk))).status == "FAIL"


def test_preflight_live_check_sends_a_valid_jwt_and_compares_the_slug(gh):
    sent = []

    def get(url, headers, timeout):
        sent.append((url, headers))
        return httpx.Response(200, json={"slug": SLUG})

    assert pf.check_app_live(app_env(gh), get=get).status == "PASS"
    url, headers = sent[0]
    assert url == "https://api.github.com/app"
    assert jwt.decode(headers["Authorization"].removeprefix("Bearer "), gh.public, algorithms=["RS256"], issuer=APP_ID, leeway=5)
    assert pf.check_app_live(app_env(gh, GITHUB_APP_SLUG="someone-else"), get=get).status == "FAIL"
    assert pf.check_app_live(app_env(gh), get=lambda *a, **k: httpx.Response(401, json={"message": "Bad credentials"})).status == "FAIL"

    def offline(*a, **k):
        raise httpx.ConnectError("down")

    r = pf.check_app_live(app_env(gh), get=offline)
    assert r.status == "FAIL" and "no network" in r.detail


def test_preflight_output_never_holds_the_jwt_or_the_key(gh):
    lines = pf.render(pf.run_checks(app_env(gh), "env", offline=True), app_env(gh))
    assert "eyJ" not in lines and "BEGIN" not in lines and gh.key.read_text().splitlines()[1] not in lines
