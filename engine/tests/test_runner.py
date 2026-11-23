import json
import time

import jsonschema

from conftest import BACKEND
from dpdp_lens.__main__ import main
from dpdp_lens.runner import CLAUSES, SCANNERS, run_scan
from dpdp_lens.scanners import log_scan

SCHEMA = json.loads((CLAUSES.parent / "finding.schema.json").read_text())


def scan(target, db, **kw):
    return run_scan(target, str(BACKEND), str(db), **kw)


def test_scan_finds_all_current_violations_with_ids_clauses_and_score(target, target_db):
    r = scan(target, target_db)
    assert [f.check for f in r.findings] == [
        "api_pii_exposure", "api_idor", "db_plaintext_pii", "log_pii", "erasure_incomplete", "children_no_parental_consent",
        "missing_contact", "notice_drift"]
    assert [f.id for f in r.findings] == [f"F-00{i}" for i in range(1, 9)]
    assert all(f.clauses for f in r.findings)
    assert r.findings[0].clauses[0].ref == "Act s8(5)"
    assert (r.score, r.counts.critical, r.counts.high, r.counts.medium, r.counts.low) == (57, 2, 4, 1, 1)  # 100 - 2*10 - 4*5 - 2 - 1
    assert r.notice_drift.undeclared == ["dob", "aadhaar", "parent_pan"]


def test_config_findings_come_after_the_first_ten_so_their_ids_do_not_move(target, target_db, with_late_scanners):
    r = scan(target, target_db)
    first = [f.check for f in r.findings[:8]]
    assert first[-1] == "notice_drift" and [f.id for f in r.findings[:8]] == [f"F-00{i}" for i in range(1, 9)]
    config = r.findings[8:]
    assert sorted(f.check for f in config) == sorted([
        "config_secret_committed"] * 3 + ["config_env_in_image", "config_container_root", "config_cors_wildcard",
                                          "config_debug_enabled", "config_db_exposed"])  # .env, compose, auth.py (a real one)
    assert all(f.layer == "config" and f.clauses and f.evidence.location.line > 0 for f in config)
    assert not any(v in r.model_dump_json() for v in ("tutornest-demo-secret-123", "admin123", "mail-demo-pass-456", "hackathon-insecure"))


def test_scan_json_validates_against_contract_schema(target, target_db):
    jsonschema.validate(json.loads(scan(target, target_db).model_dump_json()), SCHEMA)


def test_scan_is_deterministic(target, target_db):
    a, b = scan(target, target_db), scan(target, target_db)
    assert a.model_dump(exclude={"scanned_at"}) == b.model_dump(exclude={"scanned_at"})


def test_failing_or_hanging_scanner_does_not_kill_the_scan(target, fresh_db):
    def boom(*_):
        raise RuntimeError("boom")

    def hang(*_):
        time.sleep(1)

    scanners = [("boom", boom), ("hang", hang), ("log_scan", lambda t, repo, db, fe: log_scan.scan(repo))]
    errors = []
    r = scan(target, fresh_db, scanners=scanners, timeout=0.2, errors=errors)
    assert errors == ["boom: RuntimeError: boom", "hang: timed out after 0.2s"]
    assert [(f.id, f.check) for f in r.findings] == [("F-001", "log_pii")]


def test_default_scanner_order():
    assert [n for n, _ in SCANNERS] == [
        "api_scan", "idor_probe", "db_scan", "log_scan", "erasure_scan", "children_scan", "contact_scan", "browser_scan"]


def test_cli_scan_writes_valid_json(target, target_db, tmp_path, capsys):
    out = tmp_path / "scan.json"
    assert main(["scan", "--target", target, "--repo", str(BACKEND), "--db", str(target_db), "--out", str(out)]) == 0
    jsonschema.validate(json.loads(out.read_text()), SCHEMA)
    assert "score 57, 8 findings" in capsys.readouterr().out
