"""notice_drift: personal data the app handles that the public privacy notice does not list.
Declared = fields named in the notice's list items. Observed = PII found in the DB and in open API responses."""
import re

import httpx

from .. import config
from ..htmltext import list_items, visible_text
from ..models import Evidence, Finding, Fix, Location, NoticeDrift, ObservedField
from . import api_scan, db_scan

ORDER = ["name", "email", "phone", "dob", "aadhaar", "pan", "parent_pan"]  # fixed order keeps scans deterministic
KEYWORDS = {
    "name": r"\bname\b", "email": r"e-?mail", "phone": r"phone|mobile", "dob": r"date of birth|birth ?date|\bdob\b",
    "aadhaar": r"aadhaa?r", "pan": r"\bpan\b|permanent account", "parent_pan": r"\bpan\b|permanent account"}


def field_name(pii_type: str, column: str) -> str:
    """A PAN under a 'parent' column or key is the parent's PAN."""
    return "parent_pan" if pii_type == "pan" and "parent" in column.lower() else pii_type


def declared_fields(html: str) -> list[str]:
    """Fields the notice lists. Looks at list items (Rule 3: itemise the data), or at the visible text if there is no list."""
    text = " ".join(list_items(html)) or visible_text(html)
    return [f for f in ORDER if re.search(KEYWORDS[f], text, re.I)]


def observed_fields(target_url: str, db_path: str) -> list[ObservedField]:
    where: dict[str, list[str]] = {}
    for table, column, pii_type, _ in db_scan.observe(db_path):
        where.setdefault(field_name(pii_type, column), []).append(f"db:{table}.{column}")
    for path, key, pii_type in api_scan.observe(target_url):
        where.setdefault(field_name(pii_type, key), []).append(f"api:{path}")
    return [ObservedField(field=f, where=list(dict.fromkeys(where[f]))) for f in ORDER if f in where]


def build(target_url: str, db_path: str) -> NoticeDrift:
    try:
        notice = httpx.get(f"{target_url.rstrip('/')}/notice", timeout=config.HTTP_TIMEOUT).raise_for_status().text
    except httpx.HTTPError as e:
        raise RuntimeError(f"could not read the privacy notice: {e}") from e
    declared = declared_fields(notice)
    observed = observed_fields(target_url, db_path)
    return NoticeDrift(declared=declared, observed=observed,
                       undeclared=[o.field for o in observed if o.field not in declared])


def finding(drift: NoticeDrift, notice_url: str) -> Finding:
    return Finding(
        id="", check="notice_drift", layer="notice", severity="medium",
        title="Collected personal data is not listed in the privacy notice",
        explanation="The app handles personal data that its public privacy notice does not list. "
                    "This likely does not meet the duty to itemise the personal data in the notice.",
        clauses=[],
        evidence=Evidence(
            kind="http",
            summary=f"The notice lists {', '.join(drift.declared) or 'no fields'}. Also found in the app: {', '.join(drift.undeclared)}",
            masked_sample=", ".join(drift.undeclared),  # field names only, never values
            location=Location(url=notice_url)),
        fix=Fix(available=False))
