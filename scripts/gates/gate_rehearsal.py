"""The docs/demo-script.md path on the live stack, with timings: scan, critical finding, fix V1, drift, data flow,
V3 and V5 fixes, report. Needs the demo stack (./run_demo.sh)."""
import re
import shutil
import subprocess
import time

from playwright.sync_api import sync_playwright

import common as c

RAW = re.compile(r"\b\d{12}\b|\b\d{4}\s\d{4}\s\d{4}\b|\b[6-9]\d{9}\b|\b[\w.]+@[\w.]+\.\w+\b")  # raw Aadhaar, phone, email
# In PDF text: an unmasked Aadhaar (12 digits), a full PAN (masks start XXXXX) or a full Indian mobile number.
PDF_PII = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b|\b(?!X{5})[A-Z]{5}\d{4}[A-Z]\b|\b(?:\+91[\s-]?)?[6-9]\d{9}\b")
g, T, t0 = c.Gate("rehearsal"), {}, [time.perf_counter()]


def lap(name):
    now = time.perf_counter()
    T[name] = round(now - t0[0], 1)
    t0[0] = now
    print(f"  TIME {name}: {T[name]}s")


with sync_playwright() as p:
    b, errs = c.launch(p), []
    page = c.new_page(b, errs)
    c.open_live(page); lap("open dashboard")
    g.check("first run: tagline and exactly one Run scan button",
            "Does your app do what its privacy notice says?" in c.body(page) and page.get_by_role("button", name="Run scan").count() == 1)
    c.shot(page, "first-run")
    page.get_by_role("button", name="Run scan").click()
    page.get_by_text(re.compile(r"Step \d+ of \d+")).wait_for(timeout=4000)  # real steps from the engine, not timer text
    page.locator('section[aria-label="Scan progress"]').get_by_text(re.compile(r"^\d+(\.\d\d s| ms)$")).first.wait_for(timeout=15000)
    g.check("scan: a finished layer shows its measured duration", True)
    page.screenshot(path=str(c.SHOT_DIR / "scanning.png"))  # no count-up wait: the scan is still running
    step_text = page.locator("body").inner_text()
    g.check("scan overlay shows a real engine step", any(label in step_text for label in (
        "Testing the API", "Testing API access", "Inspecting the database", "Scanning source code", "Checking that deletion",
        "Testing signup", "Looking for a DPO", "Auditing the signup page", "Comparing the privacy notice")))
    page.get_by_text(f"Findings ({c.START_FINDINGS})").wait_for(timeout=30000); lap("run scan")
    g.check(f"scan: score {c.START_SCORE}, {c.START_FINDINGS} findings", f" {c.START_SCORE} " in f" {c.summary(page)} ", c.summary(page)[:100])
    c.shot(page, "rehearsal-1-scan")
    c.row(page, "Public API endpoint").click()
    d = c.detail(page).inner_text(); lap("open critical finding")
    g.check("critical finding shows Act s8(5) and Rule 6(1)(b)", "Act s8(5)" in d and "Rule 6(1)(b)" in d)
    g.check("evidence shows no raw Aadhaar, phone or email", not RAW.findall(d), str(RAW.findall(d)[:3]))
    v1 = c.fix_and_wait(page, "Public API endpoint"); lap("fix V1")
    f = v1["finding"]["fix"]
    g.check("V1 live, verified, score 19 to 29", v1["mode"] == "live" and f["verified"] and (v1["score_before"], v1["score_after"]) == (19, 29),
            f'{v1["mode"]} {v1["score_before"]}->{v1["score_after"]}')
    g.check("V1 badges green", c.badges_green(page))
    d = c.detail(page).inner_text()
    g.check("V1 verification log from the live run: 5 timed steps, port, pytest passed",
            "verification log" in d.lower() and "127.0.0.1:" in d and len(re.findall(r"\d+(?:\.\d\d s| ms)", d)) >= 6
            and re.search(r"\d+ passed", d) is not None and "finding gone" in d, d[d.lower().find("verification log"):].replace("\n", " | "))
    g.check("V1 VERIFIED mark with score 19 to 29", "VERIFIED" in c.detail(page).inner_text() and "19 to 29" in c.detail(page).inner_text())
    c.shot(page, "rehearsal-2-v1-fixed")
    c.detail(page).evaluate("e => e.scrollTop = e.scrollHeight")
    c.shot(page, "fix-verification-log")
    c.detail(page).evaluate("e => e.scrollTop = 0")
    page.get_by_role("button", name="Notice vs Runtime").click()
    page.get_by_text("are not in its privacy notice").wait_for(timeout=3000); lap("notice vs runtime tab")
    t = c.body(page)
    g.check("drift headline and 3 undeclared rows", "3 of 6 data fields the app handles are not in its privacy notice" in t and t.lower().count("not in the notice") == 3)
    c.shot(page, "rehearsal-3-drift")
    page.get_by_role("button", name="Data Flow").click()
    page.get_by_role("list", name="Fields by layer").wait_for(); lap("data flow view")
    page.get_by_role("button", name="Findings").click()
    v3 = c.fix_and_wait(page, "Personal data written to logs"); lap("fix V3")
    g.check("V3 live, verified, 29 to 34", v3["mode"] == "live" and v3["finding"]["fix"]["verified"] and (v3["score_before"], v3["score_after"]) == (29, 34),
            f'{v3["mode"]} {v3["score_before"]}->{v3["score_after"]}')
    v5 = c.fix_and_wait(page, "Tracking script loads before any consent"); lap("fix V5")
    g.check("V5 live, verified, 34 to 39", v5["mode"] == "live" and v5["finding"]["fix"]["verified"] and (v5["score_before"], v5["score_after"]) == (34, 39),
            f'{v5["mode"]} {v5["score_before"]}->{v5["score_after"]}')
    s = c.summary(page)
    g.check("gauge 39, history 19 to 39", " 39 " in f" {s} " and "19 to 39" in s, s[:120])
    c.shot(page, "rehearsal-4-after-3-fixes", top=True)
    page.get_by_role("button", name="Export report").click()
    items = page.get_by_role("menuitem").all()
    fmts = {m.locator("span").first.inner_text(): m.get_attribute("href") for m in items}
    g.check("export menu: PDF, HTML, JSON, SARIF only", list(fmts) == ["PDF", "HTML", "JSON", "SARIF"], str(list(fmts)))
    got = {k: page.request.get(v) for k, v in fmts.items()}
    g.check("export: every format is a real 200 from the engine",
            all(r.status == 200 for r in got.values()) and got["PDF"].headers["content-type"] == "application/pdf"
            and got["JSON"].json()["scan_id"] and got["SARIF"].json()["version"] == "2.1.0", str({k: r.status for k, r in got.items()}))
    pdf_path = c.SHOT_DIR / "report-sample.pdf"
    pdf_path.write_bytes(got["PDF"].body())
    tool = shutil.which("pdftotext")
    text = subprocess.run([tool, "-layout", str(pdf_path), "-"], capture_output=True, text=True).stdout if tool else ""
    leaks = PDF_PII.findall(text)
    g.check("pdf: masked evidence only (no unmasked Aadhaar, PAN or phone), footer and score line present",
            bool(tool) and not leaks and "Main duties apply from 13 May 2027" in text and "Score at scan 19, now 39" in text
            and "XXXX XXXX" in text, "pdftotext not found, install poppler-utils" if not tool else str(leaks[:3]))
    with page.context.expect_page() as pop:
        page.get_by_role("menuitem", name="HTML").click()
    rp = pop.value
    rp.wait_for_load_state()
    rt = rp.locator("body").inner_text()
    g.check("report opens, readiness wording, no cached label", "/report/" in rp.url and "not a compliance certificate" in rt.lower() and "Cached golden" not in rt, rp.url)
    g.check("report has no raw PII", not RAW.findall(rt), str(RAW.findall(rt)[:3]))
    g.check("no console errors", not c.real_errors(errs), "; ".join(errs))
    b.close()
print("TIMES", T)
g.done()
