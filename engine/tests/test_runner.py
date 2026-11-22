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


def test_scan_finds_v1_to_v4_with_ids_clauses_and_score(target, fresh_db):
    r = scan(target, fresh_db)
    assert [f.check for f in r.findings] == ["api_pii_exposure", "api_idor", "db_plaintext_pii", "log_pii"]
    assert [f.id for f in r.findings] == ["F-001", "F-002", "F-003", "F-004"]
    assert all(f.clauses for f in r.findings)
    assert r.findings[0].clauses[0].ref == "Act s8(5)"
    assert (r.score, r.counts.critical, r.counts.high) == (40, 2, 2)  # 100 - 2*20 - 2*10
    assert r.notice_drift is None  # T13


def test_scan_json_validates_against_contract_schema(target, fresh_db):
    jsonschema.validate(json.loads(scan(target, fresh_db).model_dump_json()), SCHEMA)


def test_scan_is_deterministic(target, fresh_db):
    a, b = scan(target, fresh_db), scan(target, fresh_db)
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
    assert [n for n, _ in SCANNERS] == ["api_scan", "idor_probe", "db_scan", "log_scan"]


def test_cli_scan_writes_valid_json(target, fresh_db, tmp_path, capsys):
    out = tmp_path / "scan.json"
    assert main(["scan", "--target", target, "--repo", str(BACKEND), "--db", str(fresh_db), "--out", str(out)]) == 0
    jsonschema.validate(json.loads(out.read_text()), SCHEMA)
    assert "score 40, 4 findings" in capsys.readouterr().out
