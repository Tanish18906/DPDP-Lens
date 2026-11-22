"""db_plaintext_pii: Aadhaar or PAN stored in plaintext columns. Read only SQLite, 20 sampled rows per column."""
import re
import sqlite3
from pathlib import Path

from ..models import Evidence, Finding, Fix, Location
from ..recognizers import find_pii

SAMPLE_ROWS = 20
FLAGGED = {"aadhaar", "pan"}  # phone, email and dob only go in the evidence list
HASHED = re.compile(r"^(?:[0-9a-fA-F]{32,128}|\$2[aby]\$.+|\$argon2.+)$")  # hex digest, bcrypt, argon2


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def scan(db_path: str) -> list[Finding]:
    findings = []
    con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for table in tables:
            hits: dict[str, str] = {}   # column -> masked sample, Aadhaar or PAN
            also: dict[str, str] = {}   # column -> masked sample, phone, email, dob
            for col in (r[1] for r in con.execute(f"PRAGMA table_info({_q(table)})")):
                rows = con.execute(
                    f"SELECT {_q(col)} FROM {_q(table)} WHERE {_q(col)} IS NOT NULL LIMIT {SAMPLE_ROWS}")
                for (value,) in rows:
                    text = str(value)
                    if HASHED.match(text):
                        continue
                    for pii_type, _, _, masked in find_pii(text, col):
                        (hits if pii_type in FLAGGED else also).setdefault(col, masked)
            if not hits:
                continue
            summary = f"Plaintext {', '.join(hits)} in table {table} (sampled up to {SAMPLE_ROWS} rows per column)"
            if also:
                summary += f". Also seen: {', '.join(also)}"
            findings.append(Finding(
                id="", check="db_plaintext_pii", layer="db", severity="high",
                title="Aadhaar or PAN stored in plaintext columns",
                explanation=f"Table {table} keeps Aadhaar or PAN numbers as readable text, with no encryption, masking or tokens. "
                            "This likely does not meet the safeguard expected for personal data at rest.",
                clauses=[],
                evidence=Evidence(
                    kind="db", summary=summary,
                    masked_sample="; ".join(f"{c}={m}" for c, m in hits.items()),
                    location=Location(table=table, column=", ".join(hits))),
                fix=Fix(available=False)))
    finally:
        con.close()
    return findings
