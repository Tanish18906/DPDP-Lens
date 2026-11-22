"""How the dashboard shows a fix that is cached, failed or not verified. The engine's real answer is rewritten in the
browser (no server is touched), so every state can be seen on demand. Needs the demo stack."""
import json

from playwright.sync_api import sync_playwright

import common as c

g = c.Gate("fix_states")


def session(browser, route=None):
    errs = []
    page = c.new_page(browser, errs)
    if route:
        route(page)
    c.open_live(page)
    c.run_scan(page)
    return page, errs


def cached(page):
    def handler(route):
        r = route.fetch()
        b = r.json()
        b["mode"], b["fallback_reason"] = "cached_golden", "RuntimeError: boom"
        route.fulfill(response=r, json=b)
    page.route("**/findings/*/fix*", handler)


def broken(page):
    page.route("**/findings/*/fix*", lambda r: r.fulfill(status=502, content_type="application/json", body=json.dumps(
        {"error": "Bad Gateway", "detail": "Live fix failed (RuntimeError: boom) and no cached golden result exists"})))


def unverified(page):
    def handler(route):
        r = route.fetch()
        b = r.json()
        b["finding"]["status"] = "open"
        b["finding"]["fix"].update(verified=False, rescan_passed=False, tests_passed=True)
        b["score_after"] = b["score_before"]
        route.fulfill(response=r, json=b)
    page.route("**/findings/*/fix*", handler)


with sync_playwright() as p:
    b = c.launch(p)

    page, errs = session(b, cached)
    c.row(page, "Public API endpoint").click()
    page.get_by_role("button", name="Fix and verify").click()
    page.get_by_text("Cached golden patch mode").wait_for(timeout=20000)
    page.wait_for_timeout(700)
    t = c.body(page)
    g.check("cached: amber label with the fallback reason", "Live run could not finish: RuntimeError: boom" in t)
    g.check("cached: not presented as live", "Verified in a saved run. It was not run just now." in t and c.FIXED not in t)
    c.detail(page).evaluate("e => e.scrollTop = e.scrollHeight")
    c.shot(page, "fix-cached-label")

    page, errs = session(b, broken)
    c.row(page, "Public API endpoint").click()
    page.get_by_role("button", name="Fix and verify").click()
    alert = page.get_by_role("alert")
    alert.wait_for(timeout=5000)
    msg = alert.inner_text()
    g.check("error: red banner with the engine's text", "Fix failed:" in msg and "no cached golden result exists" in msg, msg)
    g.check("error: finding stays open, button still there", "Verified fixed" not in c.body(page) and page.get_by_role("button", name="Fix and verify").is_enabled())
    g.check("error: score unchanged at 0", " 0 " in f" {c.summary(page)} ")
    c.shot(page, "fix-error-banner")
    g.check("error: no console errors besides the 502", not c.real_errors(errs), "; ".join(errs))

    page, errs = session(b, unverified)
    c.row(page, "Public API endpoint").click()
    page.get_by_role("button", name="Fix and verify").click()
    page.get_by_text("Not verified.").wait_for(timeout=20000)
    g.check("unverified: red Re-scan, green Tests, red Verified",
            (c.color(page, "Re-scan passed"), c.color(page, "Tests passed"), c.color(page, "Verified")) == (c.RED, c.GREEN, c.RED))
    g.check("unverified: finding open, no patch download", "Verified fixed" not in c.body(page) and "Download patch" not in c.body(page))
    c.shot(page, "fix-unverified")

    page, errs = session(b)
    c.row(page, "Aadhaar or PAN stored in plaintext").click()
    btn = page.get_by_role("button", name="No automated fix yet")
    g.check("plaintext columns (V4): disabled 'No automated fix yet'", btn.is_visible() and btn.is_disabled())
    b.close()
g.done()
