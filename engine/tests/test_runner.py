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
        "api_pii_exposure", "api_idor", "db_plaintext_pii", "log_pii", "erasure_incomplete", "missing_contact"]
    assert [f.id for f in r.findings] == [f"F-00{i}" for i in range(1, 7)]
    assert all(f.clauses for f in r.findings)
    assert r.findings[0].clauses[0].ref == "Act s8(5)"
    assert (r.score, r.counts.critical, r.counts.high, r.counts.low) == (28, 2, 3, 1)  # 100 - 2*20 - 3*10 - 2
    assert r.notice_drift is None  # T13


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

    scanners = [("boom", boom), ("hang", hang), ("log_scan", lambda t, repo, db: log_scan.scan(repo))]
    r = scan(target, fresh_db, scanners=scanners, timeout=0.2)
    assert [(f.id, f.check) for f in r.findings] == [("F-001", "log_pii")]


def test_default_scanner_order():
    assert [n for n, _ in SCANNERS] == [
        "api_scan", "idor_probe", "db_scan", "log_scan", "erasure_scan", "contact_scan"]


def test_cli_scan_writes_valid_json(target, target_db, tmp_path, capsys):
    out = tmp_path / "scan.json"
    assert main(["scan", "--target", target, "--repo", str(BACKEND), "--db", str(target_db), "--out", str(out)]) == 0
    jsonschema.validate(json.loads(out.read_text()), SCHEMA)
    assert "score 28, 6 findings" in capsys.readouterr().out
