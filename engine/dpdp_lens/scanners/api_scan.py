"""api_pii_exposure: unauthenticated GET routes that return personal data. GET only, no bodies."""
import httpx

from .. import config
from ..models import Evidence, Finding, Fix, Location
from ..recognizers import find_pii

# Never probed: docs, schema, health and the static notice page.
SKIP_PATHS = {"/health", "/openapi.json", "/docs", "/redoc", "/notice"}


def pii_fields(obj, key=None, out=None) -> dict[str, str]:
    """Field name -> masked sample for the first PII value seen under that key.
    The JSON key is passed to find_pii as the column hint (e.g. 'aadhaar')."""
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            pii_fields(v, k, out)
    elif isinstance(obj, list):
        for v in obj:
            pii_fields(v, key, out)
    elif isinstance(obj, (str, int)) and not isinstance(obj, bool):
        for t, _, _, masked in find_pii(str(obj), key):
            out.setdefault(key or t, masked)
    return out


def scan(target_url: str, transport=None) -> list[Finding]:
    findings = []
    with httpx.Client(base_url=target_url, timeout=config.HTTP_TIMEOUT, transport=transport) as c:
        paths = c.get("/openapi.json").raise_for_status().json().get("paths", {})
        routes = [p for p, ops in paths.items()
                  if "get" in ops and "{" not in p and p not in SKIP_PATHS]
        for path in routes[:config.MAX_REQUESTS]:
            try:
                r = c.get(path)  # no Authorization header on purpose
            except httpx.HTTPError:
                continue
            if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
                continue
            body = r.json()
            fields = pii_fields(body)
            if not fields:
                continue
            n = len(body) if isinstance(body, list) else 1
            findings.append(Finding(
                id="", check="api_pii_exposure", layer="api", severity="critical",
                title="Public API endpoint exposes personal data",
                explanation=f"GET {path} returns personal data to anyone, with no login. "
                            "This likely does not meet the access control expected for reasonable security safeguards.",
                clauses=[],
                evidence=Evidence(
                    kind="http",
                    summary=f"GET {path} returned {n} record(s) with {', '.join(fields)} without login",
                    masked_sample="; ".join(f"{k}={v}" for k, v in fields.items()),
                    location=Location(url=f"{target_url.rstrip('/')}{path}")),
                fix=Fix(available=True)))
    return findings
