"""The children_no_parental_consent finding (V8 detection) in the dashboard. Needs the demo stack."""
import re

from playwright.sync_api import sync_playwright

import common as c

g = c.Gate("children")
with sync_playwright() as p:
    b, errs = c.launch(p), []
    page = c.new_page(b, errs)
    c.open_live(page)
    c.run_scan(page)
    s = c.summary(page)
    g.check("10 findings, score 0, counts 2/5/2/1", " 0 " in f" {s} " and list(c.counts(page).items()) ==
            [("critical", "2"), ("high", "5"), ("medium", "2"), ("low", "1")], s[:110])
    r = c.row(page, "Under-18 signup accepted with no parental consent")
    g.check("new finding listed once", r.count() == 1)
    r.click()
    d = c.detail(page).inner_text()
    g.check("clauses Act s9(1) and Rule 10", "Act s9(1)" in d and "Rule 10" in d)
    g.check("evidence summary and masked email", "returned 201" in d and re.search(r"[a-z]\*+@", d) is not None)
    g.check("no raw email in the evidence", not re.search(r"\b[\w.]+@[\w.]+\.\w+\b", d.replace("***@", "")))
    g.check("fix offered", page.get_by_role("button", name="Fix and verify").is_enabled())
    c.shot(page, "children-finding")
    page.get_by_role("button", name="Notice vs Runtime").click()
    page.get_by_text("are not in its privacy notice").wait_for(timeout=3000)
    g.check("drift unchanged: 3 of 6", "3 of 6 data fields the app handles are not in its privacy notice" in c.body(page))
    g.check("no console errors", not c.real_errors(errs), "; ".join(errs))
    b.close()
g.done()
