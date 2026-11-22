"""Headless browser launch: bundled Chromium first, system Chrome as the fallback (docs/05)."""
import logging

log = logging.getLogger("dpdp_lens")


def launch(playwright):
    try:
        browser = playwright.chromium.launch()
        log.info("browser: bundled Chromium")
    except Exception as e:
        log.info("browser: bundled Chromium failed (%s), using system Chrome", str(e).splitlines()[0][:100])
        browser = playwright.chromium.launch(channel="chrome")
    return browser
