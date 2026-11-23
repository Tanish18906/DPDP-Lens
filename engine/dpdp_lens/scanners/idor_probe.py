"""api_idor: can user A read user B's record through an id route? GET only, demo logins from config."""
import re

import httpx

from .. import config
from ..checks import reason
from ..models import Evidence, Finding, Fix, Location
from .api_scan import pii_fields

_ID_ROUTE = re.compile(r"^[^{}]*\{(\w*id)\}[^{}]*$")  # exactly one id path parameter


def _login(c: httpx.Client, creds: dict) -> tuple[dict, dict]:
    r = c.post("/api/login", json={"email": creds["email"], "password": creds["password"]})
    r.raise_for_status()
    body = r.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


def scan(target_url: str, users: dict | None = None, transport=None) -> list[Finding]:
    users = users or config.DEMO_USERS
    findings = []
    with httpx.Client(base_url=target_url, timeout=config.HTTP_TIMEOUT, transport=transport) as c:
        a_hdr, a = _login(c, users["user_a"])
        _, b = _login(c, users["user_b"])
        paths = c.get("/openapi.json").raise_for_status().json().get("paths", {})
        for path, ops in paths.items():
            m = _ID_ROUTE.match(path)
            if "get" not in ops or not m:
                continue
            param = "{" + m.group(1) + "}"
            own = c.get(path.replace(param, str(a["id"])), headers=a_hdr)
            if own.status_code != 200:  # control: route must work for A's own record
                continue
            other = c.get(path.replace(param, str(b["id"])), headers=a_hdr)
            if other.status_code != 200 or "json" not in other.headers.get("content-type", ""):
                continue
            body = other.json()
            if not isinstance(body, dict) or (body.get("id") != b["id"] and body.get("email") != b["email"]):
                continue
            fields = pii_fields(body)
            findings.append(Finding(
                id="", check="api_idor", layer="api", severity="critical",
                title="Any logged-in user can read other users' records",
                severity_reason=reason("api_idor"),
                explanation=f"GET {path} returns another user's record to a logged-in user without checking ownership. "
                            "This likely does not meet the access control expected for reasonable security safeguards.",
                clauses=[],
                evidence=Evidence(
                    kind="http",
                    summary=f"user {a['id']} read the record of user {b['id']} via GET {path}",
                    masked_sample="; ".join(f"{k}={v}" for k, v in fields.items()),
                    location=Location(url=f"{target_url.rstrip('/')}{path}")),
                fix=Fix(available=True)))
    return findings
