import re
from html import escape
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import BACKEND
from dpdp_lens.api import create_app
from dpdp_lens.models import Evidence, Finding, Fix, Location, NoticeDrift, ObservedField, ScanResult, compute_counts, compute_score
from dpdp_lens.report import render_report

SAMPLE = ScanResult.model_validate_json((Path(__file__).resolve().parents[2] / "contract" / "sample-scan.json").read_text())


def make(findings, drift=None):
    return ScanResult(scan_id="S-007", target="http://localhost:8000", scanned_at="2026-11-23T08:00:00+05:30",
                      score=compute_score(findings), counts=compute_counts(findings), findings=findings, notice_drift=drift)


def finding(fid="F-001", severity="critical", status="open", fix=None, **over):
    base = dict(id=fid, check="api_pii_exposure", layer="api", severity=severity, title="Title", explanation="Explanation.",
                clauses=[], evidence=Evidence(kind="http", summary="Summary", masked_sample="a***@x.test",
                                              location=Location(url="http://localhost:8000/api/students")),
                status=status, fix=fix or Fix(available=True))
    return Finding(**{**base, **over})


def test_sample_scan_report_has_everything_a_reader_needs():
    html = render_report(SAMPLE)
    assert "<title>DPDP Lens: readiness report - S-001</title>" in html
    assert "DPDP Lens is a readiness report, not a compliance certificate. Main duties apply from 13 May 2027." in html
    assert f"<b>{SAMPLE.score}</b>readiness score" in html
    for f in SAMPLE.findings:
        assert f.id in html and escape(f.title) in html and escape(f.evidence.summary) in html  # shown escaped (T&amp;C)
        assert all(escape(c.ref) in html for c in f.clauses)
    assert "Act s8(5)" in html and "reasonable security safeguards" in html
    assert "3 of 6 data fields the app handles are not in its privacy notice" in html
    assert html.count("Not in the notice") == 3 and "<code>aadhaar</code>" in html
    assert "s8(7) may be exempt. s8(5) still applies." in html


def test_findings_are_sorted_critical_first():
    html = render_report(make([finding("F-002", "low"), finding("F-003", "critical"), finding("F-001", "high")]))
    assert [m for m in re.findall(r'class="id">(F-\d+)', html)] == ["F-003", "F-001", "F-002"]


def test_no_drift_data_says_so_and_no_findings_says_it_is_not_a_compliance_result():
    html = render_report(make([]))
    assert "No drift data for this scan." in html and "Not in the notice" not in html
    assert "No findings from the checks we ran. The checks are limited" in html


def test_everything_is_escaped_and_the_page_loads_nothing():
    evil = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    f = finding(title=evil, explanation=evil, status="verified_fixed", evidence=Evidence(
        kind="http", summary=evil, masked_sample=evil, location=Location(file=evil, line=3)),
        fix=Fix(available=True, verified=True, rescan_passed=True, tests_passed=True,
                diff=f"--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old {evil}\n+new {evil}\n"))
    drift = NoticeDrift(declared=[evil], observed=[ObservedField(field=evil, where=[evil])], undeclared=[evil])
    html = render_report(make([f], drift))
    assert "<script" not in html and "<img" not in html  # only the escaped text is there
    assert html.count("&lt;script&gt;alert(1)&lt;/script&gt;") >= 7 and "&lt;img src=x onerror=alert(2)&gt;" in html
    assert not re.search(r"<[a-z][^>]*\s(href|src)=", html)  # no tag loads or links anything
    assert "<link" not in html and "@import" not in html and "url(" not in html


def test_report_is_deterministic():
    assert render_report(SAMPLE) == render_report(SAMPLE)


def test_verified_live_fix_shows_badges_scores_and_the_diff():
    f = finding(status="verified_fixed", fix=Fix(available=True, verified=True, rescan_passed=True, tests_passed=True,
                                                  score_before=28, score_after=48, diff="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"))
    html = render_report(make([f]), {"F-001": {"mode": "live", "fallback_reason": None}})
    assert "Status: Verified fixed" in html and "Re-scan passed: yes" in html and "Tests passed: yes" in html
    assert "Score 28 to 48" in html and '<span class="del">-a</span>' in html and '<span class="add">+b</span>' in html
    assert "Verified on a sandbox copy. Re-scan passed" in html and "Cached golden" not in html


def test_cached_fix_is_never_shown_as_live():
    f = finding(status="verified_fixed", fix=Fix(available=True, verified=True, rescan_passed=True, tests_passed=True, diff="d"))
    html = render_report(make([f]), {"F-001": {"mode": "cached_golden", "fallback_reason": "RuntimeError: boom"}})
    assert "Cached golden patch mode" in html and "Live run could not finish: RuntimeError: boom" in html
    assert "Verified in a saved run on a sandbox copy. It was not run just now." in html
    assert "Re-scan passed and the app's tests still pass" not in html
    replay = render_report(make([f]), {"F-001": {"mode": "cached_golden", "fallback_reason": None}})
    assert "Replayed from a saved verified run, not run just now." in replay


def test_fix_that_ran_but_did_not_verify_says_so():
    f = finding(fix=Fix(available=True, verified=False, rescan_passed=False, tests_passed=True, diff="d"))
    html = render_report(make([f]), {"F-001": {"mode": "live", "fallback_reason": None}})
    assert "Re-scan passed: no" in html and "Tests passed: yes" in html and "Verified: no" in html
    assert "Not verified. The finding stays open." in html and "Status: Open" in html
    assert "Verified on a sandbox copy" not in html


def test_untouched_finding_has_no_fix_block():
    assert 'class="fix"' not in render_report(make([finding()]))


# --- the endpoint
def scan_fn(target, repo, db, scan_id):
    return make([finding()]).model_copy(update={"scan_id": scan_id})


def client(tmp_path, **kw):
    (tmp_path / "x.db").write_text("")
    c = TestClient(create_app(scan_fn=scan_fn, repo_root=tmp_path, **kw))
    c.post("/scan", json={"target_url": "http://localhost:8000", "repo_path": ".", "db_path": "x.db"})
    return c


def test_report_endpoint_serves_a_locked_down_html_page(tmp_path):
    r = client(tmp_path).get("/report/S-001")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "DPDP Lens: readiness report - S-001" in r.text


def test_report_endpoint_errors_are_json(tmp_path):
    c = client(tmp_path)
    assert c.get("/report/S-404").status_code == 404 and set(c.get("/report/S-404").json()) == {"error", "detail"}
    c.app.state.scans["S-009"] = {"status": "running"}
    assert c.get("/report/S-009").status_code == 409
    c.app.state.scans["S-010"] = {"status": "error", "detail": "RuntimeError: boom"}
    r = c.get("/report/S-010")
    assert r.status_code == 500 and r.json()["detail"] == "RuntimeError: boom"


def test_report_after_a_live_fix_shows_verified_fixed(target, target_db, tmp_path):
    c = TestClient(create_app(repo_root="/", golden_dir=tmp_path / "golden"))
    c.post("/scan", json={"target_url": target, "repo_path": str(BACKEND), "db_path": str(target_db)})
    v1 = next(f for f in c.get("/scan/S-001").json()["findings"] if f["check"] == "api_pii_exposure")
    assert c.post(f"/findings/{v1['id']}/fix", params={"scan_id": "S-001"}).status_code == 200
    html = c.get("/report/S-001").text
    assert "Status: Verified fixed" in html and "Verified on a sandbox copy. Re-scan passed" in html and "Cached golden" not in html
    assert "Score 13 to 33" in html and "get_admin_user" in html and "3 of 6 data fields the app handles" in html
    assert "<script" not in html


def test_report_marks_a_cached_replay(tmp_path):
    d = tmp_path / "golden"
    d.mkdir()
    (d / "V1.json").write_text('{"diff": "--- a/x\\n", "verified": true, "rescan_passed": true, "tests_passed": true}')
    c = client(tmp_path, golden_dir=d)
    assert c.post("/findings/F-001/fix", params={"scan_id": "S-001", "mode": "cached"}).status_code == 200
    html = c.get("/report/S-001").text
    assert "Cached golden patch mode" in html and "Replayed from a saved verified run" in html


def test_pdf_endpoint_returns_a_pdf_download(tmp_path):
    seen = {}

    def fake_pdf(html, scan_id):
        seen.update(html=html, scan_id=scan_id)
        return b"%PDF-1.4 fake"

    r = client(tmp_path, pdf_fn=fake_pdf).get("/report/S-001.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert 'filename="dpdp-lens-S-001.pdf"' in r.headers["content-disposition"]
    assert seen["scan_id"] == "S-001" and "DPDP Lens: readiness report - S-001" in seen["html"]


def test_pdf_endpoint_without_a_browser_is_a_clear_json_error(tmp_path):
    def no_browser(html, scan_id):
        raise RuntimeError("Executable doesn't exist")

    c = client(tmp_path, pdf_fn=no_browser)
    r = c.get("/report/S-001.pdf")
    assert r.status_code == 503 and r.json()["detail"] == "PDF needs Chromium or Chrome, use the HTML report"
    assert c.get("/report/S-404.pdf").status_code == 404
    assert c.get("/report/S-001").status_code == 200  # the HTML route still works next to the .pdf one


def test_render_pdf_makes_a_real_a4_pdf():
    from dpdp_lens.report import render_pdf
    pdf = render_pdf(render_report(SAMPLE), "S-001")
    boxes = {tuple(round(float(x)) for x in m.split()) for m in re.findall(rb"/MediaBox\s*\[([^\]]*)\]", pdf)}
    assert pdf.startswith(b"%PDF") and boxes == {(0, 0, 596, 843)}  # A4 (595 x 842 points, Chromium rounds up)


def test_score_line_shows_score_at_scan_and_now_after_a_fix():
    fixed = finding("F-001", "critical", status="verified_fixed")
    scan = SAMPLE.model_copy(update={"findings": [fixed, *SAMPLE.findings[1:]]})
    scan = scan.model_copy(update={"score": compute_score(scan.findings)})
    html = render_report(scan)
    assert f"Score at scan {SAMPLE.score}, now {scan.score} after 1 verified fix" in html
    assert "Score at scan" not in render_report(SAMPLE)
