import json
import sqlite3

import httpx

from dpdp_lens.scanners import children_scan


def count(db, table):
    con = sqlite3.connect(db)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


def test_children_scan_finds_v8_and_cleans_up(fresh_target):
    url, db = fresh_target
    before = count(db, "students")
    findings = children_scan.scan(url, str(db))
    assert [f.check for f in findings] == ["children_no_parental_consent"]
    f = findings[0]
    assert f.severity == "high" and f.layer == "api" and f.evidence.kind == "http"
    assert f.evidence.location.url.endswith("/api/signup")
    assert "probe-" not in json.dumps(f.model_dump())  # no raw marker values
    assert count(db, "students") == before  # probe row removed


def test_children_scan_repeats_with_same_result(fresh_target):
    url, db = fresh_target
    assert children_scan.scan(url, str(db)) == children_scan.scan(url, str(db))


def stub(status, seen):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(status, json={"id": 1})
    return httpx.MockTransport(handler)


def test_minor_signup_rejected_is_not_flagged(tmp_path):
    seen = []
    assert children_scan.scan("http://stub", str(tmp_path / "x.db"), transport=stub(422, seen)) == []
    assert seen[0]["age"] == 14 and "parent_pan" not in seen[0]  # what the probe really sent


def test_minor_signup_accepted_is_flagged(tmp_path):
    findings = children_scan.scan("http://stub", str(tmp_path / "x.db"), transport=stub(201, []))
    assert len(findings) == 1 and "201" in findings[0].evidence.summary
