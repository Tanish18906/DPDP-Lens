"""Block 13: open a pull request with a verified fix, against a fake GitHub API (git data API, pulls, downscoped tokens). No network.
Real GitHub cannot be tested here: see the hand-over for what must be checked by hand."""
import base64
import difflib
import json
import re

import pytest

from dpdp_lens import audit, pr
from dpdp_lens.fixer.verify import GOLDEN_DIR
from dpdp_lens.ingest import mark_fixed
from dpdp_lens.models import Finding
from github_fakes import add_repo
from remote import TARGET_APP
from test_github_app import TOKEN, api, connect, gh, install, remote  # noqa: F401  (fixtures and helpers of the GitHub App tests)

from dpdp_lens.fixer.templates import V3  # noqa: E402

GOLDEN = json.loads((GOLDEN_DIR / "V3.json").read_text())  # the verified log_pii diff, made on TutorNest's app/main.py
# verify_fix builds the stored diff as "<patch>\n\nVerified: ...\nNot verified / you still must: ...\n" (the old golden file predates the two lines)
GOLDEN["diff"] = f"{GOLDEN['diff'].rstrip()}\n\nVerified: {V3.verified_msg}\nNot verified / you still must: {V3.not_verified_msg or 'verify your own tests and deploy'}\n"
MAIN = (TARGET_APP / "backend" / "app" / "main.py").read_text()
OTHER = "# unrelated file\n"


def prepare(api, gh, monkeypatch, *, verified=True, mode="live", commit=None, allow="1", fix_repos="acme/tutornest", diff=None, main=MAIN, install_it=True):
    """A connected repo with a scan, a verified fix recorded for its log_pii finding, and the repo present in the fake GitHub."""
    monkeypatch.setenv("DPDP_FIX_REPOS", fix_repos)
    if allow is None:
        monkeypatch.delenv("DPDP_ALLOW_PR", raising=False)
    else:
        monkeypatch.setenv("DPDP_ALLOW_PR", allow)
    install(api)
    repo = connect(api, installation_id=1 if install_it else None) if install_it else None
    if repo is None:
        monkeypatch.setenv("DPDP_ALLOWED_REPOS", "acme/tutornest")
        repo = connect(api)
    repo = repo.json()
    sid = api.post(f"/repos/{repo['id']}/scan", json={}, headers=TOKEN).json()["scan_id"]
    scanned = api.get(f"/scans/{sid}/delta").json()["commit"]
    add_repo(gh.st, "acme/tutornest", {"backend/app/main.py": main, "backend/other.py": OTHER, "README.md": "# demo\n"}, commit=scanned,
             modes={"backend/other.py": "100755"})
    store = api.app.state.core.store
    row = store.one("SELECT human_id, last_finding_json FROM findings WHERE check_id='log_pii'")
    finding = json.loads(row["last_finding_json"])
    finding["status"] = "verified_fixed" if verified else "open"
    finding["fix"] = {**finding["fix"], "available": True, "verified": verified, "rescan_passed": verified, "tests_passed": verified,
                      "diff": diff or GOLDEN["diff"]}
    if verified:
        mark_fixed(store, row["human_id"], "U1", Finding.model_validate(finding), {"mode": mode, "commit": commit or scanned})
    api.hid, api.scanned, api.repo_id = row["human_id"], scanned, repo["id"]
    return api


def open_pr(api, actor="U1"):
    return api.post(f"/findings/{api.hid}/pr", json={"actor": actor}, headers=TOKEN)


def short(sha):
    return sha[:7]


def test_the_pull_request_flow_end_to_end(api, gh, monkeypatch):
    prepare(api, gh, monkeypatch)
    before = gh.st.token_calls
    r = open_pr(api)
    assert r.status_code == 200, r.text
    out = r.json()
    branch = f"dpdp-lens/fix-{api.hid}-{short(api.scanned)}"
    assert out["branch"] == branch and out["reused"] is False and out["base"] == "main" and out["pr_url"] == "https://github.com/acme/tutornest/pull/1"
    gr = gh.st.repos["acme/tutornest"]
    assert gr["refs"]["main"] == api.scanned  # the default branch was never touched
    new_commit = gr["refs"][branch]
    assert gr["commits"][new_commit]["parents"] == [api.scanned]  # from exactly the scanned commit
    files = {e["path"]: e for e in gr["trees"][gr["commits"][new_commit]["tree"]]}
    assert gr["blobs"][files["backend/app/main.py"]["sha"]].decode() != MAIN
    assert files["backend/other.py"]["mode"] == "100755" and gr["blobs"][files["backend/other.py"]["sha"]].decode() == OTHER  # untouched files stay as they were
    patched = gr["blobs"][files["backend/app/main.py"]["sha"]].decode()
    again = "".join(difflib.unified_diff(MAIN.splitlines(True), patched.splitlines(True), "a/app/main.py", "b/app/main.py"))
    assert again.rstrip("\n") == pr.split_diff(GOLDEN["diff"])[0].rstrip("\n")  # exactly the verified result
    assert "logger.info(\"signup ok user_id=%s\", student_id)" in patched and "req.aadhaar)" not in patched
    # only additions: blobs, a tree, a commit, a NEW ref, a pull request. Never a ref update, a delete or a merge.
    assert [(m, p) for m, p, _ in gh.st.writes] == [("POST", "git/blobs"), ("POST", "git/trees"), ("POST", "git/commits"), ("POST", "git/refs"), ("POST", "pulls")]
    assert all(w[2].get("ref", branch) == f"refs/heads/{branch}" for w in gh.st.writes if w[1] == "git/refs")
    prr = gr["prs"][0]
    assert prr["title"].startswith(f"DPDP Lens: fix {api.hid} ") and prr["head"] == branch and prr["base"] == "main"
    v, nv = pr.split_diff(GOLDEN["diff"])[1:]
    assert v in prr["body"] and nv in prr["body"]  # the two lines exactly as the engine produced them
    assert "Likely does not meet Act s8(5)" in prr["body"] and "Generated by DPDP Lens" in prr["body"] and "not a compliance certificate" in prr["body"]
    assert "`app/main.py`: +2 -2" in prr["body"] and "has moved on" not in prr["body"]
    # the store: the url is on the record, the finding stays Fixed (not Resolved), the audit chain has pr_opened
    rec = api.get(f"/findings/{api.hid}").json()
    assert rec["pr_url"] == out["pr_url"] and rec["status"] == "fixed" and rec["pr_available"] is False
    ev = [e for e in api.get("/audit/events", params={"type": "pr_opened"}).json()]
    assert len(ev) == 1 and ev[0]["actor"] == "U1" and ev[0]["result"] == out["pr_url"] and ev[0]["meta"]["branch"] == branch
    assert api.get("/audit/verify").json()["ok"] and gh.st.token_calls >= before + 1


def test_downscoped_token_request_body_and_no_reuse(api, gh, monkeypatch):
    prepare(api, gh, monkeypatch)
    gh.app.repos(1)  # a read token for the scan side is cached
    cached = dict(gh.app._tokens)
    assert open_pr(api).status_code == 200
    bodies = [b for b in gh.st.token_requests if b]
    assert bodies == [{"repositories": ["tutornest"], "permissions": {"contents": "write", "pull_requests": "write"}}]  # one repo, two permissions
    assert any(b is None for b in gh.st.token_requests)  # scans and clones keep their plain read tokens
    write_tokens = [t for t, scope in gh.st.scope.items() if scope]
    assert len(write_tokens) == 1 and write_tokens[0] not in {t for t, _ in gh.app._tokens.values()}  # never cached
    assert gh.app._tokens == cached  # the scan token cache was left alone
    # a plain read token can read but is refused by the write routes of the fake (403): it could not have made the pull request
    read_token = gh.app.token(1)
    assert gh.app.api_call("GET", "/installation/repositories", read_token)["total_count"] >= 1
    from dpdp_lens.github_app import GitHubAppError
    with pytest.raises(GitHubAppError) as e:
        gh.app.api_call("POST", "/repos/acme/tutornest/git/blobs", read_token, json={"content": "x", "encoding": "utf-8"})
    assert e.value.kind == "auth"


def test_the_token_never_reaches_the_store_the_audit_log_the_response_or_an_error(api, gh, monkeypatch):
    prepare(api, gh, monkeypatch)
    r = open_pr(api)
    token = next(t for t, scope in gh.st.scope.items() if scope)
    dump = r.text + json.dumps(api.get("/audit/events", params={"limit": 1000}).json()) + json.dumps(api.get("/findings").json())
    assert token not in dump
    api.app.state.core.store.close()
    assert all(token.encode() not in p.read_bytes() for p in api.db.parent.glob("dpdp.db*"))
    leak = pr.PrError("github", f"GitHub said no for {token} and Bearer {gh.app.app_jwt()}")
    assert token not in str(leak) and "eyJ" not in str(leak) and "ghs_" not in audit.redact(f"x {token}")


def test_the_branch_name_is_strictly_validated():
    assert pr.branch_name("DPDP-014", "a" * 40) == "dpdp-lens/fix-DPDP-014-aaaaaaa"
    for bad in ("../DPDP-001", "DPDP-001; rm", "dpdp-001", "DPDP-1", "DPDP-001/../x", "DPDP-001\n"):
        with pytest.raises(pr.PrError):
            pr.branch_name(bad, "a" * 40)
    with pytest.raises(pr.PrError):
        pr.branch_name("DPDP-001", "XYZ----")  # not hex
    assert not pr.BRANCH.fullmatch("main") and not pr.BRANCH.fullmatch("dpdp-lens/fix-DPDP-001-abc12345")


# ---- refusals (nothing is written to GitHub in any of them)

@pytest.mark.parametrize("kw, status, word", [
    (dict(allow=None), 403, "switched off"), (dict(allow="0"), 403, "switched off"),
    (dict(fix_repos="acme/other"), 403, "not in DPDP_FIX_REPOS"),
    (dict(install_it=False), 403, "not connected through the GitHub App"),
    (dict(verified=False), 409, "not verified"),
    (dict(mode="cached_golden"), 409, "cached replay")])
def test_refusals_say_why_and_write_nothing(api, gh, monkeypatch, kw, status, word):
    prepare(api, gh, monkeypatch, **kw)
    r = open_pr(api)
    assert r.status_code == status and word in r.json()["detail"], r.text
    assert gh.st.writes == [] and api.get(f"/findings/{api.hid}").json()["pr_url"] == ""


def test_the_button_flag_is_only_true_when_everything_allows_it(api, gh, monkeypatch):
    prepare(api, gh, monkeypatch)
    assert api.get(f"/findings/{api.hid}").json()["pr_available"] is True
    assert [i for i in api.get("/findings").json()["items"] if i["human_id"] == api.hid][0]["pr_available"] is True
    monkeypatch.setenv("DPDP_ALLOW_PR", "0")
    assert api.get(f"/findings/{api.hid}").json()["pr_available"] is False
    monkeypatch.setenv("DPDP_ALLOW_PR", "1")
    monkeypatch.setenv("DPDP_FIX_REPOS", "acme/other")
    assert api.get(f"/findings/{api.hid}").json()["pr_available"] is False


def test_the_route_needs_the_token_and_a_known_finding(api, gh, monkeypatch):
    prepare(api, gh, monkeypatch)
    assert api.post(f"/findings/{api.hid}/pr", json={}).status_code == 401
    assert api.post("/findings/DPDP-999/pr", json={}, headers=TOKEN).status_code == 404


def test_a_patch_that_does_not_apply_pushes_nothing(api, gh, monkeypatch):
    prepare(api, gh, monkeypatch, main=MAIN.replace("# PLANTED V3", "# changed upstream"))
    r = open_pr(api)
    assert r.status_code == 409 and "need exactly one" in r.json()["detail"]
    assert gh.st.writes == [] and [e for e in api.get("/audit/events", params={"type": "pr_failed"}).json()][0]["meta"]["reason"]
    assert api.get(f"/findings/{api.hid}").json()["pr_url"] == ""


def test_an_existing_branch_with_an_open_pr_is_reused_and_one_without_is_reported(api, gh, monkeypatch):
    prepare(api, gh, monkeypatch)
    branch = f"dpdp-lens/fix-{api.hid}-{short(api.scanned)}"
    gr = gh.st.repos["acme/tutornest"]
    gr["refs"][branch] = api.scanned  # the branch is there already
    r = open_pr(api)
    assert r.status_code == 409 and "already exists and has no open pull request" in r.json()["detail"] and gh.st.writes == []
    gr["prs"].append({"number": 7, "head": branch, "state": "open", "html_url": "https://github.com/acme/tutornest/pull/7", "title": "t", "body": "b", "base": "main"})
    r = open_pr(api)
    assert r.status_code == 200 and r.json()["reused"] is True and r.json()["pr_url"].endswith("/pull/7") and gh.st.writes == []
    assert open_pr(api).json()["pr_url"].endswith("/pull/7")  # and a second click gives the stored url


def test_a_moved_default_branch_is_said_in_the_body(api, gh, monkeypatch):
    prepare(api, gh, monkeypatch)
    gh.st.repos["acme/tutornest"]["refs"]["main"] = "b" * 40  # someone pushed to main after the scan
    assert open_pr(api).status_code == 200
    body = gh.st.repos["acme/tutornest"]["prs"][0]["body"]
    assert "`main` has moved on since then" in body and "bbbbbbb" in body and gh.st.repos["acme/tutornest"]["refs"]["main"] == "b" * 40


def test_a_github_refusal_is_a_502_with_an_audit_event(api, gh, monkeypatch):
    prepare(api, gh, monkeypatch)
    del gh.st.repos["acme/tutornest"]  # the repo is gone for the token
    r = open_pr(api)
    assert r.status_code == 502 and "GitHub refused the pull request step" in r.json()["detail"]
    ev = api.get("/audit/events", params={"type": "pr_failed"}).json()
    assert len(ev) == 1 and ev[0]["meta"]["reason"] and api.get(f"/findings/{api.hid}").json()["status"] == "fixed"


def test_the_diff_applier_is_exact_or_refuses():
    old = "a\nb\nc\nd\ne\n"
    new = "a\nB\nc\nd\ne\nf\n"
    section = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/x.py", "b/x.py"))
    assert pr.apply_section(old, section, "x.py") == new
    with pytest.raises(pr.PrError):
        pr.apply_section(old.replace("b", "Q"), section, "x.py")  # the file is not what was verified
    with pytest.raises(pr.PrError):
        pr.apply_section(old, section.replace("+1,6 @@", "+1,7 @@"), "x.py")  # a diff that does not reproduce itself (wrong hunk header)
    nonl = "a\nb"  # a file with no newline at its end: difflib's diff cannot express it, so it is refused, never guessed
    sec = "".join(difflib.unified_diff(nonl.splitlines(True), "a\nc".splitlines(True), "a/y", "b/y"))
    with pytest.raises(pr.PrError):
        pr.apply_section(nonl, sec, "y")
    with pytest.raises(pr.PrError):
        pr.split_diff("--- a/x\n+++ b/x\n")  # no verification lines


def test_the_pr_body_holds_no_token_and_no_raw_personal_data(api, gh, monkeypatch):
    prepare(api, gh, monkeypatch)
    open_pr(api)
    body = gh.st.repos["acme/tutornest"]["prs"][0]["body"]
    assert not re.search(r"ghs_|eyJ|\b[2-9]\d{3} ?\d{4} ?\d{4}\b|\b[6-9]\d{9}\b", body)


def test_migration_from_version_3_adds_the_pr_column(tmp_path):
    from dpdp_lens.store import Store
    s = Store(tmp_path / "v3.db")
    s.run("INSERT INTO repos(full_name, created_at) VALUES ('a/b', 'x')")
    s.run("ALTER TABLE findings DROP COLUMN pr_url")
    s.run("PRAGMA user_version=3")
    s.close()
    new = Store(tmp_path / "v3.db")
    assert new.one("PRAGMA user_version")[0] == 4 and new.one("SELECT COUNT(*) FROM pragma_table_info('findings') WHERE name='pr_url'")[0] == 1


# ---- preflight

def test_preflight_pull_request_switch(gh):
    from test_github_app import app_env, pf
    assert pf.check_pr_switch({}).status == "SKIP" and pf.check_pr_switch({"DPDP_ALLOW_PR": "0"}).status == "SKIP"  # off by default: the old setup passes
    env = app_env(gh, DPDP_ALLOW_PR="1", DPDP_FIX_REPOS="acme/tutornest")
    r = pf.check_pr_switch(env)
    assert r.status == "PASS" and "not checked here" in r.detail
    assert pf.check_pr_switch({**env, "DPDP_FIX_REPOS": ""}).status == "FAIL"
    no_app = {k: v for k, v in env.items() if not k.startswith("GITHUB_APP_")}
    assert pf.check_pr_switch(no_app).status == "FAIL" and "GitHub App" in pf.check_pr_switch(no_app).detail
