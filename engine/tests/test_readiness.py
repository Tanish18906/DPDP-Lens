"""Block 11: the DPDP readiness report (engine). A TutorNest ingest through a local bare repo, as in test_api_v2. No network."""
import json
import re
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from dpdp_lens import readiness, repo_scan
from dpdp_lens.api import create_app
from dpdp_lens.fixer.verify import GOLDEN_DIR
from dpdp_lens.ingest import record_scan_failed
from dpdp_lens.store import Store
from remote import make_remote

TOKEN = {"X-DPDP-Token": "test-token"}
PII = [re.compile(r"\b[2-9]\d{3} ?\d{4} ?\d{4}\b"), re.compile(r"\b(?!X{5})[A-Z]{5}\d{4}[A-Z]\b"), re.compile(r"\b[6-9]\d{9}\b")]


@pytest.fixture(scope="module")
def remote(tmp_path_factory):
    base = tmp_path_factory.mktemp("remote11")
    return base, make_remote(base)


@pytest.fixture
def api(remote, tmp_path, monkeypatch, with_late_scanners):
    base, sha = remote
    monkeypatch.setattr(repo_scan, "GIT_BASE", f"file://{base}")
    monkeypatch.setattr(repo_scan, "ALLOW_FILE", True)
    monkeypatch.setenv("DPDP_API_TOKEN", "test-token")
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", "acme/tutornest")
    monkeypatch.setenv("DPDP_FIX_REPOS", "acme/tutornest")
    shutil.copytree(GOLDEN_DIR, tmp_path / "golden")
    store = Store(tmp_path / "dpdp.db")
    client = TestClient(create_app(repo_root=tmp_path, state_dir=tmp_path / "state", store=store, golden_dir=tmp_path / "golden"))
    client.store = store
    return client


def scanned(api):
    rid = api.post("/repos", json={"full_name": "acme/tutornest", "actor": "U1"}, headers=TOKEN).json()["id"]
    sid = api.post(f"/repos/{rid}/scan", json={}, headers=TOKEN).json()["scan_id"]
    return rid, sid


def link(api, rid, **body):
    r = api.post(f"/repos/{rid}/report-link", json={"actor": "U1", **body}, headers=TOKEN)
    assert r.status_code == 200, r.text
    return r.json()


def first_lines(html: str) -> str:
    return re.sub(r"<[^>]+>", "\n", html.split("<h2>")[0])


def test_the_report_of_a_tutornest_ingest_has_every_section(api):
    rid, sid = scanned(api)
    r = api.get(f"/repos/{rid}/report", headers=TOKEN)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "<h1>DPDP readiness report</h1>" in html and "compliance audit report" not in html.lower()
    assert "readiness report based on automated checks. It is not legal advice and not a compliance certificate" in html
    assert html.index("What this report is") < html.index("<h2>Scan</h2>")  # the disclaimer is the first section
    for section in ("<h2>Scope</h2>", "<h2>Health</h2>", "<h2>Summary</h2>", "<h2>Findings</h2>", "<h2>Audit trail</h2>", "<h2>Limits</h2>", "Print / Save as PDF"):
        assert section in html
    j = api.get(f"/repos/{rid}/report", params={"format": "json"}, headers=TOKEN).json()
    assert j["repo"] == {"id": rid, "full_name": "acme/tutornest", "branch": "main"} and j["scan"]["scan_id"] == sid
    assert j["scan"]["commit"] == api.get(f"/scans/{sid}/delta").json()["commit"] and j["scan"]["scanner_version"] and j["complete"] is True
    assert j["scope"]["mode"] == "static" and j["scope"]["checks_total"] == 26 and j["scope"]["checks_run"] == len(j["scope"]["run"]) < 26
    assert {n["check"] for n in j["scope"]["not_run"]} >= {"api_pii_exposure", "api_idor"} and all("running app" in n["reason"] for n in j["scope"]["not_run"])
    assert f"static checks only ({j['scope']['checks_run']} of 26)" in html and "tamper-evident, not tamper-proof" in html
    assert "static" in " ".join(j["limits"]) and "10 of 26" in " ".join(j["limits"])
    stored = api.get("/findings", params={"repo_id": rid, "limit": 500}).json()
    assert len(j["findings"]) == stored["total"] == j["summary"]["findings"] and sum(j["summary"]["by_severity"].values()) == stored["total"]
    sev = [f["severity"] for f in j["findings"]]
    assert sev == sorted(sev, key=["critical", "high", "medium", "low"].index)  # critical first
    one = next(f for f in j["findings"] if f["check"] == "log_pii")
    assert {"human_id", "title", "clauses", "location", "proof", "status", "fix", "evidence"} <= set(one)
    assert one["proof"] == "static" and any(c["ref"] == "Act s8(5)" for c in one["clauses"]) and one["location"].endswith("main.py:" + one["location"].split(":")[-1])
    assert "Act s8(5)" in html and one["human_id"] in html and "A verified fix template exists, not run yet" in html
    assert j["audit"]["chain_ok"] is True and j["audit"]["events_for_repo"] == len(api.get("/audit/events", params={"repo_id": rid, "limit": 1000}).json())


def test_the_default_scan_is_the_latest_complete_one_and_a_named_scan_works(api):
    rid, first = scanned(api)
    second = api.post(f"/repos/{rid}/scan", json={}, headers=TOKEN).json()["scan_id"]
    assert api.get(f"/repos/{rid}/report", params={"format": "json"}, headers=TOKEN).json()["scan"]["scan_id"] == second
    assert api.get(f"/repos/{rid}/report", params={"format": "json", "scan_id": first}, headers=TOKEN).json()["scan"]["scan_id"] == first
    assert api.get(f"/repos/{rid}/report", params={"scan_id": "S-999"}, headers=TOKEN).status_code == 404
    assert api.get("/repos/99/report", headers=TOKEN).status_code == 404
    assert api.get(f"/repos/{rid}/report", params={"format": "pdf"}, headers=TOKEN).status_code == 422


def test_a_repo_with_no_scan_has_no_report(api):
    rid = api.post("/repos", json={"full_name": "acme/tutornest", "actor": "U1"}, headers=TOKEN).json()["id"]
    r = api.get(f"/repos/{rid}/report", headers=TOKEN)
    assert r.status_code == 404 and "no scan yet" in r.json()["detail"]


def test_an_incomplete_scan_is_said_in_the_first_lines_and_never_reads_clean(api):
    rid, sid = scanned(api)
    api.store.run("UPDATE scans SET status='incomplete', errors_json=? WHERE scan_id=?",
                  (json.dumps([{"scanner": "log_scan", "kind": "capped", "message": "file over 1 MB"}]), sid))
    html = api.get(f"/repos/{rid}/report", headers=TOKEN).text
    top = first_lines(html)
    assert "Scan incomplete: results are partial" in top and "not a clean result" in top
    assert html.index("results are partial") < html.index("What this report is")
    assert "log_scan" in html and "file over 1 MB" in html and "Unknown" in html
    j = api.get(f"/repos/{rid}/report", params={"format": "json"}, headers=TOKEN).json()
    assert j["complete"] is False and j["health"]["status"] == "unknown"


def test_a_newer_failed_scan_is_called_out_on_the_older_complete_report(api):
    rid, sid = scanned(api)
    record_scan_failed(api.store, rid, "S-900", "bot", "U1", "clone failed: network is unreachable")
    html = api.get(f"/repos/{rid}/report", headers=TOKEN).text
    assert "The latest scan S-900 is failed" in first_lines(html) and f"older scan {sid}" in html
    failed = api.get(f"/repos/{rid}/report", params={"scan_id": "S-900"}, headers=TOKEN).text
    assert "Scan failed: scan S-900 produced no results" in first_lines(failed) and "No findings were stored for this scan." in failed


def test_evidence_is_masked_and_no_raw_pii_reaches_the_page(api, raw_pii):
    rid, sid = scanned(api)
    for html in (api.get(f"/repos/{rid}/report", headers=TOKEN).text, api.get(f"/repos/{rid}/report", params={"format": "json"}, headers=TOKEN).text):
        assert not any(rx.search(html) for rx in PII)
    # even if a raw value got into a stored finding, the report masks it again
    row = api.store.one("SELECT human_id, last_finding_json FROM findings LIMIT 1")
    last = json.loads(row["last_finding_json"])
    aadhaar = next(v for v in raw_pii if re.fullmatch(r"\d{12}", v))
    last["evidence"]["masked_sample"] = f"aadhaar {aadhaar[:4]} {aadhaar[4:8]} {aadhaar[8:]}"
    api.store.run("UPDATE findings SET last_finding_json=? WHERE human_id=?", (json.dumps(last), row["human_id"]))
    page = api.get(f"/repos/{rid}/report", headers=TOKEN).text
    assert aadhaar not in page and f"{aadhaar[:4]} {aadhaar[4:8]} {aadhaar[8:]}" not in page and not any(rx.search(page) for rx in PII)


def test_html_is_escaped_and_the_csp_allows_only_its_own_print_script(api):
    rid, sid = scanned(api)
    row = api.store.one("SELECT human_id FROM findings LIMIT 1")
    api.store.run("UPDATE findings SET title='<script>alert(1)</script>' WHERE human_id=?", (row["human_id"],))
    r = api.get(f"/repos/{rid}/report", headers=TOKEN)
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text
    nonce = re.search(r"script-src 'nonce-([^']+)'", r.headers["content-security-policy"]).group(1)
    assert f'<script nonce="{nonce}">' in r.text and r.text.count("<script") == 1 and r.headers["cache-control"] == "no-store"


# ---- signed links and access

def test_a_signed_link_opens_the_report_without_the_token_header(api):
    rid, sid = scanned(api)
    out = link(api, rid)
    assert out["scan_id"] == sid and out["expires_in"] == 900 and out["url"].startswith(f"/repos/{rid}/report?scan_id={sid}&sig=")
    assert out["summary"]["coverage"].startswith("static checks only") and out["summary"]["findings"] > 0 and out["summary"]["health"] == "at_risk"
    r = api.get(out["url"])  # no header
    assert r.status_code == 200 and "DPDP readiness report" in r.text
    assert api.get(out["url"] + "&format=json").json()["scan"]["scan_id"] == sid
    assert [e["type"] for e in api.get("/audit/events", params={"type": "report_link_created"}).json()] == ["report_link_created"]


def test_expired_tampered_and_misbound_links_are_403(api, remote, monkeypatch):
    rid, sid = scanned(api)
    good = link(api, rid)["url"]
    sig = good.split("sig=")[1]
    assert api.get(f"/repos/{rid}/report", params={"scan_id": sid, "sig": sig[:-1] + ("0" if sig[-1] != "0" else "1")}).status_code == 403  # tampered
    payload, mac = sig.split(".")
    assert api.get(f"/repos/{rid}/report", params={"scan_id": sid, "sig": payload[:-2] + "AA." + mac}).status_code == 403  # payload changed
    expired = readiness.sign_link("test-token", rid, sid, now=time.time() - 3600)
    assert api.get(f"/repos/{rid}/report", params={"scan_id": sid, "sig": expired}).status_code == 403
    assert api.get(f"/repos/{rid}/report", params={"scan_id": "S-002", "sig": sig}).status_code == 403  # another scan
    assert api.get(f"/repos/{rid + 1}/report", params={"scan_id": sid, "sig": sig}).status_code == 403  # another repo
    assert api.get(f"/repos/{rid}/report", params={"sig": sig}).status_code == 403  # a link without its scan id
    assert api.get(f"/repos/{rid}/report", params={"scan_id": sid, "sig": readiness.sign_link("other-secret", rid, sid)}).status_code == 403
    monkeypatch.delenv("DPDP_API_TOKEN")
    assert api.get(good).status_code == 403  # no secret on the engine: no link is valid


def test_a_link_for_one_repo_never_opens_another_repos_report(api, monkeypatch):
    rid, sid = scanned(api)
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", "acme/tutornest,acme/other")
    other = api.post("/repos", json={"full_name": "acme/other", "actor": "U1"}, headers=TOKEN).json()["id"]
    sig = link(api, rid)["url"].split("sig=")[1]
    r = api.get(f"/repos/{other}/report", params={"scan_id": sid, "sig": sig})
    assert r.status_code == 403


def test_without_a_token_or_link_the_report_is_refused(api):
    rid, sid = scanned(api)
    assert api.get(f"/repos/{rid}/report").status_code == 401
    assert api.get(f"/repos/{rid}/report", headers={"X-DPDP-Token": "wrong"}).status_code == 401
    assert api.post(f"/repos/{rid}/report-link", json={}).status_code == 401
    assert api.post("/repos/99/report-link", json={}, headers=TOKEN).status_code == 404
    assert api.post(f"/repos/{rid}/report-link", json={"scan_id": "S-999"}, headers=TOKEN).status_code == 404


def test_link_helpers_are_strict():
    sig = readiness.sign_link("s", 1, "S-001", now=1000)
    assert readiness.check_link("s", sig, 1, "S-001", now=1000 + 899) and not readiness.check_link("s", sig, 1, "S-001", now=1000 + 901)
    assert not readiness.check_link("s", sig, 2, "S-001", now=1000) and not readiness.check_link("s", sig, 1, "S-002", now=1000)
    assert not readiness.check_link("", readiness.sign_link("", 1, "S-001", now=1000), 1, "S-001", now=1000)
    for bad in ("", "x", "a.b", sig.split(".")[0], "." + sig.split(".")[1]):
        assert not readiness.check_link("s", bad, 1, "S-001", now=1000)


# ---- the audit trail line

def test_the_audit_line_says_intact_or_names_the_first_bad_event(api):
    rid, sid = scanned(api)
    html = api.get(f"/repos/{rid}/report", headers=TOKEN).text
    n = api.get("/audit/verify").json()["checked"]
    assert f"Audit chain intact: {n} events checked." in html and "BROKEN" not in html
    api.store.run("UPDATE events SET result='edited' WHERE id=2")
    j = api.get(f"/repos/{rid}/report", params={"format": "json"}, headers=TOKEN).json()
    assert j["audit"]["chain_ok"] is False and j["audit"]["first_bad"] == 2 and j["audit"]["chain_checked"] == 1
    html = api.get(f"/repos/{rid}/report", headers=TOKEN).text
    assert "Audit chain BROKEN: the first bad event is number 2" in html and "Audit chain intact" not in html


def test_a_verified_fix_is_reported_with_exactly_what_was_verified(api):
    rid, sid = scanned(api)
    hid = next(f["human_id"] for f in api.get("/findings", params={"limit": 500}).json()["items"] if f["check"] == "log_pii")
    r = api.post(f"/findings/{hid}/fix?mode=cached", json={"actor": "U9"}, headers=TOKEN)
    assert r.status_code == 200 and r.json()["record"]["status"] == "fixed"
    j = api.get(f"/repos/{rid}/report", params={"format": "json"}, headers=TOKEN).json()
    one = next(f for f in j["findings"] if f["human_id"] == hid)
    assert one["status"] == "fixed" and one["status_by"] == "U9" and one["status_reason"] == "verified fix"
    assert one["fix"]["verified"] is True and one["fix"]["text"].startswith("Verified (cached verified patch (replay))")
    assert "re-scan of the fixed copy: passed" in one["fix"]["text"] and "app tests: " in one["fix"]["text"]
    assert j["summary"]["by_status"]["fixed"] == 1 and j["summary"]["open_by_severity"] != j["summary"]["by_severity"]
