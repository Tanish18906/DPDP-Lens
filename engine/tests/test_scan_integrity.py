"""Block 01a: scan errors, coverage, static mode, scan caps, fingerprints."""
import re
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import BACKEND
from dpdp_lens.api import create_app
from dpdp_lens.checks import CHECKS
from dpdp_lens.fingerprint import RULES, fingerprint, fingerprints
from dpdp_lens.locator import Capped, _files
from dpdp_lens.runner import SCANNER_CHECKS, STATIC_SCANNERS, run_scan
from dpdp_lens.scanners import config_scan, frontend_scan, log_scan
from test_contract import load_sample

TARGET_APP = BACKEND.parent
CLEAN_APP = Path(__file__).parent / "fixtures" / "clean_app"
TUTORNEST_STATIC_CHECKS = {"log_pii", "config_secret_committed", "config_env_in_image", "config_container_root", "config_cors_wildcard",
                           "config_debug_enabled", "config_db_exposed", "fe_pii_in_storage", "consent_not_recorded"}
STATIC_CHECKS = TUTORNEST_STATIC_CHECKS | {
    "config_s3_public", "config_security_group_ingress_anywhere", "config_storage_unencrypted",
    "config_tf_hardcoded_secret", "config_k8s_privileged", "config_k8s_host_network", "config_k8s_secret_in_env",
}
LOG_SCAN = ("log_scan", lambda target, repo, db, fe: log_scan.scan(repo))


def static(path):
    return run_scan("", str(path), "", mode="static")


def copy_app(dest: Path) -> Path:
    shutil.copytree(TARGET_APP, dest, ignore=shutil.ignore_patterns("node_modules", "*.db", "__pycache__", "dist", "*.log", ".pytest_cache"))
    return dest


# ---- scan errors and coverage

def test_scanner_that_raises_gives_complete_false_and_a_scan_error():
    def boom(*_):
        raise RuntimeError("boom")

    errors = []
    r = run_scan("", str(CLEAN_APP), "", scanners=[("boom", boom), LOG_SCAN], errors=errors)
    assert r.complete is False
    assert [(e.scanner, e.kind, e.message) for e in r.scan_errors] == [("boom", "failed", "RuntimeError: boom")]
    assert errors == ["boom: RuntimeError: boom"]  # the legacy list still gets its entry (verify.py reads it)
    assert r.coverage.scanners_failed == ["boom"] and r.coverage.checks_run == ["log_pii"]


def test_scanner_that_sleeps_past_the_timeout_gives_kind_timeout():
    r = run_scan("", str(CLEAN_APP), "", scanners=[("hang", lambda *_: time.sleep(1)), LOG_SCAN], timeout=0.2)
    assert [(e.scanner, e.kind) for e in r.scan_errors] == [("hang", "timeout")]
    assert r.complete is False and "0.2" in r.scan_errors[0].message


def test_a_failed_scanner_is_in_neither_checks_run_nor_checks_skipped():
    def boom(*_):
        raise RuntimeError("x")

    r = run_scan("", str(CLEAN_APP), "", scanners=[("api_scan", boom), LOG_SCAN])
    cov = r.coverage
    assert cov.mode == "full" and cov.scanners_failed == ["api_scan"] and cov.checks_run == ["log_pii"]
    assert "api_pii_exposure" not in cov.checks_run + cov.checks_skipped
    assert set(cov.checks_run + cov.checks_skipped) == set(CHECKS) - {"api_pii_exposure"}


def test_clean_scan_is_complete_and_has_a_version():
    r = run_scan("", str(CLEAN_APP), "", scanners=[LOG_SCAN])
    assert r.complete is True and r.scan_errors == [] and r.scanner_version


def test_scanner_check_map_covers_every_check_once():
    mapped = [c for checks in SCANNER_CHECKS.values() for c in checks]
    assert sorted(mapped) == sorted(CHECKS)


def test_api_scan_response_carries_scan_errors_and_complete(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "x.db").write_text("")

    def boom(*_):
        raise RuntimeError("boom")

    def scan_fn(target, repo, db, scan_id, **_):
        return run_scan(target, repo, db, scanners=[("boom", boom)], scan_id=scan_id)

    client = TestClient(create_app(scan_fn=scan_fn, repo_root=tmp_path))
    sid = client.post("/scan", json={"target_url": "http://127.0.0.1:1", "repo_path": "app", "db_path": "x.db"}).json()["scan_id"]
    body = client.get(f"/scan/{sid}").json()
    assert body["complete"] is False and body["scan_errors"][0]["scanner"] == "boom"


def test_failing_browser_scan_is_reported_and_the_score_is_not_clean(target, target_db, with_late_scanners):
    """Without a frontend the browser scan cannot run. Before block 01a that only went to the log."""
    r = run_scan(target, str(BACKEND), str(target_db))
    assert r.complete is False
    assert [(e.scanner, e.kind) for e in r.scan_errors] == [("browser_scan", "failed")]
    assert r.coverage.scanners_failed == ["browser_scan"]
    assert not {"tracker_before_consent", "consent_bundled"} & set(r.coverage.checks_run + r.coverage.checks_skipped)


def test_full_scan_regression_without_frontend(target, target_db, with_late_scanners):
    """The full scan of TutorNest does not change (the live 21 findings, score 13 case is checked by scripts/run_gates.sh)."""
    r = run_scan(target, str(BACKEND), str(target_db))
    assert len(r.findings) == 19 and [f.id for f in r.findings] == [f"F-{i:03d}" for i in range(1, 20)]
    assert (r.score, r.counts.critical, r.counts.high, r.counts.medium, r.counts.low) == (20, 2, 9, 7, 1)
    assert all(re.fullmatch(r"[0-9a-f]{16}", f.fingerprint) for f in r.findings)
    assert len({f.fingerprint for f in r.findings}) == 19
    assert {f.check: f.proof for f in r.findings}["api_idor"] == "probed"


# ---- static mode

def test_static_mode_on_the_clean_app_has_no_findings(with_late_scanners):
    r = static(CLEAN_APP)
    assert r.findings == [] and r.complete is True and r.score == 100
    assert r.coverage.mode == "static" and set(r.coverage.checks_run) == STATIC_CHECKS


def test_static_mode_on_target_app_runs_only_static_checks(with_late_scanners):
    r = static(TARGET_APP)
    assert r.complete is True and r.notice_drift is None
    assert {f.check for f in r.findings} == TUTORNEST_STATIC_CHECKS
    assert set(r.coverage.checks_run) == STATIC_CHECKS
    assert set(r.coverage.checks_skipped) == set(CHECKS) - STATIC_CHECKS  # includes consent_no_withdrawal
    assert "consent_no_withdrawal" in r.coverage.checks_skipped
    assert r.scan_errors == [] and r.target == ""


def test_static_mode_does_not_call_a_live_scanner(monkeypatch, with_late_scanners):
    import dpdp_lens.runner as runner

    def never(*_):
        raise AssertionError("live scanner called in static mode")

    monkeypatch.setattr(runner, "SCANNERS", [(n, never if n not in STATIC_SCANNERS else fn) for n, fn in runner.SCANNERS])
    assert static(CLEAN_APP).complete is True


# ---- walkers

def test_walkers_skip_build_folders_and_symlinks_that_leave_the_root(tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("import logging\nlogging.getLogger('a').info('x', email)\n")
    repo = tmp_path / "repo"
    for d in ("dist", "build", ".venv", "node_modules", ".git", "__pycache__"):
        (repo / d).mkdir(parents=True)
        (repo / d / "bad.py").write_text("import logging\nlog = logging.getLogger('a')\nlog.info('x', email)\n")
    (repo / "link.py").symlink_to(outside)
    (repo / "ok.py").write_text("x = 1\n")
    assert list(_files(repo)) == ["ok.py"]
    assert log_scan.scan(str(repo)) == []


def test_symlink_inside_the_root_is_still_scanned(tmp_path):
    (tmp_path / "real.py").write_text("x = 1\n")
    (tmp_path / "alias.py").symlink_to(tmp_path / "real.py")
    assert list(_files(tmp_path)) == ["alias.py", "real.py"]


def test_more_than_the_file_limit_is_a_cap_not_a_clean_scan(tmp_path):
    for i in range(6):
        (tmp_path / f"f{i}.py").write_text("")
    with pytest.raises(Capped):
        list(_files(tmp_path, limit=5))
    assert len(list(_files(tmp_path, limit=6))) == 6


BIG = "#" * 1_000_001


def test_file_over_1mb_is_skipped_and_recorded_but_other_files_still_give_findings(tmp_path):
    (tmp_path / "big.py").write_text("x = 1\n" + BIG)
    (tmp_path / "ok.py").write_text("import logging\nlog = logging.getLogger('a')\nlog.info('x', email)\n")
    r = run_scan("", str(tmp_path), "", scanners=[LOG_SCAN])
    assert [f.check for f in r.findings] == ["log_pii"]  # the other file was still scanned
    assert [(e.scanner, e.kind) for e in r.scan_errors] == [("log_scan", "capped")] and r.complete is False
    assert "big.py" in r.scan_errors[0].message
    # the scanner did not see everything, so its check is not "run": a later ingest must not resolve findings from it
    assert r.coverage.checks_run == [] and r.coverage.scanners_failed == ["log_scan"]


def test_noise_files_over_1mb_are_skipped_silently(tmp_path):
    for rel in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "frontend/app.min.js", "frontend/app.js.map", "dist/big.js",
                "node_modules/x/big.py", "build/big.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(BIG)
    (tmp_path / "frontend" / "ok.js").write_text("const a = 1;\n")
    scanners = [LOG_SCAN, ("config_scan", lambda t, repo, db, fe: config_scan.scan(repo)),
                ("frontend_scan", lambda t, repo, db, fe: frontend_scan.scan(repo))]
    r = run_scan("", str(tmp_path), "", scanners=scanners)
    assert r.scan_errors == [] and r.complete is True
    assert set(r.coverage.checks_run) == {"log_pii", "fe_pii_in_storage"} | {c for c in CHECKS if c.startswith("config_")}


def test_big_file_that_is_not_noise_marks_the_other_walkers_incomplete_too(tmp_path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "bundle.js").write_text(BIG)
    (tmp_path / "settings.yml").write_text("a: 1\n" + BIG)
    r = run_scan("", str(tmp_path), "", scanners=[("config_scan", lambda t, repo, db, fe: config_scan.scan(repo)),
                                                   ("frontend_scan", lambda t, repo, db, fe: frontend_scan.scan(repo))])
    assert sorted((e.scanner, e.kind) for e in r.scan_errors) == [("config_scan", "capped"), ("frontend_scan", "capped")]
    assert r.complete is False and r.coverage.checks_run == []


# ---- fingerprints

def test_every_registered_check_has_a_fingerprint_rule():
    assert set(RULES) == set(CHECKS)


def test_same_scan_twice_gives_equal_fingerprints(with_late_scanners):
    a, b = static(TARGET_APP), static(TARGET_APP)
    assert [f.fingerprint for f in a.findings] == [f.fingerprint for f in b.findings] and a.findings


def test_a_copy_at_another_path_gives_equal_fingerprints(tmp_path, with_late_scanners):
    here = static(TARGET_APP)
    there = static(copy_app(tmp_path / "elsewhere" / "target-app"))
    assert [(f.check, f.fingerprint) for f in here.findings] == [(f.check, f.fingerprint) for f in there.findings]


def test_line_shifts_do_not_change_fingerprints(tmp_path, with_late_scanners):
    before = static(TARGET_APP)
    copy = copy_app(tmp_path / "target-app")
    for rel in ("backend/app/main.py", "frontend/src/App.jsx"):
        f = copy / rel
        f.write_text("\n\n\n" + f.read_text() if rel.endswith(".py") else "// shifted\n// shifted\n" + f.read_text())
    after = static(copy)
    assert [f.evidence.location.line for f in before.findings] != [f.evidence.location.line for f in after.findings]
    assert [f.fingerprint for f in before.findings] == [f.fingerprint for f in after.findings]


def test_the_three_secret_findings_have_three_fingerprints(with_late_scanners):
    secrets = [f for f in static(TARGET_APP).findings if f.check == "config_secret_committed"]
    assert len(secrets) == 3 and len({f.fingerprint for f in secrets}) == 3


def test_host_and_port_are_not_part_of_the_fingerprint():
    f = load_sample().findings[0]
    moved = f.model_copy(update={"evidence": f.evidence.model_copy(update={"location": f.evidence.location.model_copy(
        update={"url": "http://10.1.2.3:9999/api/students"})})})
    assert f.evidence.location.url != moved.evidence.location.url and fingerprint(f) == fingerprint(moved)


def test_log_fingerprint_uses_the_file_and_sorted_field_names_not_the_line():
    f = next(x for x in load_sample().findings if x.check == "log_pii")
    swap = lambda s, line=1: f.model_copy(update={"evidence": f.evidence.model_copy(update={  # noqa: E731
        "summary": s, "location": f.evidence.location.model_copy(update={"line": line})})})
    assert fingerprint(swap("Log call includes email, aadhaar", 5)) == fingerprint(swap("Log call includes aadhaar, email", 99))
    assert fingerprint(swap("Log call includes email")) != fingerprint(swap("Log call includes email, aadhaar"))


def test_two_identical_findings_in_one_scan_do_not_share_a_fingerprint():
    f = load_sample().findings[0]
    fps = fingerprints([f, f, f])
    assert fps[0] == fingerprint(f) and len(set(fps)) == 3
