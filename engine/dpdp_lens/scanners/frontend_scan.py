"""frontend_scan: the front end SOURCE (docs/15 S4). Static and read only.
observe(): personal data fields the signup form collects, for the notice drift block.
scan(): personal data written to localStorage or sessionStorage (fe_pii_in_storage). Paths are relative to app_root."""
import re
from pathlib import Path

from .. import hints
from ..checks import reason
from ..locator import MAX_FILES, _files, read_capped
from ..models import Evidence, Finding, Fix, Location
from .log_scan import js_code_view

SUFFIXES = (".html", ".jsx", ".tsx", ".ts", ".js")
JS_SUFFIXES = (".jsx", ".tsx", ".js", ".ts", ".mjs", ".cjs")
# (drift field, lower case identifier pattern). parent_pan comes before pan.
FIELD_HINTS = [
    ("parent_pan", r"parent[_-]?pan"), ("aadhaar", r"aadhaa?r"), ("pan", r"(?:^|[_-])pan$|permanent"),
    ("dob", r"(?:^|[_-])dob$|birth"), ("phone", r"phone|mobile"), ("email", r"e-?mail"), ("name", r"(?:^|[_-])name$")]
NOT_PII = {"age", "password", "consent", "terms", "confirm"}  # form controls that are not personal data fields
TAG = re.compile(r"<(?:input|select|textarea)\b", re.I)
ATTR = re.compile(r"""\b(name|id)\s*=\s*["']([^"']+)["']""")
STORAGE = re.compile(r"\b(localStorage|sessionStorage)\.setItem\s*\(")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def classify(identifier: str) -> str:
    """The drift field an identifier names, or ''."""
    low = identifier.lower()
    return next((field for field, pattern in FIELD_HINTS if re.search(pattern, low)), "")


def _tag_end(text: str, start: int) -> int:
    """Index of the `>` that closes the tag at start. Skips quotes and {braces}, so `=>` inside onChange is not the end."""
    depth, quote = 0, ""
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == ">" and depth <= 0:
            return i
    return len(text)


def _call_end(text: str, start: int) -> int:
    """Index after the `)` that closes the call whose `(` sits just before start."""
    depth = 1
    for i in range(start, len(text)):
        depth += (text[i] == "(") - (text[i] == ")")
        if depth == 0:
            return i + 1
    return len(text)


def _source_files(root: Path):
    for rel in _files(root, MAX_FILES):
        if rel.startswith("frontend/") and rel.endswith(SUFFIXES):
            try:
                yield rel, read_capped(root, rel)
            except (OSError, UnicodeDecodeError):
                continue


def observe(app_root) -> list[tuple[str, str]]:
    """(drift field, "frontend:<file>:<line>") for each form control that names a personal data field."""
    root, found, unknown = Path(app_root), [], []
    for rel, text in _source_files(root):
        for tag in TAG.finditer(text):
            body = text[tag.start():_tag_end(text, tag.start())]
            attrs = {k: (v, tag.start() + m.start()) for m in ATTR.finditer(body) for k, v in [(m.group(1), m.group(2))]}
            ident, at = attrs.get("name") or attrs.get("id") or ("", 0)
            if not ident or ident.lower() in NOT_PII:
                continue
            line = text.count("\n", 0, at) + 1
            if field := classify(ident):
                found.append((field, f"frontend:{rel}:{line}"))
            else:
                unknown.append((ident, f"frontend:{rel}:{line}"))
    if unknown:  # names no rule classified: the ML hook decides, an empty answer changes nothing
        guess = hints.semantic_hints([ident for ident, _ in unknown])
        found += [(guess[ident], where) for ident, where in unknown if guess.get(ident)]
    return found


def scan(app_root) -> list[Finding]:
    root, out = Path(app_root), []
    for rel, text in _source_files(root):
        if rel.endswith(JS_SUFFIXES):
            text = js_code_view(text, keep_strings=True)  # a call in a comment is not a call (same length, same line numbers)
        for m in STORAGE.finditer(text):
            call = text[m.start():_call_end(text, m.end())]
            fields = list(dict.fromkeys(f for w in WORD.findall(call[m.end() - m.start():]) if (f := classify(w))))
            if not fields:
                continue
            line = text.count("\n", 0, m.start()) + 1
            names = ", ".join(fields)
            out.append(Finding(
                id="", check="fe_pii_in_storage", layer="frontend", severity="medium",
                title="Personal data kept in browser storage",
                severity_reason=reason("fe_pii_in_storage", fields=names, storage=m.group(1)),
                explanation=f"The page saves {names} in {m.group(1)}, where any script on the page can read it and it stays after the tab is closed. "
                            "This likely does not meet the safeguard expected for protecting personal data in the browser.",
                clauses=[],
                evidence=Evidence(kind="code", summary=f"{m.group(1)}.setItem stores {names} in {rel}",
                                  masked_sample=" ".join(call.split())[:160],  # code only, never a stored value
                                  location=Location(file=rel, line=line)),
                fix=Fix(available=False)))
            break  # one finding per file
    return out
