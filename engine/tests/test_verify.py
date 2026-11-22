import json
import subprocess
import tempfile
from pathlib import Path

import httpx
import pytest

from conftest import BACKEND, FRONTEND, seed_copy
from dpdp_lens.fixer.sandbox import Sandbox
from dpdp_lens.fixer.templates import V1, V3, V5, PatchError, Template, apply_template
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
    result = verify_fix(V1_FINDING, BACKEND, fresh_db, score_before=13, golden_dir=golden)
    fix = result.fix
    assert fix.verified and fix.rescan_passed and fix.tests_passed
    assert "get_admin_user" in fix.diff and fix.diff.startswith("--- a/app/main.py\n+++ b/app/main.py")
    assert (fix.score_before, fix.score_after) == (13, 33)  # re-scan: V1 gone, six other findings stay
    assert [f.check for f in result.rescan.findings] == [
        "api_idor", "db_plaintext_pii", "log_pii", "erasure_incomplete", "children_no_parental_consent", "missing_contact",
        "notice_drift"]
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
    result = verify_fix(V3_FINDING, BACKEND, fresh_db, score_before=13, golden_dir=golden)
    fix = result.fix
    assert fix.verified and fix.rescan_passed and fix.tests_passed
    assert '+    logger.info("signup ok user_id=%s", student_id)' in fix.diff
    assert '-    logger.info("signup email=%s aadhaar=%s", req.email, req.aadhaar)' in fix.diff
    assert (fix.score_before, fix.score_after) == (13, 23)  # log_pii (high) gone, the six others stay
    assert [f.check for f in result.rescan.findings] == [
        "api_pii_exposure", "api_idor", "db_plaintext_pii", "erasure_incomplete", "children_no_parental_consent",
        "missing_contact", "notice_drift"]
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
    noop = Template(check=V1.check, golden_id="V1", scanner="api_scan", edits=(("backend", "app/main.py", "# PLANTED V1\n", "# PLANTED V1\n"),))
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
    other = V1_FINDING.model_copy(update={"check": "db_plaintext_pii"})
    with pytest.raises(PatchError, match="no fix template"):
        verify_fix(other, BACKEND, fresh_db)


# --- V5: the frontend fix. Needs target-app/frontend with node_modules (npm install).
needs_node = pytest.mark.skipif(not (FRONTEND / "node_modules").is_dir(), reason="run npm install in target-app/frontend")
V5_FINDING = Finding(
    id="F-007", check="tracker_before_consent", layer="browser", severity="high", title="t", explanation="e", clauses=[],
    evidence=Evidence(kind="network", summary="s", location=Location(url="http://localhost:5173")))


def node_procs():
    return subprocess.run(["pgrep", "-fc", "http.server"], capture_output=True, text=True).stdout.strip()


@needs_node
def test_v5_fix_is_verified_on_a_patched_copy_of_the_frontend(tmp_path, fresh_db):
    golden, tree_before, dirs_before, procs_before = tmp_path / "golden", tree_hash(TARGET_APP), temp_dirs(), node_procs()
    result = verify_fix(V5_FINDING, BACKEND, fresh_db, score_before=8, golden_dir=golden)
    fix, checks = result.fix, [f.check for f in result.rescan.findings]
    assert fix.verified and fix.rescan_passed and fix.tests_passed
    assert "tracker_before_consent" not in checks
    assert "consent_bundled" in checks  # the patched page still rendered its form, so the browser scan really ran
    assert "--- a/frontend/index.html" in fix.diff and "--- a/frontend/src/App.jsx" in fix.diff
    assert "-    <script async src=\"https://connect.facebook.net/en_US/fbevents.js\"></script>" in fix.diff
    assert "+function loadTrackingPixel() {" in fix.diff
    assert load_golden("V5", golden)["verified"] is True
    assert tree_hash(TARGET_APP) == tree_before and temp_dirs() == dirs_before and node_procs() == procs_before


@needs_node
def test_a_frontend_patch_that_does_not_build_is_a_patch_error(tmp_path, fresh_db):
    broken = Template(check=V5.check, golden_id="V5", scanner="browser_scan", edits=(
        ("frontend", "src/App.jsx", "export default function App() {\n", "export default function App() {\n  const = ;\n"),))
    dirs_before, procs_before = temp_dirs(), node_procs()
    with pytest.raises(PatchError, match="does not build"):
        verify_fix(V5_FINDING, BACKEND, fresh_db, template=broken, golden_dir=tmp_path / "golden")
    assert load_golden("V5", tmp_path / "golden") is None and temp_dirs() == dirs_before and node_procs() == procs_before


@needs_node
def test_a_browser_scan_that_could_not_run_is_never_a_pass(tmp_path, fresh_db, monkeypatch):
    """If the patched page cannot be scanned, 'the tracker is gone' proves nothing, so verification must raise."""
    monkeypatch.setattr(Sandbox, "start_frontend", lambda self: "http://127.0.0.1:9")
    with pytest.raises(RuntimeError, match="could not run browser_scan"):
        verify_fix(V5_FINDING, BACKEND, fresh_db, golden_dir=tmp_path / "golden")
    assert load_golden("V5", tmp_path / "golden") is None


def test_frontend_patch_without_node_modules_raises_a_setup_error(tmp_path, fresh_db):
    import shutil
    bare = tmp_path / "frontend"
    shutil.copytree(FRONTEND, bare, ignore=shutil.ignore_patterns("node_modules", "dist"))
    with pytest.raises(RuntimeError, match="npm install"):
        verify_fix(V5_FINDING, BACKEND, fresh_db, frontend_dir=bare, golden_dir=tmp_path / "golden")


# --- V2, V7, V8: backend-only fixes, V6: frontend fix
def finding_for(check, layer, kind):
    return Finding(id="F-001", check=check, layer=layer, severity="high", title="t", explanation="e", clauses=[],
                   evidence=Evidence(kind=kind, summary="s", location=Location(url="http://localhost:8000")))


@pytest.mark.parametrize("check,gid,layer,kind", [
    ("api_idor", "V2", "api", "http"),
    ("erasure_incomplete", "V7", "db", "db"),
    ("children_no_parental_consent", "V8", "api", "http")])
def test_backend_fix_is_verified_and_leaves_nothing_behind(tmp_path, fresh_db, check, gid, layer, kind):
    golden, tree_before, dirs_before, procs_before = tmp_path / "golden", tree_hash(TARGET_APP), temp_dirs(), uvicorn_count()
    result = verify_fix(finding_for(check, layer, kind), BACKEND, fresh_db, golden_dir=golden)
    fix = result.fix
    assert fix.verified and fix.rescan_passed and fix.tests_passed and fix.diff
    assert check not in [f.check for f in result.rescan.findings]
    assert len(result.rescan.findings) >= 5  # the other findings are still there, only this one went
    assert load_golden(gid, golden)["verified"] is True
    assert tree_hash(TARGET_APP) == tree_before and temp_dirs() == dirs_before and uvicorn_count() == procs_before


@needs_node
def test_v6_fix_is_verified_on_a_patched_copy_of_the_frontend(tmp_path, fresh_db):
    golden, tree_before, dirs_before, procs_before = tmp_path / "golden", tree_hash(TARGET_APP), temp_dirs(), node_procs()
    result = verify_fix(finding_for("consent_bundled", "browser", "dom"), BACKEND, fresh_db, golden_dir=golden)
    fix, checks = result.fix, [f.check for f in result.rescan.findings]
    assert fix.verified and fix.rescan_passed and fix.tests_passed
    assert "consent_bundled" not in checks and "tracker_before_consent" in checks  # browser scan really ran, tracker not fixed here
    assert "+  const [agreed, setAgreed] = useState(false)" in fix.diff and "+                <span>I agree to the Terms</span>" in fix.diff
    assert load_golden("V6", golden)["verified"] is True
    assert tree_hash(TARGET_APP) == tree_before and temp_dirs() == dirs_before and node_procs() == procs_before
