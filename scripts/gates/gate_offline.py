"""Engine unreachable (blocked in the browser, no server is touched), then the labelled sample mode."""
from playwright.sync_api import sync_playwright

import common as c

g = c.Gate("offline")
with sync_playwright() as p:
    b, errs = c.launch(p), []
    page = c.new_page(b, errs)
    c.use_sample_mode(page)
    t = c.body(page)
    g.check("engine down: banner and Use sample data button", "Engine not reachable" in t and "Use sample data" in t)
    g.check("engine down: no fake findings before the click", "No scan yet" in t or "Findings (0)" in t)
    c.shot(page, "engine-down")
    page.get_by_role("button", name="Use sample data").click()
    page.get_by_text("Sample Data Mode").wait_for()
    page.get_by_role("button", name="Run scan").click()
    page.get_by_text("Findings (5)").wait_for(timeout=15000)
    g.check("sample scan: 5 findings, score 73 (the sample's own numbers)", " 73 " in f" {c.summary(page)} ", c.summary(page)[:80])
    page.locator('[id^="finding-row-"]').first.click()
    page.get_by_role("button", name="Fix and verify").click()
    page.get_by_text("Simulated (sample data)").wait_for(timeout=10000)
    g.check("sample fix: score 73 to 83, taken from the sample's own fix.score_after", " 83 " in f" {c.summary(page)} ")
    t = c.body(page)
    g.check("sample fix labelled Simulated, no live claims", "Simulated. No real re-scan or tests were run." in t and "Cached golden" not in t
            and "Verified on a sandbox copy" not in t and "Download patch" not in t and "SIMULATED" in t and "VERIFIED" not in t and "verification log" not in t.lower())
    page.get_by_role("button", name="Notice vs Runtime").click()
    g.check("sample drift shows the facebook.com request", "facebook.com" in c.body(page))
    c.shot(page, "sample-mode")
    page.get_by_role("button", name="Back to live engine").click()
    page.get_by_role("button", name="Use sample data").wait_for(timeout=5000)  # engine still blocked: banner is back
    t = c.body(page)
    g.check("back to live: SAMPLE label and sample findings gone", "SAMPLE" not in t and "Sample Data Mode" not in t and "Findings (5)" not in t)
    g.check("no console errors", not c.real_errors(errs), "; ".join(errs))
    b.close()
g.done()
