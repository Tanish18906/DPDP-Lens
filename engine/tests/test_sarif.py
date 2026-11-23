import json
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import BACKEND
from dpdp_lens.__main__ import main
from dpdp_lens.api import create_app
from dpdp_lens.models import Clause, Evidence, Finding, Fix, Location, ScanResult, compute_counts, compute_score
from dpdp_lens.sarif import to_sarif

SAMPLE = ScanResult.model_validate_json((Path(__file__).resolve().parents[2] / "contract" / "sample-scan.json").read_text())


def finding(fid, check="log_pii", severity="high", status="open", loc=None, masked="a***@x.test"):
    return Finding(id=fid, check=check, layer="code", severity=severity, title="Title", explanation="Explanation.",
                   clauses=[Clause(ref="Act s8(5)", note="reasonable security safeguards")],
                   evidence=Evidence(kind="code", summary="Summary", masked_sample=masked, location=loc or Location(file="app/main.py", line=87)),
                   status=status, fix=Fix(available=True))


def scan_of(findings):
    return ScanResult(scan_id="S-009", target="http://localhost:8000", scanned_at="2026-11-23T08:00:00+05:30",
                      score=compute_score(findings), counts=compute_counts(findings), findings=findings)


def test_sarif_shape_and_one_result_per_open_finding():
    s = to_sarif(SAMPLE)
    assert s["version"] == "2.1.0" and "sarif-2.1.0" in s["$schema"] and len(s["runs"]) == 1
    run = s["runs"][0]
    assert run["tool"]["driver"]["name"] == "DPDP Lens"
    open_ids = [f.id for f in SAMPLE.findings if f.status == "open" and f.evidence.location.file]  # live findings have no file and stay out
    assert [r["properties"]["findingId"] for r in run["results"]] == open_ids
    rule_ids = [r["id"] for r in run["tool"]["driver"]["rules"]]
    assert len(rule_ids) == len(set(rule_ids)) and {r["ruleId"] for r in run["results"]} <= set(rule_ids)
    for r in run["results"]:
        assert r["message"]["text"] and r["locations"] and r["level"] in ("error", "warning", "note")
    assert "not a compliance certificate" in run["properties"]["note"]


def test_levels_and_clauses_and_fixed_findings_are_left_out():
    s = to_sarif(scan_of([finding("F-001", severity="critical"), finding("F-002", "a", "medium"), finding("F-003", "b", "low"),
                          finding("F-004", "c", "high", status="verified_fixed")]))
    results = s["runs"][0]["results"]
    assert [r["level"] for r in results] == ["error", "warning", "note"]
    assert results[0]["properties"]["clauses"] == ["Act s8(5)"]
    assert "Act s8(5): reasonable security safeguards" in s["runs"][0]["tool"]["driver"]["rules"][0]["help"]["text"]


def test_locations_are_repo_relative_files_only():
    file_loc = to_sarif(scan_of([finding("F-001")]))["runs"][0]["results"][0]["locations"][0]
    assert file_loc["physicalLocation"] == {"artifactLocation": {"uri": "app/main.py"}, "region": {"startLine": 87}}
    for loc in (Location(url="http://localhost:8000/api/students"), Location(table="students", column="aadhaar"),
                Location(file="/etc/passwd", line=1), Location(file="../outside.py", line=1)):
        assert to_sarif(scan_of([finding("F-001", loc=loc)]))["runs"][0]["results"] == []  # no file, absolute or outside the repo: left out


def test_partial_fingerprint_is_the_finding_fingerprint():
    f = finding("F-001").model_copy(update={"fingerprint": "0123456789abcdef"})
    assert to_sarif(scan_of([f]))["runs"][0]["results"][0]["partialFingerprints"] == {"dpdpLens/v1": "0123456789abcdef"}
    assert "partialFingerprints" not in to_sarif(scan_of([finding("F-001")]))["runs"][0]["results"][0]  # an old scan has none


def test_only_masked_text_is_used():
    text = json.dumps(to_sarif(scan_of([finding("F-001", masked="XXXX XXXX 1234")])))
    assert "XXXX XXXX 1234" in text and "Sample (masked)" in text


def test_sarif_api_route(tmp_path):
    c = TestClient(create_app(repo_root="/"))
    c.app.state.scans["S-001"] = scan_of([finding("F-001")])
    c.app.state.scans["S-002"] = {"status": "running"}
    assert c.get("/scan/S-001/sarif").json()["runs"][0]["results"][0]["ruleId"] == "log_pii"
    assert c.get("/scan/S-404/sarif").status_code == 404 and c.get("/scan/S-002/sarif").status_code == 409


def test_cli_writes_json_and_sarif(target, target_db, tmp_path):
    out, sarif = tmp_path / "scan.json", tmp_path / "scan.sarif"
    # no frontend in the tests: browser_scan fails, the scan is incomplete (exit 2) but both files are still written
    assert main(["scan", "--target", target, "--repo", str(BACKEND), "--db", str(target_db), "--out", str(out), "--sarif", str(sarif)]) == 2
    scan, s = json.loads(out.read_text()), json.loads(sarif.read_text())
    with_file = [f for f in scan["findings"] if f["evidence"]["location"]["file"]]
    assert len(s["runs"][0]["results"]) == len(with_file) and s["runs"][0]["properties"]["readinessScore"] == scan["score"]
