"""api_pii_exposure: unauthenticated GET routes that return personal data. GET only, no bodies."""
import httpx

from .. import config
from ..models import Evidence, Finding, Fix, Location
from ..recognizers import find_pii, is_name_column

# Never probed: docs, schema, health and the static notice page.
SKIP_PATHS = {"/health", "/openapi.json", "/docs", "/redoc", "/notice"}


def pii_matches(obj, key=None, out=None) -> dict[str, tuple[str, str]]:
    """Field name -> (pii type, masked sample) for the first PII value seen under that key.
    The JSON key is passed to find_pii as the column hint (e.g. 'aadhaar')."""
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            pii_matches(v, k, out)
    elif isinstance(obj, list):
        for v in obj:
            pii_matches(v, key, out)
    elif isinstance(obj, (str, int)) and not isinstance(obj, bool):
        for t, _, _, masked in find_pii(str(obj), key):
            out.setdefault(key or t, (t, masked))
    return out


def pii_fields(obj) -> dict[str, str]:
    """Field name -> masked sample."""
    return {k: masked for k, (_, masked) in pii_matches(obj).items()}


def _open_routes(target_url: str, transport=None):
    """(path, JSON body) for every GET route without a path parameter that answers 200 JSON with no login."""
    with httpx.Client(base_url=target_url, timeout=config.HTTP_TIMEOUT, transport=transport) as c:
        paths = c.get("/openapi.json").raise_for_status().json().get("paths", {})
        routes = [p for p, ops in paths.items()
                  if "get" in ops and "{" not in p and p not in SKIP_PATHS]
        for path in routes[:config.MAX_REQUESTS]:
            try:
                r = c.get(path)  # no Authorization header on purpose
            except httpx.HTTPError:
                continue
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                yield path, r.json()


def name_keys(obj, key=None, out=None) -> set[str]:
    """JSON keys like 'name' that hold a non-empty string. Column context only, as names have no value pattern."""
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            name_keys(v, k, out)
    elif isinstance(obj, list):
        for v in obj:
            name_keys(v, key, out)
    elif isinstance(obj, str) and obj.strip() and is_name_column(key):
        out.add(key)
    return out


def observe(target_url: str, transport=None) -> list[tuple[str, str, str]]:
    """(path, field name, pii type) for PII an unauthenticated GET returns. A name key is reported as type 'name'."""
    found = []
    for path, body in _open_routes(target_url, transport):
        found += [(path, key, t) for key, (t, _) in pii_matches(body).items()]
        found += [(path, key, "name") for key in sorted(name_keys(body))]
    return found


def scan(target_url: str, transport=None) -> list[Finding]:
    findings = []
    for path, body in _open_routes(target_url, transport):
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
