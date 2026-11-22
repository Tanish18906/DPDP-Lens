"""children_no_parental_consent: sign up one synthetic 14 year old with no parent data.
If the app accepts it, flag it. The probe removes its own rows afterwards, so repeat scans give the same result."""
import httpx

from .. import config
from ..models import Evidence, Finding, Fix, Location
from ..recognizers import mask_email
from .erasure_scan import PROBE_PASSWORD, _cleanup, _marker


def scan(target_url: str, db_path: str, transport=None) -> list[Finding]:
    email, aadhaar = _marker()  # synthetic: fake email, Verhoeff-valid fake Aadhaar
    try:
        with httpx.Client(base_url=target_url, timeout=config.HTTP_TIMEOUT, transport=transport) as c:
            r = c.post("/api/signup", json={
                "name": "Child Probe", "email": email, "phone": "9000000002", "dob": "2012-01-01", "age": 14,
                "aadhaar": aadhaar, "password": PROBE_PASSWORD})  # no parent_pan, no parental consent field
    finally:
        _cleanup(db_path, (email, aadhaar))
    if r.status_code not in (200, 201):
        return []
    return [Finding(
        id="", check="children_no_parental_consent", layer="api", severity="high",
        title="Under-18 signup accepted with no parental consent",
        explanation="A signup for a 14 year old was accepted with no step to verify a parent or guardian. "
                    "The Act asks for verifiable consent of a parent before processing a child's data.",
        clauses=[],
        evidence=Evidence(
            kind="http",
            summary=f"POST /api/signup with age 14 and no parent data returned {r.status_code}",
            masked_sample=f"email={mask_email(email)}",  # same every run, so scans stay deterministic
            location=Location(url=f"{target_url.rstrip('/')}/api/signup")),
        fix=Fix(available=True))]
