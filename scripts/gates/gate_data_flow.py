"""The Data Flow tab, built from notice_drift.observed: sample mode and a live scan. Needs the demo stack."""
from playwright.sync_api import sync_playwright

import common as c


def label(page):
    return page.locator('svg[role="img"]').get_attribute("aria-label")


def red(page):
    return sorted(t.strip() for t in page.locator('svg[role="img"] text[fill="#FF5C5C"]').evaluate_all("els => els.map(e => e.textContent)"))


g = c.Gate("data_flow")
with sync_playwright() as p:
    b, errs = c.launch(p), []
    page = c.new_page(b, errs)
    c.use_sample_mode(page)
    page.get_by_role("button", name="Use sample data").click()
    page.get_by_role("button", name="Data Flow").click()
    a = label(page)
    g.check("sample: DB to API has aadhaar, dob, parent_pan", "Database to Backend API: aadhaar, dob, parent_pan" in a)
    g.check("sample: API to Frontend has the same three", "Backend API to Frontend: aadhaar, dob, parent_pan" in a)
    g.check("sample: Frontend to Third parties has aadhaar", "Frontend to Third parties: aadhaar" in a)
    r = red(page)
    g.check("sample: red '! field' labels", r.count("! aadhaar") == 3 and "! dob" in r and "! parent_pan" in r, str(r))
    g.check("sample: facebook.com shown", "facebook.com" in page.locator('svg[role="img"]').text_content())
    g.check("sample: no old hardcoded text", all(x not in c.body(page) for x in ("tracker (V5)", "3rd Party")))
    c.shot(page, "data-flow-sample")
    page.unroute(f"{c.ENGINE}/**")
    c.open_live(page)
    page.get_by_role("button", name="Data Flow").click()
    g.check("live before scan: empty state", page.get_by_text("No data flow yet").is_visible())
    c.run_scan(page)
    page.get_by_role("button", name="Data Flow").click()
    a = label(page)
    parts = a.split(". ")
    g.check("live: DB to API lists aadhaar, dob, parent_pan", all(f in parts[0] for f in ("aadhaar", "dob", "parent_pan")))
    g.check("live: API to Frontend lists aadhaar, dob, parent_pan", all(f in parts[1] for f in ("aadhaar", "dob", "parent_pan")))
    g.check("live: Frontend to Third parties none observed", a.endswith("Frontend to Third parties: none observed"))
    g.check("live: declared fields not red", not any(x in red(page) for x in ("! name", "! email", "! phone")), str(red(page)))
    t = c.body(page)
    g.check("live: no hardcoded drawing text", all(x not in t for x in ("tracker (V5)", "3rd Party", "Facebook")))
    g.check("live: tracker caption", "Trackers are reported as findings" in t)
    c.shot(page, "data-flow-live")
    g.check("no console errors", not c.real_errors(errs), "; ".join(errs))
    b.close()
g.done()
