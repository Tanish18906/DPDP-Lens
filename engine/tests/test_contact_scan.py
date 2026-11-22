import httpx
import pytest

from dpdp_lens.scanners import contact_scan

CONTACT = "<p>Grievance Officer: Ms Rao, grievance@tutornest.test</p>"


def pages(notice, front=None):
    """Mock: 'http://t/notice' and 'http://f' serve the given HTML, anything else is a 404."""
    def handler(req):
        body = {"http://t/notice": notice, "http://f": front}.get(str(req.url).rstrip("/") if "f" in req.url.host else str(req.url))
        return httpx.Response(200, text=body) if body is not None else httpx.Response(404)
    return httpx.MockTransport(handler)


def test_real_notice_page_has_no_contact(target):
    findings = contact_scan.scan(target, frontend_url=None)
    assert [f.check for f in findings] == ["missing_contact"]
    f = findings[0]
    assert f.severity == "low" and f.layer == "notice" and f.evidence.location.url.endswith("/notice")


def test_visible_contact_is_found():
    assert contact_scan.scan("http://t", None, pages(f"<body>{CONTACT}</body>")) == []


def test_contact_only_in_html_comment_or_script_does_not_count():
    html = f"<body><!-- {CONTACT} --><script>var x = 'DPO dpo@t.test';</script><p>Hello</p></body>"
    assert [f.check for f in contact_scan.scan("http://t", None, pages(html))] == ["missing_contact"]


def test_keyword_without_email_or_phone_does_not_count():
    assert len(contact_scan.scan("http://t", None, pages("<p>Our grievance process is fair.</p>"))) == 1


def test_generic_contact_us_does_not_count():
    assert len(contact_scan.scan("http://t", None, pages("<p>Contact us: help@tutornest.test</p>"))) == 1


def test_contact_on_frontend_counts():
    assert contact_scan.scan("http://t", "http://f", pages("<p>Hi</p>", f"<footer>{CONTACT}</footer>")) == []


def test_unreachable_frontend_is_skipped_but_nothing_reachable_raises():
    assert len(contact_scan.scan("http://t", "http://f", pages("<p>Hi</p>"))) == 1  # frontend 404, notice checked
    with pytest.raises(RuntimeError):
        contact_scan.scan("http://nope", "http://f", pages("<p>Hi</p>"))
