import hashlib
import json
import re

import pytest
from fastapi.testclient import TestClient

from conftest import BACKEND
from dpdp_lens import runner
from dpdp_lens.api import create_app
from dpdp_lens.fixer.notice_align import MARKER, PURPOSE_PLACEHOLDER, align_notice, pending_inputs, render_section
from dpdp_lens.fixer.verify import Verification, verify_fix
from dpdp_lens.htmltext import visible_text
from dpdp_lens.models import Fix, NoticeDrift, ObservedField, ScanResult, compute_counts, compute_score
from dpdp_lens.scanners import notice_drift
from dpdp_lens.scanners.notice_drift import declared_fields
from test_sandbox import tree_hash

NOTICE = BACKEND / "static" / "notice.html"
DRIFT = NoticeDrift(
    declared=["name", "email", "phone"],
    observed=[ObservedField(field="dob", where=["db:students.dob", "api:/api/students"]),
              ObservedField(field="aadhaar", where=["db:students.aadhaar", "api:/api/students", "request:facebook.com"])],
    undeclared=["dob", "aadhaar"])


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- the generator
def test_align_is_idempotent():
    once = align_notice(NOTICE.read_text(), DRIFT)
    assert once != NOTICE.read_text() and once.count(MARKER) == 1
    assert align_notice(once, DRIFT) == once


def test_every_purpose_is_the_placeholder_and_none_is_invented():
    section = render_section(DRIFT)
    purposes = re.findall(r"Purpose: ([^<]*)</li>", section)
    assert purposes == [PURPOSE_PLACEHOLDER] * 2 and section.count("Purpose:") == 2
    text = visible_text(section).lower()
    for invented in ("tutoring", "marketing", "to provide", "authentication", "advertis", "analytics", "verify"):
        assert invented not in text


def test_section_names_layers_and_hosts_but_no_file_paths():
    section = render_section(DRIFT)
    assert "Handled in: Database, API responses" in section
    assert "<h3>Shared with</h3>" in section and "<li>facebook.com</li>" in section
    assert "students" not in section and "/api" not in section and "db:" not in section


def test_the_patched_notice_declares_every_field_and_keeps_the_old_ones():
    patched = align_notice(NOTICE.read_text(), DRIFT)
    assert declared_fields(patched) == ["name", "email", "phone", "dob", "aadhaar"]
    assert patched.index(MARKER) < patched.lower().rindex("</body>")


def test_field_names_are_escaped():
    d = NoticeDrift(declared=[], observed=[ObservedField(field="<b>x</b>", where=["request:<i>h</i>"])], undeclared=["<b>x</b>"])
    section = render_section(d)
    assert "<b>x" not in section and "<i>h" not in section and "&lt;b&gt;" in section


def test_pending_inputs_one_purpose_per_field():
    assert pending_inputs(DRIFT) == ["purpose for dob", "purpose for aadhaar"]


def test_clean_control_nothing_to_align_and_no_fix_offered(monkeypatch, target, target_db):
    html = "<html><body><ul><li>Name</li></ul></body></html>"
    clean = NoticeDrift(declared=["name"], observed=[ObservedField(field="name", where=["db:t.name"])], undeclared=[])
    assert align_notice(html, clean) == html
    monkeypatch.setattr(notice_drift, "build", lambda t, d: clean)
    r = runner.run_scan(target, str(BACKEND), str(target_db))
    assert "notice_drift" not in [f.check for f in r.findings]  # no finding, so there is nothing to fix


# --- end to end on the real target
def test_fix_notice_drift_is_verified_and_the_original_is_untouched(tmp_path, target, target_db):
    drift = notice_drift.build(target, str(target_db))
    assert drift.undeclared == ["dob", "aadhaar", "parent_pan"]
    finding = notice_drift.finding(drift, f"{target}/notice")
    app_before, notice_before = tree_hash(BACKEND.parent), sha(NOTICE)
    golden = tmp_path / "golden"
    result = verify_fix(finding, BACKEND, target_db, score_before=0, golden_dir=golden, drift=drift)
    fix = result.fix
    assert fix.verified and fix.rescan_passed and fix.tests_passed
    assert (fix.kind, fix.pending_inputs) == ("notice_align", ["purpose for dob", "purpose for aadhaar", "purpose for parent_pan"])
    assert fix.diff.startswith("--- a/static/notice.html\n+++ b/static/notice.html") and "+  " + MARKER in fix.diff
    assert PURPOSE_PLACEHOLDER in fix.diff
    assert [s["step"] for s in result.log["steps"]] == ["copy", "patch", "start", "rescan", "tests"]
    assert result.log["rescan_check"] == "notice_drift" and result.log["rescan_findings"] == 0 and result.rescan is None
    saved = json.loads((golden / "NOTICE.json").read_text())
    assert saved["verified"] and saved["kind"] == "notice_align" and saved["pending_inputs"] == fix.pending_inputs
    assert sha(NOTICE) == notice_before and tree_hash(BACKEND.parent) == app_before  # original byte identical


def test_no_drift_block_is_a_patch_error(target, target_db):
    from dpdp_lens.fixer.templates import PatchError
    finding = notice_drift.finding(NoticeDrift(declared=[], observed=[], undeclared=["dob"]), f"{target}/notice")
    with pytest.raises(PatchError):
        verify_fix(finding, BACKEND, target_db, drift=None)


# --- through the fix route
def _client(tmp_path, fix_fn, golden_dir):
    drift_finding = notice_drift.finding(DRIFT, "http://localhost:8000/notice").model_copy(update={"id": "F-001", "fix": Fix(available=True)})

    def scan_fn(target, repo, db, scan_id):
        fs = [drift_finding]
        return ScanResult(scan_id=scan_id, target=target, scanned_at="2026-11-23T00:00:00+00:00", score=compute_score(fs),
                          counts=compute_counts(fs), findings=fs, notice_drift=DRIFT)

    (tmp_path / "x.db").write_text("")
    c = TestClient(create_app(scan_fn=scan_fn, repo_root=tmp_path, fix_fn=fix_fn, golden_dir=golden_dir))
    assert c.post("/scan", json={"target_url": "http://localhost:8000", "repo_path": ".", "db_path": "x.db"}).status_code == 200
    return c


def test_route_passes_the_drift_block_and_returns_the_kind(tmp_path):
    seen = {}

    def fake(finding, repo, db, **kw):
        seen.update(kw)
        fix = Fix(available=True, diff="d", verified=True, rescan_passed=True, tests_passed=True,
                  kind="notice_align", pending_inputs=pending_inputs(DRIFT))
        return Verification(fix=fix, rescan=None, tests_output="")

    body = _client(tmp_path, fake, tmp_path).post("/findings/F-001/fix", params={"scan_id": "S-001"}).json()
    assert seen["drift"] == DRIFT and body["mode"] == "live"
    assert body["finding"]["status"] == "verified_fixed" and body["finding"]["fix"]["kind"] == "notice_align"
    assert body["finding"]["fix"]["pending_inputs"] == ["purpose for dob", "purpose for aadhaar"]
    assert body["score_after"] == 100


def test_route_cached_golden_for_notice_drift(tmp_path):
    (tmp_path / "NOTICE.json").write_text(json.dumps({
        "golden_id": "NOTICE", "check": "notice_drift", "source": "live", "diff": "--- g\n", "verified": True,
        "rescan_passed": True, "tests_passed": True, "kind": "notice_align", "pending_inputs": ["purpose for dob"]}))
    body = _client(tmp_path, None, tmp_path).post("/findings/F-001/fix", params={"scan_id": "S-001", "mode": "cached"}).json()
    assert body["mode"] == "cached_golden" and body["finding"]["fix"]["pending_inputs"] == ["purpose for dob"]
