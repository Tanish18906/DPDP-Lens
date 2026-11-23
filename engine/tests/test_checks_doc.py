import json
from pathlib import Path

from dpdp_lens import checks_doc
from dpdp_lens.__main__ import main
from dpdp_lens.checks import CHECKS
from dpdp_lens.models import ScanResult
from dpdp_lens.report import render_report
from test_contract import load_sample

ROOT = Path(__file__).resolve().parents[2]


def test_checks_md_is_current_and_lists_every_check_id():
    text = (ROOT / "docs" / "CHECKS.md").read_text()
    assert text == checks_doc.to_markdown(), "regenerate: cd engine && python -m dpdp_lens checks --md > ../docs/CHECKS.md"
    assert all(f"`{cid}`" in text for cid in CHECKS)


def test_readme_names_every_check_id():
    readme = (ROOT / "README.md").read_text()
    assert [cid for cid in CHECKS if f"`{cid}`" not in readme] == []


def test_checks_cli_prints_md_by_default_and_json_on_request(capsys):
    assert main(["checks"]) == 0
    assert capsys.readouterr().out == checks_doc.to_markdown()
    assert main(["checks", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [c["id"] for c in data["checks"]] == list(CHECKS) and data["weights"] == {"critical": 10, "high": 5, "medium": 2, "low": 1}
    assert all(c["clauses"] and c["detection"] and c["recommendation"] for c in data["checks"])


def test_report_shows_reason_recommendation_and_file_line_for_every_finding(tmp_path, capsys):
    scan = load_sample()
    f = scan.findings[0].model_copy(update={"evidence": scan.findings[0].evidence.model_copy(update={
        "location": scan.findings[0].evidence.location.model_copy(update={"file": "backend/app/main.py", "line": 64})})})
    scan = scan.model_copy(update={"findings": [f] + scan.findings[1:]})
    html = render_report(scan)
    for x in scan.findings:
        assert x.severity_reason in html and x.recommendation in html
    assert "backend/app/main.py:64" in html and "Recommended fix" in html
    assert "100 minus 10 per critical, 5 per high, 2 per medium and 1 per low" in html  # from SEVERITY_WEIGHTS, not text
    (tmp_path / "scan.json").write_text(scan.model_dump_json())
    assert main(["report", str(tmp_path / "scan.json"), "--out", str(tmp_path / "r.html")]) == 0
    assert (tmp_path / "r.html").read_text() == html


def test_committed_sample_report_agrees_with_its_scan_and_holds_no_raw_data():
    scan_file, html_file = ROOT / "reports" / "tutornest-scan.json", ROOT / "reports" / "tutornest-report.html"
    if not scan_file.exists():
        return  # written by scripts/make_sample_report.sh
    scan = ScanResult.model_validate_json(scan_file.read_text())
    html = html_file.read_text()
    assert html == render_report(scan)
    assert all(x.severity_reason and x.recommendation and x.evidence.location.file for x in scan.findings if x.layer != "browser" or x.evidence.location.url)
    blob = scan_file.read_text() + html + (ROOT / "reports" / "tutornest.sarif").read_text()
    for raw in ("tutornest-demo-secret-123", "admin123", "mail-demo-pass-456", "hackathon-insecure", "StudentPass123"):
        assert raw not in blob
