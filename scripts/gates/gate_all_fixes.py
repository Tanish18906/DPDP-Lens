"""All 7 verified fixes live on one scan through the dashboard. Needs the demo stack."""
import time

from playwright.sync_api import sync_playwright

import common as c

g = c.Gate("all_fixes")
with sync_playwright() as p:
    b, errs = c.launch(p), []
    page = c.new_page(b, errs)
    c.open_live(page)
    c.run_scan(page)
    g.check(f"scan: {c.START_FINDINGS} findings", True)
    for title, gid, expect in c.FIX_ORDER:
        t = time.perf_counter()
        j = c.fix_and_wait(page, title)
        fx = j["finding"]["fix"]
        g.check(f"{gid}: live, verified, tests passed, score_after {expect}",
                j["mode"] == "live" and fx["verified"] and fx["tests_passed"] and j["score_after"] == expect,
                f'{j["mode"]} {j["score_before"]}->{j["score_after"]} {time.perf_counter() - t:.1f}s')
        g.check(f"{gid}: badges green and diff shown", c.badges_green(page) and bool(fx["diff"]))
        g.check(f"{gid}: row says Verified fixed", "Verified fixed" in c.row(page, title).inner_text())
    s = c.summary(page)
    g.check(f"final: gauge {c.FINAL_SCORE}, history {c.START_SCORE} to {c.FINAL_SCORE}", f" {c.FINAL_SCORE} " in f" {s} " and f"{c.START_SCORE} to {c.FINAL_SCORE}" in s, s[:120])
    left = [r.inner_text().split("\n") for r in page.locator('[id^="finding-row-"]').all() if "Verified fixed" not in r.inner_text()]
    g.check(f"{c.LEFT_OPEN} findings left open (the ones with no fix template)", len(left) == c.LEFT_OPEN, str(left))
    t = c.body(page)
    g.check(f"summary: all 7 verified, score {c.START_SCORE} to {c.FINAL_SCORE}, {c.LEFT_OPEN} manual",
            "All 7 findings with a fix template are verified" in t and f"Score {c.START_SCORE} to {c.FINAL_SCORE}." in t and f"{c.LEFT_OPEN} findings still need a manual change." in t)
    c.shot(page, "all-fixes-after-7", top=True)
    g.check("no console errors", not c.real_errors(errs), "; ".join(errs))
    b.close()
g.done()
