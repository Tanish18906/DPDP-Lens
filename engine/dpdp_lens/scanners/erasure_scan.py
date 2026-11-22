"""erasure_incomplete: sign up a synthetic user, delete it, then look for its PII left in the DB.
The probe removes its own marker rows afterwards, so repeat scans give the same result."""
import logging
import re
import secrets
import sqlite3
from pathlib import Path

import httpx
from stdnum.verhoeff import calc_check_digit

from .. import config
from ..models import Evidence, Finding, Fix, Location
from ..recognizers import mask_email
from .db_scan import _q

log = logging.getLogger("dpdp_lens")
LOG_TABLE = re.compile(r"log|audit", re.I)  # Rule 8(3): logs may be kept for at least 1 year
PROBE_PASSWORD = "ProbePass123!"  # synthetic


def _marker() -> tuple[str, str]:
    email = f"erasure-probe-{secrets.token_hex(4)}@example.test"
    digits = str(secrets.randbelow(8) + 2) + "".join(str(secrets.randbelow(10)) for _ in range(10))
    return email, digits + calc_check_digit(digits)  # Verhoeff-valid fake Aadhaar


def _matches(con: sqlite3.Connection, values: tuple[str, ...]) -> list[tuple[str, str, str]]:
    """(table, column, value) for every non-log column that holds a marker value."""
    found = []
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for table in tables:
        if LOG_TABLE.search(table):
            continue
        for col in (r[1] for r in con.execute(f"PRAGMA table_info({_q(table)})")):
            for v in values:
                if con.execute(f"SELECT 1 FROM {_q(table)} WHERE CAST({_q(col)} AS TEXT) = ? LIMIT 1", (v,)).fetchone():
                    found.append((table, col, v))
    return found


def _cleanup(db_path: str, values: tuple[str, ...]) -> None:
    """Delete only rows holding this probe's own marker values."""
    try:
        con = sqlite3.connect(db_path)
        try:
            for table, col, v in _matches(con, values):
                con.execute(f"DELETE FROM {_q(table)} WHERE CAST({_q(col)} AS TEXT) = ?", (v,))
            con.commit()
        finally:
            con.close()
    except sqlite3.Error as e:
        log.warning("erasure probe cleanup failed: %s", e)


def _step(r: httpx.Response, step: str, ok: tuple[int, ...]) -> dict:
    if r.status_code not in ok:
        raise RuntimeError(f"erasure probe {step} returned {r.status_code}")
    return r.json()


def scan(target_url: str, db_path: str, transport=None) -> list[Finding]:
    email, aadhaar = _marker()
    left: list[tuple[str, str, str]] = []
    try:
        with httpx.Client(base_url=target_url, timeout=config.HTTP_TIMEOUT, transport=transport) as c:
            created = _step(c.post("/api/signup", json={
                "name": "Erasure Probe", "email": email, "phone": "9000000001", "dob": "2000-01-01", "age": 25,
                "aadhaar": aadhaar, "password": PROBE_PASSWORD}), "signup", (200, 201))
            token = _step(c.post("/api/login", json={"email": email, "password": PROBE_PASSWORD}),
                          "login", (200,))["access_token"]
            _step(c.delete(f"/api/students/{created['id']}", headers={"Authorization": f"Bearer {token}"}),
                  "delete", (200,))
        con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            left = _matches(con, (email, aadhaar))
        finally:
            con.close()
    finally:
        _cleanup(db_path, (email, aadhaar))
    if not left:
        return []
    tables = sorted({t for t, _, _ in left})
    return [Finding(
        id="", check="erasure_incomplete", layer="db", severity="high",
        title="Personal data is still stored after deletion",
        explanation="After a delete request, the user's personal data is still in the database. "
                    "This likely does not meet the duty to erase data once the purpose is served or consent is withdrawn.",
        clauses=[],
        evidence=Evidence(
            kind="db",
            summary=f"After DELETE of a synthetic user, its data is still in: {', '.join(tables)}",
            masked_sample=f"email={mask_email(email)}",  # same every run, so scans stay deterministic
            location=Location(table=", ".join(tables))),
        fix=Fix(available=True))]
