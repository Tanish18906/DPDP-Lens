"""tracker_before_consent and consent_bundled: load the signup page with no clicks (Playwright).
Third-party requests are stubbed with an empty 200, so nothing leaves the machine, but the request event still fires."""
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from .. import config
from ..browser import launch
from ..models import Evidence, Finding, Fix, Location
from ..netutil import is_local

SERVICES = Path(__file__).resolve().parents[1] / "data" / "services.json"  # Disconnect, CC BY-NC-SA 4.0
TRACKER_CATEGORIES = ("Advertising", "Analytics", "Social")  # in priority order
CONSENT = re.compile(r"agree|consent|accept|terms|privacy", re.I)
TERMS = re.compile(r"terms|conditions|privacy", re.I)
MARKETING = re.compile(r"marketing|promotion|newsletter|offers|advert", re.I)

CHECKBOXES_JS = """() => [...document.querySelectorAll('input[type=checkbox]')].map(el => {
  const label = el.closest('label') || (el.id && document.querySelector(`label[for="${el.id}"]`))
  return { checked: el.checked,
           label: (label ? label.textContent : el.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim() }
})"""


@lru_cache
def _domains() -> dict[str, tuple[str, str]]:
    """domain -> (category, company). A domain listed in several categories keeps the first by priority."""
    categories = json.loads(SERVICES.read_text())["categories"]
    table: dict[str, tuple[str, str]] = {}
    for category in TRACKER_CATEGORIES:
        for entry in categories.get(category, []):
            for company, sites in entry.items():
                for domains in sites.values():
                    for domain in domains:
                        table.setdefault(domain, (category, company))
    return table


def classify(host: str) -> tuple[str, str] | None:
    """(category, company) if host or a parent domain is a known tracker, else None. Never matches a bare TLD."""
    parts = host.lower().rstrip(".").split(".")
    table = _domains()
    for i in range(len(parts) - 1):
        if hit := table.get(".".join(parts[i:])):
            return hit
    return None


def _first_party(host: str | None) -> bool:
    return not host or is_local(f"http://{host}")


def stub_third_party(route) -> None:
    """Let local requests through. Answer everything else with an empty 200 so no data leaves the machine."""
    request = route.request
    if _first_party(urlparse(request.url).hostname):
        route.continue_()
    else:
        route.fulfill(status=200, body="",
                      content_type="application/javascript" if request.resource_type == "script" else "text/plain")


def _bare(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path}"  # query strings can carry data, so they never go into evidence


def scan(frontend_url: str | None) -> list[Finding]:
    if not frontend_url:
        raise RuntimeError("browser_scan needs a frontend URL (config.FRONTEND_URL)")
    if not is_local(frontend_url):
        raise ValueError(f"browser_scan only opens localhost or private addresses: {frontend_url}")
    try:
        httpx.get(frontend_url, timeout=config.HTTP_TIMEOUT).raise_for_status()  # fail fast, before starting a browser
    except httpx.HTTPError as e:
        raise RuntimeError(f"frontend not reachable at {frontend_url}: {e}") from e

    requested: list[str] = []
    with sync_playwright() as p:
        browser = launch(p)
        try:
            page = browser.new_context().new_page()
            page.on("request", lambda r: requested.append(r.url))
            page.route("**/*", stub_third_party)
            page.goto(frontend_url, wait_until="load", timeout=15000)  # no clicks, ever
            for wait in (lambda: page.wait_for_selector("input[type=checkbox]", timeout=5000),
                         lambda: page.wait_for_load_state("networkidle", timeout=3000)):
                try:
                    wait()  # the page is a React app: wait for the form, then for late requests
                except PlaywrightTimeout:
                    pass
            boxes = page.evaluate(CHECKBOXES_JS)
        finally:
            browser.close()
    return _tracker_finding(frontend_url, requested) + _consent_finding(frontend_url, boxes)


def _tracker_finding(frontend_url: str, requested: list[str]) -> list[Finding]:
    seen: dict[str, tuple[str, str, str]] = {}  # host -> (category, company, bare url), in request order
    for url in requested:
        host = urlparse(url).hostname
        if host and not _first_party(host) and host not in seen and (hit := classify(host)):
            seen[host] = (*hit, _bare(url))
    if not seen:
        return []
    return [Finding(
        id="", check="tracker_before_consent", layer="browser", severity="high",
        title="Tracking script loads before any consent",
        explanation="The signup page contacts an advertising or social tracker as soon as it opens, before the user has agreed to anything. "
                    "This likely does not meet the consent expected before tracking, and it matters more because the users are children.",
        clauses=[],
        evidence=Evidence(
            kind="network",
            summary="Before any click, the page requested " + "; ".join(
                f"{host} ({category}, {company})" for host, (category, company, _) in seen.items()),
            masked_sample=next(iter(seen.values()))[2], location=Location(url=frontend_url)),
        fix=Fix(available=True))]


def _consent_finding(frontend_url: str, boxes: list[dict]) -> list[Finding]:
    consent = [b for b in boxes if CONSENT.search(b["label"])]
    ticked = [b for b in consent if b["checked"]]
    bundled = [b for b in consent if TERMS.search(b["label"]) and MARKETING.search(b["label"])]
    if not ticked and not bundled:
        return []
    problems = [text for text, hit in (("is already ticked", ticked), ("bundles terms with marketing", bundled)) if hit]
    box = (ticked or bundled)[0]
    return [Finding(
        id="", check="consent_bundled", layer="browser", severity="medium",
        title="Consent box is pre-ticked or bundled with marketing",
        explanation="The consent checkbox is already ticked, or one box covers both the terms and marketing messages. "
                    "This likely does not meet the requirement for free, specific and unambiguous consent given by a clear action.",
        clauses=[],
        evidence=Evidence(kind="dom", summary=f"The consent checkbox {' and '.join(problems)}",
                          masked_sample=box["label"], location=Location(url=frontend_url)),
        fix=Fix(available=False))]
