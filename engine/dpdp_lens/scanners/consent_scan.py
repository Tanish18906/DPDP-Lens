"""consent_scan: two static consent lifecycle checks (docs/15 S5, bonus).
consent_not_recorded: no consent table, column or model field in the schema or source. Comments and the front end do not count.
consent_no_withdrawal: no route in the running app's OpenAPI spec for consent, withdraw, revoke, opt out or unsubscribe.
Wording is "no consent record found in the schema or source", never "does not record consent": a static scan cannot see everything."""
import ast
import re
from pathlib import Path

import httpx

from .. import config
from ..checks import reason
from ..locator import MAX_FILES, _files, read_capped
from ..models import Evidence, Finding, Fix, Location

CONSENT = re.compile(r"consent", re.I)
WITHDRAW = re.compile(r"consent|withdraw|revoke|opt[-_ ]?out|unsubscribe", re.I)
CREATE = re.compile(r"CREATE\s+TABLE", re.I)


def _in_ast(tree: ast.AST) -> bool:
    """A class (model) with a consent field, or a table name that says consent."""
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for n in cls.body:
            targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
            if any(isinstance(t, ast.Name) and CONSENT.search(t.id) for t in targets):
                return True
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str) and CONSENT.search(n.value.value):
                return True  # __tablename__ = "consents"
    return False


def _in_create_table(text: str) -> bool:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if CREATE.search(line):
            for j in range(i, min(i + 80, len(lines))):
                if j > i and lines[j].lstrip().startswith(")"):
                    break
                if CONSENT.search(lines[j]):
                    return True
    return False


def has_consent_record(app_root) -> tuple[bool, int]:
    """(found, number of schema and source files read). Tests and the front end are not read."""
    root, read = Path(app_root), 0
    for rel in _files(root, MAX_FILES):
        p = Path(rel)
        if not rel.endswith((".py", ".sql")) or rel.startswith("frontend/") or "tests" in p.parts or p.name.startswith("test_") or p.name == "conftest.py":
            continue
        try:
            text = read_capped(root, rel)
        except (OSError, UnicodeDecodeError):
            continue
        read += 1
        try:
            if rel.endswith(".py") and _in_ast(ast.parse(text)):
                return True, read
        except (SyntaxError, ValueError):
            pass
        if _in_create_table(text):
            return True, read
    return False, read


def _finding(check, layer, kind, title, summary, sample, explanation, fix_available=False, **facts) -> Finding:
    return Finding(
        id="", check=check, layer=layer, severity="medium", title=title, severity_reason=reason(check, **facts),
        explanation=explanation, clauses=[],
        evidence=Evidence(kind=kind, summary=summary, masked_sample=sample, location=Location()),  # the runner adds the signup handler
        fix=Fix(available=fix_available))


def scan(target_url: str, app_root) -> list[Finding]:
    """Without a target_url (static mode) only consent_not_recorded runs: consent_no_withdrawal needs the live OpenAPI spec."""
    out = []
    found, read = has_consent_record(app_root)
    if not found:
        out.append(_finding(
            "consent_not_recorded", "code", "code", "No consent record found in the schema or source",
            f"No consent table, column or model field was found in {read} schema and source files", "",
            "We found no place where a consent is stored, so the app may not be able to show who agreed to what and when. "
            "This likely does not meet the duty to be able to prove notice and consent."))
    if not target_url:
        return out
    r = httpx.get(f"{target_url.rstrip('/')}/openapi.json", timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()  # without the spec the check cannot say anything, so the runner logs a scanner error
    paths = sorted(r.json().get("paths", {}))
    if not any(WITHDRAW.search(p) for p in paths):
        out.append(_finding(
            "consent_no_withdrawal", "api", "http", "No consent withdrawal route found",
            f"None of the {len(paths)} routes in the OpenAPI spec is about consent, withdrawal, opt out or unsubscribe",
            ", ".join(paths)[:200],
            "The API has no route that lets a person withdraw consent. "
            "This likely does not meet the duty to make withdrawal as easy as giving consent and to stop processing after it.", n=len(paths)))
    return out
