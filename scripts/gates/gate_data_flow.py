"""The Data Flow view: one lane per field across Notice, Database, API, Browser, built from notice_drift.observed.
Sample mode and a live scan. Needs the demo stack."""
from playwright.sync_api import sync_playwright

import common as c

DASH = "—"  # empty layer cell


COLS = ("notice", "db", "api", "request")


def rows(page):
    """field -> [notice, database, api, browser] cell text, in lane order."""
    out = {}
    for lane in page.locator('ul[aria-label="Fields by layer"] > li').all():
        cells = [lane.locator(f'[data-col="{k}"]').inner_text().strip() for k in COLS]
        out[lane.get_attribute("data-field")] = [x.split("\n")[0] if x.startswith(DASH) else x for x in cells]  # drop the sr-only text
    return out


def header(page):
    return page.get_by_test_id("lane-head").inner_text().split("\n")


def lines(page, field):
    """Line segments drawn in a lane: (left style, thickness class)."""
    return page.locator(f'li[data-field="{field}"] span[aria-hidden="true"].absolute').evaluate_all(
        "els => els.map(e => [e.style.left, e.className.includes('h-1 ') ? 'thick' : 'thin'])")


g = c.Gate("data_flow")
with sync_playwright() as p:
    b, errs = c.launch(p), []
    page = c.new_page(b, errs)
    c.use_sample_mode(page)
    page.get_by_role("button", name="Use sample data").click()
    page.get_by_role("button", name="Data Flow").click()
    g.check("columns: Field, Notice, Database, API, Browser", header(page) == ["Field", "Notice", "Database", "API", "Browser"], str(header(page)))
    r = rows(page)
    g.check("sample: undeclared rows first", set(list(r)[:3]) == {"aadhaar", "dob", "parent_pan"}, str(list(r)))
    g.check("sample: aadhaar not in the notice, seen in DB, API and the browser (facebook.com)",
            r["aadhaar"][0] == "Not in the notice" and "students.aadhaar" in r["aadhaar"][1]
            and "/api/students" in r["aadhaar"][2] and "facebook.com" in r["aadhaar"][3], str(r["aadhaar"]))
    g.check("sample: dob and parent_pan in DB and API, not in the browser",
            all(r[f][1] != DASH and r[f][2] != DASH and r[f][3] == DASH for f in ("dob", "parent_pan")))
    g.check("sample: name, email, phone in the notice", all(r[f][0] == "In the notice" for f in ("name", "email", "phone")))
    g.check("sample: aadhaar has 3 thick red segments (notice to DB, API, browser), name has none",
            [t for _, t in lines(page, "aadhaar")] == ["thick"] * 3 and lines(page, "name") == [], str(lines(page, "aadhaar")))
    g.check("sample: no old drawing text", all(x not in c.body(page) for x in ("tracker (V5)", "3rd Party", "Cross-Layer")))
    c.shot(page, "data-flow-sample")

    page.unroute(f"{c.ENGINE}/**")
    c.open_live(page)
    page.get_by_role("button", name="Data Flow").click()
    g.check("live before scan: empty state", page.get_by_text("No data flow yet").is_visible())
    c.run_scan(page)
    page.get_by_role("button", name="Data Flow").click()
    r = rows(page)
    g.check("live: undeclared aadhaar, dob, parent_pan first, each in DB and API",
            set(list(r)[:3]) == {"aadhaar", "dob", "parent_pan"}
            and all(r[f][0] == "Not in the notice" and r[f][1] != DASH and r[f][2] != DASH for f in ("aadhaar", "dob", "parent_pan")), str(r))
    g.check("live: Browser column empty", all(v[3] == DASH for v in r.values()), str(r))
    g.check("live: declared fields not flagged", all(r[f][0] == "In the notice" for f in ("name", "email", "phone") if f in r))
    g.check("live: email line is thin, dob line is thick, 2 segments each",
            [t for _, t in lines(page, "email")] == ["thin", "thin"] and [t for _, t in lines(page, "dob")] == ["thick", "thick"])
    t = c.body(page)
    g.check("live: footnote says no third-party request was seen", "No third-party request was seen as a drift field" in t)
    g.check("live: no hardcoded drawing text", all(x not in t for x in ("tracker (V5)", "3rd Party", "Facebook")))
    c.shot(page, "data-flow-live")
    g.check("no console errors", not c.real_errors(errs), "; ".join(errs))
    b.close()
g.done()
