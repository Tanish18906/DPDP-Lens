"""Shared helpers for the Playwright gates. Settings come from the environment:
DASH_URL (default http://localhost:5174) and SHOT_DIR (default docs/fallback-shots in the repo)."""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
URL = os.environ.get("DASH_URL", "http://localhost:5174")
ENGINE = os.environ.get("ENGINE_URL", "http://localhost:8100")
SHOT_DIR = Path(os.environ.get("SHOT_DIR", ROOT / "docs" / "fallback-shots"))
SHOT_DIR.mkdir(parents=True, exist_ok=True)

# Redesign tokens: accent teal (passed), critical (failed), muted (pending).
GREEN, RED, GREY = "rgb(14, 90, 85)", "rgb(180, 35, 24)", "rgb(91, 98, 112)"
VIEWPORT = {"width": 1366, "height": 768}
FIXED = "Verified. Re-scan passed and the app's tests still pass."

# Demo facts on the seeded demo app with the frontend running: a full scan, then each fix in click order.
START_FINDINGS, START_SCORE = 21, 13  # weights 10/5/2/1: 2 critical, 10 high, 8 medium, 1 low = penalty 87
FIX_ORDER = [  # (row title, fix id, score after, cumulative on one scan)
    ("Public API endpoint", "V1", 23), ("Any logged-in user can read", "V2", 33), ("Personal data written to logs", "V3", 38),
    ("Tracking script loads before any consent", "V5", 43), ("Consent box is pre-ticked", "V6", 45),
    ("Personal data is still stored after deletion", "V7", 50), ("Under-18 signup accepted", "V8", 55)]
FINAL_SCORE, LEFT_OPEN = 55, 14  # after all 7 fixes: 21 findings minus 7


class Gate:
    def __init__(self, name):
        self.name, self.results = name, []

    def check(self, name, ok, detail=""):
        self.results.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

    def done(self):
        print(f"{self.name}: {sum(self.results)}/{len(self.results)} passed")
        sys.exit(0 if self.results and all(self.results) else 1)


def launch(p):
    try:
        return p.chromium.launch()
    except Exception:
        return p.chromium.launch(channel="chrome")  # system Chrome when the bundled build is missing


def new_page(browser, errs):
    page = browser.new_context(viewport=VIEWPORT, accept_downloads=True).new_page()
    page.on("console", lambda m: errs.append(m.text) if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errs.append(str(e)))
    return page


def real_errors(errs):
    return [e for e in errs if "Failed to load resource" not in e]  # aborted or refused requests are expected in some gates


def open_live(page):
    page.goto(URL)
    page.get_by_text("Live Engine (:8100)").wait_for(timeout=8000)


def run_scan(page, findings=START_FINDINGS):
    page.get_by_role("button", name="Run scan").click()
    page.get_by_text(f"Findings ({findings})").wait_for(timeout=30000)


def summary(page):
    return page.locator('section[aria-label="Summary"]').inner_text().lower().replace("\n", " ")


def counts(page):
    return dict(re.findall(r"(critical|high|medium|low)\s*(\d+)", summary(page)))


def body(page):
    return page.locator("body").inner_text()


def row(page, title):
    return page.locator('[id^="finding-row-"]', has_text=title)


def detail(page):
    return page.locator('section[aria-label="Finding detail"]')


def color(page, label):
    return page.get_by_text(label, exact=True).first.evaluate("e => getComputedStyle(e).color")


def badges_green(page):
    return all(color(page, b) == GREEN for b in ("Re-scan passed", "Tests passed", "Verified"))


def fix_and_wait(page, title, timeout=60000):
    """Select a finding, click Fix and verify, wait for the verified message. Returns the engine's JSON answer."""
    row(page, title).click()
    with page.expect_response(lambda r: "/fix" in r.url and r.request.method == "POST") as resp:
        page.get_by_role("button", name="Fix and verify").click()
    page.get_by_text(FIXED).wait_for(timeout=timeout)
    page.wait_for_timeout(900)  # score count-up is 800 ms
    return resp.value.json()


def shot(page, name, top=False):
    """Save a fallback screenshot. top=True scrolls the page up so the score is in the picture."""
    if top:
        page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(900)  # let the 800 ms score count-up finish
    page.screenshot(path=str(SHOT_DIR / f"{name}.png"))


def use_sample_mode(page):
    """Open the dashboard with the engine unreachable and switch to sample data (clicking is the only way in)."""
    page.route(f"{ENGINE}/**", lambda r: r.abort())
    page.goto(URL)
    page.get_by_role("button", name="Use sample data").wait_for(timeout=8000)

