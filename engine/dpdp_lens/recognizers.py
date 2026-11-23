"""PII recognizers and maskers. Column name context first, value check second.

find_pii(text, column=None) -> list of (type, start, end, masked). Raw values never leave this module.
"""
import re

from stdnum.in_ import aadhaar as _aadhaar

# Context words. Used on column names and on the text near a match.
_CTX = {
    "aadhaar": re.compile(r"(?<![a-z])(aadhaa?r|uid)"),
    "pan": re.compile(r"(?<![a-z])pan(?![a-z])"),
    "phone": re.compile(r"(?<![a-z])(phone|mobile|contact)"),
    "email": re.compile(r"email"),
    "dob": re.compile(r"(?<![a-z])(dob|birth)"),
}
_WINDOW = 20  # chars either side of a match that count as "nearby"

_AADHAAR_RE = re.compile(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)")
_PAN_RE = re.compile(r"\b[A-Z]{3}[PCHFATBLJG][A-Z](?!0000)\d{4}[A-Z]\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{9}\b")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_DOB_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}-\d{2}-\d{2}(?!\d)")


def mask_aadhaar(v: str) -> str:
    return "XXXX XXXX " + re.sub(r"\D", "", v)[-4:]


def mask_pan(v: str) -> str:
    return "XXXXX" + v[5:]


def mask_phone(v: str) -> str:
    d = re.sub(r"\D", "", v)[-10:]
    return d[:2] + "XXXXXX" + d[-2:]


def mask_email(v: str) -> str:
    local, _, domain = v.partition("@")
    return local[:1] + "***@" + domain


def mask_dob(v: str) -> str:
    return v[:4] + "-XX-XX"  # year only


_MASKERS = {"aadhaar": mask_aadhaar, "pan": mask_pan, "phone": mask_phone,
            "email": mask_email, "dob": mask_dob}


def mask(pii_type: str, value: str) -> str:
    return _MASKERS[pii_type](value)


_NAME_COL = re.compile(r"(?:^|_)name$")


def is_name_column(column: str | None) -> bool:
    """Column or JSON key that holds a person's name: 'name', 'full_name', 'parent_name'. Not 'username'."""
    return bool(column and _NAME_COL.search(column.lower()))


def column_hint(column: str | None) -> str | None:
    """PII type a column name suggests, or None."""
    if not column:
        return None
    name = column.lower()
    for t, rx in _CTX.items():
        if rx.search(name):
            return t
    return None


def find_pii(text: str, column: str | None = None) -> list[tuple[str, int, int, str]]:
    """Find PII in text. Aadhaar and phone need column or nearby-word context."""
    hint = column_hint(column)
    out = []

    def has_ctx(t, m):
        if hint == t:
            return True
        near = text[max(0, m.start() - _WINDOW):m.end() + _WINDOW].lower()
        return bool(_CTX[t].search(near))

    for m in _AADHAAR_RE.finditer(text):
        if _aadhaar.is_valid(m.group()) and has_ctx("aadhaar", m):
            out.append(("aadhaar", m.start(), m.end(), mask_aadhaar(m.group())))
    for m in _PAN_RE.finditer(text):
        out.append(("pan", m.start(), m.end(), mask_pan(m.group())))
    for m in _PHONE_RE.finditer(text):
        if has_ctx("phone", m):
            out.append(("phone", m.start(), m.end(), mask_phone(m.group())))
    for m in _EMAIL_RE.finditer(text):
        out.append(("email", m.start(), m.end(), mask_email(m.group())))
    for m in _DOB_RE.finditer(text):
        if has_ctx("dob", m):
            out.append(("dob", m.start(), m.end(), mask_dob(m.group())))
    return sorted(out, key=lambda x: x[1])
