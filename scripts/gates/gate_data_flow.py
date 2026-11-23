"""Where each field was seen: the layer columns of the Notice vs Runtime table (the old Data Flow tab is merged into it),
built from notice_drift.observed. Sample mode and a live scan. Needs the demo stack."""
from playwright.sync_api import sync_playwright

import common as c

DASH = "—"  # empty layer cell


def rows(page):
    """field -> [in the notice, database, api, third party] as shown, in table order."""
    out = {}
    for r in page.locator('table[aria-label="Fields by layer"] tbody tr').all():
        cells = [x.inner_text().strip() for x in r.locator("th, td").all()]
        out[cells[0]] = [x.split("\n")[0] if x.startswith(DASH) else x for x in cells[1:]]  # drop the sr-only "Not seen in ..."
    return out


g = c.Gate("data_flow")
with sync_playwright() as p:
    b, errs = c.launch(p), []
    page = c.new_page(b, errs)
    c.use_sample_mode(page)
    page.get_by_role("button", name="Use sample data").click()
    g.check("no separate Data Flow tab", page.get_by_role("button", name="Data Flow").count() == 0)
    page.get_by_role("button", name="Notice vs Runtime").click()
    r = rows(page)
    g.check("sample: undeclared rows first", set(list(r)[:3]) == {"aadhaar", "dob", "parent_pan"}, str(list(r)))
    g.check("sample: aadhaar seen in DB, API and facebook.com",
            r["aadhaar"][0] == "Not in the notice" and "students.aadhaar" in r["aadhaar"][1]
            and "/api/students" in r["aadhaar"][2] and "facebook.com" in r["aadhaar"][3], str(r["aadhaar"]))
    g.check("sample: dob and parent_pan in DB and API, no third party",
            all(r[f][1] != DASH and r[f][2] != DASH and r[f][3] == DASH for f in ("dob", "parent_pan")))
    g.check("sample: name, email, phone in the notice", all(r[f][0] == "Yes" for f in ("name", "email", "phone")))
    g.check("sample: no old drawing text", all(x not in c.body(page) for x in ("tracker (V5)", "3rd Party", "Cross-Layer")))
    c.shot(page, "data-flow-sample")

    page.unroute(f"{c.ENGINE}/**")
    c.open_live(page)
    page.get_by_role("button", name="Notice vs Runtime").click()
    g.check("live before scan: empty state", page.get_by_text("No drift data yet").is_visible())
    c.run_scan(page)
    page.get_by_role("button", name="Notice vs Runtime").click()
    r = rows(page)
    g.check("live: undeclared aadhaar, dob, parent_pan first, each in DB and API",
            set(list(r)[:3]) == {"aadhaar", "dob", "parent_pan"}
            and all(r[f][0] == "Not in the notice" and r[f][1] != DASH and r[f][2] != DASH for f in ("aadhaar", "dob", "parent_pan")), str(r))
    g.check("live: no third-party column entries", all(v[3] == DASH for v in r.values()), str(r))
    g.check("live: declared fields not flagged", all(r[f][0] == "Yes" for f in ("name", "email", "phone") if f in r))
    t = c.body(page)
    g.check("live: tracker caption", "Trackers are reported as findings" in t)
    g.check("live: no hardcoded drawing text", all(x not in t for x in ("tracker (V5)", "3rd Party", "Facebook")))
    c.shot(page, "data-flow-live")
    g.check("no console errors", not c.real_errors(errs), "; ".join(errs))
    b.close()
g.done()
