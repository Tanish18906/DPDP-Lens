"""missing_contact: no DPO or grievance contact on the notice page or the frontend home. Visible text only."""
import re

import httpx

from .. import config
from ..htmltext import visible_text
from ..checks import reason
from ..models import Evidence, Finding, Fix, Location

# Strict on purpose: a generic "contact us" line does not count as a DPO or grievance contact.
_KEYWORD = re.compile(r"dpo|data protection officer|grievance", re.I)
_REACH = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")
_NEAR = 100  # chars either side of the keyword


def has_contact(html: str) -> bool:
    text = visible_text(html)
    return any(_REACH.search(text[max(0, m.start() - _NEAR):m.end() + _NEAR]) for m in _KEYWORD.finditer(text))


def scan(target_url: str, frontend_url: str | None = config.FRONTEND_URL, transport=None) -> list[Finding]:
    urls = [f"{target_url.rstrip('/')}/notice"] + ([frontend_url] if frontend_url else [])
    checked = []
    with httpx.Client(timeout=config.HTTP_TIMEOUT, transport=transport, follow_redirects=True) as c:
        for url in urls:
            try:
                r = c.get(url)
            except httpx.HTTPError:
                continue  # frontend may not be running
            if r.status_code != 200:
                continue
            if has_contact(r.text):
                return []
            checked.append(url)
    if not checked:
        raise RuntimeError("contact_scan could not load any page, so it cannot say a contact is missing")
    return [Finding(
        id="", check="missing_contact", layer="notice", severity="low",
        title="No DPO or grievance contact published",
        severity_reason=reason("missing_contact"),
        explanation="The pages we checked do not give a Data Protection Officer or grievance contact. "
                    "This likely does not meet the duty to publish contact details and a grievance process.",
        clauses=[],
        evidence=Evidence(
            kind="http", summary=f"No DPO or grievance contact with an email or phone on: {', '.join(checked)}",
            location=Location(url=checked[0])),
        fix=Fix(available=False))]
