"""notice_drift: personal data the app handles that the public privacy notice does not list.
Declared = fields named in the notice's list items. Observed = PII found in the DB and in open API responses."""
import re

import httpx

from .. import config
from ..htmltext import list_items, visible_text
from ..checks import reason
from ..models import Evidence, Finding, Fix, Location, NoticeDrift, ObservedField, UndeclaredDetail
from . import api_scan, db_scan

ORDER = ["name", "email", "phone", "dob", "aadhaar", "pan", "parent_pan"]  # fixed order keeps scans deterministic
KEYWORDS = {
    "name": r"\bname\b", "email": r"e-?mail", "phone": r"phone|mobile", "dob": r"date of birth|birth ?date|\bdob\b",
    "aadhaar": r"aadhaa?r", "pan": r"\bpan\b|permanent account", "parent_pan": r"\bpan\b|permanent account"}


NEEDS_REVIEW = {"aadhaar", "parent_pan", "dob"}  # sensitive: the first question is whether to collect it at all
REVIEW_NOTE = ("Check whether you need this field for a stated purpose. If not, stop collecting it. "
               "If yes, the notice must itemise it with its specific purpose (Act s5, Rule 3).")


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
    for table, column in db_scan.observe_names(db_path):
        where.setdefault("name", []).append(f"db:{table}.{column}")
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
    undeclared = [o for o in observed if o.field not in declared]
    return NoticeDrift(
        declared=declared, observed=observed, undeclared=[o.field for o in undeclared],
        undeclared_detail=[UndeclaredDetail(
            field=o.field, where=o.where, needs_review=o.field in NEEDS_REVIEW,
            review_note=REVIEW_NOTE if o.field in NEEDS_REVIEW else "") for o in undeclared])


def finding(drift: NoticeDrift, notice_url: str) -> Finding:
    return Finding(
        id="", check="notice_drift", layer="notice", severity="medium",
        title="Collected personal data is not listed in the privacy notice",
        severity_reason=reason("notice_drift", n=len(drift.undeclared)),
        explanation="The app handles personal data that its public privacy notice does not list. "
                    "This likely does not meet the duty to itemise the personal data in the notice.",
        clauses=[],
        evidence=Evidence(
            kind="http",
            summary=f"The notice lists {', '.join(drift.declared) or 'no fields'}. Also found in the app: {', '.join(drift.undeclared)}",
            masked_sample=", ".join(drift.undeclared),  # field names only, never values
            location=Location(url=notice_url)),
        fix=Fix(available=False))  # the notice-align fix is built and tested but not offered yet: the demo path stays as rehearsed
