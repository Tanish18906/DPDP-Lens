import json
import subprocess
import tempfile
from pathlib import Path

import httpx
import pytest

from conftest import BACKEND, seed_copy
from dpdp_lens.fixer.sandbox import Sandbox
from dpdp_lens.fixer.templates import V1, V3, PatchError, Template, apply_template
from dpdp_lens.fixer.verify import load_golden, verify_fix
from dpdp_lens.models import Evidence, Finding, Location
from test_sandbox import tree_hash

TARGET_APP = BACKEND.parent
V1_FINDING = Finding(
    id="F-001", check="api_pii_exposure", layer="api", severity="critical", title="t", explanation="e", clauses=[],
    evidence=Evidence(kind="http", summary="s", location=Location(url="http://localhost:8000/api/students")))


def temp_dirs():
    return set(Path(tempfile.gettempdir()).glob("dpdp-lens-*"))


def uvicorn_count():
    """Number of running target backends (a dev backend may be running, so tests compare before and after)."""
    return subprocess.run(["pgrep", "-fc", "uvicorn app.main:app"], capture_output=True, text=True).stdout.strip()


def test_v1_fix_is_verified(tmp_path, fresh_db):
    golden, tree_before, dirs_before, procs_before = tmp_path / "golden", tree_hash(TARGET_APP), temp_dirs(), uvicorn_count()
    result = verify_fix(V1_FINDING, BACKEND, fresh_db, score_before=28, golden_dir=golden)
    fix = result.fix
    assert fix.verified and fix.rescan_passed and fix.tests_passed
    assert "get_admin_user" in fix.diff and fix.diff.startswith("--- a/app/main.py\n+++ b/app/main.py")
    assert (fix.score_before, fix.score_after) == (28, 48)  # re-scan: V1 gone, five other findings stay
    assert [f.check for f in result.rescan.findings] == [
        "api_idor", "db_plaintext_pii", "log_pii", "erasure_incomplete", "missing_contact"]
    assert "passed" in result.tests_output
    # golden saved from the verified live run only
    saved = load_golden("V1", golden)
    assert saved["verified"] is True and saved["source"] == "live" and saved["diff"] == fix.diff
    assert "aadhaar=" not in json.dumps(saved)
    # nothing left behind, original folder untouched
    assert tree_hash(TARGET_APP) == tree_before and temp_dirs() == dirs_before
    assert uvicorn_count() == procs_before


V3_FINDING = Finding(
    id="F-004", check="log_pii", layer="code", severity="high", title="t", explanation="e", clauses=[],
    evidence=Evidence(kind="code", summary="s", location=Location(file="app/main.py", line=86)))


def test_v3_fix_is_verified_and_the_log_holds_no_personal_data(tmp_path, fresh_db):
    golden, tree_before, dirs_before = tmp_path / "golden", tree_hash(TARGET_APP), temp_dirs()
    result = verify_fix(V3_FINDING, BACKEND, fresh_db, score_before=28, golden_dir=golden)
    fix = result.fix
    assert fix.verified and fix.rescan_passed and fix.tests_passed
    assert '+    logger.info("signup ok user_id=%s", student_id)' in fix.diff
    assert '-    logger.info("signup email=%s aadhaar=%s", req.email, req.aadhaar)' in fix.diff
    assert (fix.score_before, fix.score_after) == (28, 38)  # log_pii (high) gone, the five others stay
    assert [f.check for f in result.rescan.findings] == [
        "api_pii_exposure", "api_idor", "db_plaintext_pii", "erasure_incomplete", "missing_contact"]
    assert load_golden("V3", golden)["verified"] is True
    assert tree_hash(TARGET_APP) == tree_before and temp_dirs() == dirs_before


@pytest.mark.parametrize("patched", [False, True])
def test_signup_log_before_and_after_the_v3_patch(fresh_db, patched):
    """Control: the unpatched app writes the email and Aadhaar to its log file. The patched app does not."""
    email, aadhaar = "log-probe@example.test", "234123412346"
    with Sandbox(BACKEND, fresh_db) as sb:
        if patched:
            apply_template(V3, sb.repo)
        url = sb.start()
        r = httpx.post(f"{url}/api/signup", json={"name": "Log Probe", "email": email, "phone": "9000000003",
                                                  "dob": "2000-01-01", "age": 25, "aadhaar": aadhaar, "password": "ProbePass123!"})
        assert r.status_code == 201
        log = (sb.repo / "tutornest.log").read_text()
    if patched:
        assert email not in log and aadhaar not in log and f"signup ok user_id={r.json()['id']}" in log
    else:
        assert email in log and aadhaar in log


def test_noop_patch_is_not_verified_even_if_tests_pass(tmp_path, fresh_db):
    noop = Template(check=V1.check, golden_id="V1", file=V1.file, edits=(("# PLANTED V1\n", "# PLANTED V1\n"),))
    fix = verify_fix(V1_FINDING, BACKEND, fresh_db, template=noop, golden_dir=tmp_path / "golden").fix
    assert fix.tests_passed is True and fix.rescan_passed is False and fix.verified is False
    assert load_golden("V1", tmp_path / "golden") is None  # never saved from an unverified run


def test_failing_app_tests_block_verification(tmp_path, fresh_db):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_fail.py").write_text("def test_fail():\n    assert False\n")
    fix = verify_fix(V1_FINDING, BACKEND, fresh_db, tests_dir=tests, golden_dir=tmp_path / "golden").fix
    assert fix.rescan_passed is True and fix.tests_passed is False and fix.verified is False
    assert load_golden("V1", tmp_path / "golden") is None


def test_missing_snippet_is_an_error_and_cleans_up(tmp_path):
    backend, db, _ = seed_copy(tmp_path)
    main = backend / "app/main.py"
    main.write_text(main.read_text().replace("def list_students_public():", "def renamed():"))
    dirs_before = temp_dirs()
    with pytest.raises(PatchError):
        verify_fix(V1_FINDING, backend, db, tests_dir=tmp_path / "tests")
    assert temp_dirs() == dirs_before


def test_unknown_check_has_no_template(tmp_path, fresh_db):
    other = V1_FINDING.model_copy(update={"check": "api_idor"})
    with pytest.raises(PatchError, match="no fix template"):
        verify_fix(other, BACKEND, fresh_db)
