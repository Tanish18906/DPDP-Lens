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
    g.check("final: gauge 83, history 0 to 83", " 83 " in f" {s} " and "0 → 83" in s, s[:120])
    left = [r.inner_text().split("\n") for r in page.locator('[id^="finding-row-"]').all() if "Verified fixed" not in r.inner_text()]
    g.check("3 findings left open (db plaintext, drift, contact)", len(left) == 3, str(left))
    c.shot(page, "all-fixes-after-7")
    g.check("no console errors", not c.real_errors(errs), "; ".join(errs))
    b.close()
g.done()
