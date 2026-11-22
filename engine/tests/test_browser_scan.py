import functools
import http.server
import json
import threading
import types

import pytest

from dpdp_lens import browser
from dpdp_lens.scanners import browser_scan
from dpdp_lens.scanners.browser_scan import classify, stub_third_party

FB = '<script async src="https://connect.facebook.net/en_US/fbevents.js?id=12345"></script>'
PAGES = {
    "bad.html": f'{FB}<label for="c"><input type="checkbox" id="c" checked> I agree to the Terms and to marketing messages</label>',
    "clean.html": '<script src="https://example.org/lib.js"></script><label><input type="checkbox"> I agree to the Terms</label>',
    "late.html": '<div id="r"></div><script>setTimeout(() => { document.getElementById("r").innerHTML = '
                 '\'<label><input type="checkbox" checked> I accept the terms</label>\' }, 600)</script>',
    "preticked.html": '<label><input type="checkbox" checked> I agree to the Terms</label>',
    "bundled.html": '<label><input type="checkbox"> I agree to the Terms and marketing emails</label>',
    "remember.html": '<label><input type="checkbox" checked> Remember me</label>',
}


@pytest.fixture(scope="module")
def pages(tmp_path_factory):
    """Fixture pages on a local server. Every page reports clicks to /clicked, so tests can prove there were none."""
    root = tmp_path_factory.mktemp("pages")
    for name, body in PAGES.items():
        (root / name).write_text(f"<!doctype html><html><body>{body}"
                                 "<script>document.addEventListener('click', () => fetch('/clicked'))</script></body></html>")
    clicks = []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/clicked":
                clicks.append(1)
            super().do_GET()

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield types.SimpleNamespace(url=f"http://127.0.0.1:{server.server_address[1]}", clicks=clicks)
    server.shutdown()


def checks(findings):
    return [f.check for f in findings]


def test_bad_page_gives_tracker_and_consent_findings(pages):
    findings = browser_scan.scan(f"{pages.url}/bad.html")
    assert checks(findings) == ["tracker_before_consent", "consent_bundled"]
    tracker, consent = findings
    assert tracker.severity == "high" and tracker.layer == "browser" and tracker.evidence.kind == "network"
    assert "connect.facebook.net (Social, Meta)" in tracker.evidence.summary and tracker.fix.available
    assert tracker.evidence.masked_sample == "https://connect.facebook.net/en_US/fbevents.js"
    assert consent.severity == "medium" and consent.evidence.kind == "dom"
    assert consent.evidence.summary == "The consent checkbox is already ticked and bundles terms with marketing"
    assert consent.evidence.masked_sample == "I agree to the Terms and to marketing messages"
    assert "12345" not in json.dumps([f.model_dump() for f in findings])  # query strings never reach the evidence
    assert pages.clicks == []  # the scanner never clicks


def test_run_scan_can_be_pointed_at_another_frontend(pages, target, fresh_db):
    """The fix check re-scans a patched copy of the frontend this way."""
    from conftest import BACKEND
    from dpdp_lens.runner import run_scan
    only_browser = [("browser_scan", lambda t, repo, db, fe: browser_scan.scan(fe))]
    r = run_scan(target, str(BACKEND), str(fresh_db), scanners=only_browser, frontend_url=f"{pages.url}/bad.html")
    assert [f.check for f in r.findings] == ["tracker_before_consent", "consent_bundled"]
    errors = []
    run_scan(target, str(BACKEND), str(fresh_db), scanners=only_browser, frontend_url=None, errors=errors)
    assert errors and errors[0].startswith("browser_scan: RuntimeError")


def test_clean_page_gives_nothing(pages):
    assert browser_scan.scan(f"{pages.url}/clean.html") == []  # unchecked box, example.org is not a tracker


def test_checkbox_added_late_by_javascript_is_seen(pages):
    assert checks(browser_scan.scan(f"{pages.url}/late.html")) == ["consent_bundled"]


def test_preticked_only_and_bundled_only(pages):
    pre = browser_scan.scan(f"{pages.url}/preticked.html")[0]
    assert pre.evidence.summary == "The consent checkbox is already ticked"
    bundled = browser_scan.scan(f"{pages.url}/bundled.html")[0]
    assert bundled.evidence.summary == "The consent checkbox bundles terms with marketing"


def test_unrelated_ticked_checkbox_is_not_a_consent_box(pages):
    assert browser_scan.scan(f"{pages.url}/remember.html") == []


def test_unreachable_or_non_local_frontend_raises():
    with pytest.raises(RuntimeError, match="not reachable"):
        browser_scan.scan("http://127.0.0.1:9/")
    with pytest.raises(ValueError, match="localhost or private"):
        browser_scan.scan("https://example.com/")
    with pytest.raises(RuntimeError, match="needs a frontend URL"):
        browser_scan.scan(None)


@pytest.mark.parametrize("host,expected", [
    ("connect.facebook.net", ("Social", "Meta")),
    ("www.facebook.com", ("Social", "Meta")),
    ("x.y.doubleclick.net", ("Advertising", "Google")),   # parent domain match
    ("www.google-analytics.com", ("Analytics", "Google")),
    ("example.org", None), ("fonts.gstatic.com", None), ("com", None), ("notfacebook.net", None),
])
def test_classify(host, expected):
    assert classify(host) == expected


def test_stub_lets_local_through_and_answers_third_party_with_an_empty_200():
    def route_for(url, kind="script"):
        calls = []
        route = types.SimpleNamespace(request=types.SimpleNamespace(url=url, resource_type=kind),
                                      continue_=lambda: calls.append("continue"),
                                      fulfill=lambda **kw: calls.append(("fulfill", kw)))
        stub_third_party(route)
        return calls

    assert route_for("http://localhost:5173/src/main.jsx") == ["continue"]
    assert route_for("http://127.0.0.1:8000/api") == ["continue"]
    assert route_for("data:text/plain,hi") == ["continue"]
    (action, kw), = route_for("https://connect.facebook.net/x.js")
    assert action == "fulfill" and kw == {"status": 200, "body": "", "content_type": "application/javascript"}
    assert route_for("https://example.org/p.png", "image")[0][1]["content_type"] == "text/plain"


class FakeChromium:
    def __init__(self, bundled_ok):
        self.calls, self.bundled_ok = [], bundled_ok

    def launch(self, **kw):
        self.calls.append(kw)
        if not kw and not self.bundled_ok:
            raise RuntimeError("Executable doesn't exist")
        return "browser"


def test_launch_prefers_bundled_chromium_and_falls_back_to_chrome(caplog):
    caplog.set_level("INFO", logger="dpdp_lens")
    ok = types.SimpleNamespace(chromium=FakeChromium(True))
    assert browser.launch(ok) == "browser" and ok.chromium.calls == [{}]
    broken = types.SimpleNamespace(chromium=FakeChromium(False))
    assert browser.launch(broken) == "browser" and broken.chromium.calls == [{}, {"channel": "chrome"}]
    assert "using system Chrome" in caplog.text
