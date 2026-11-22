import json

import httpx

from dpdp_lens.config import DEMO_USERS
from dpdp_lens.scanners import api_scan, idor_probe


def raw_values(target, ids=None):
    """Raw PII from the public V1 endpoint, only to prove the findings never contain it."""
    rows = httpx.get(f"{target}/api/students").json()
    rows = [r for r in rows if ids is None or r["id"] in ids]
    return [str(r[k]) for r in rows for k in ("aadhaar", "parent_pan", "phone", "email") if r.get(k)]


def test_api_scan_finds_v1_and_skips_health(target):
    findings = api_scan.scan(target)
    assert [f.check for f in findings] == ["api_pii_exposure"]
    f = findings[0]
    assert f.evidence.location.url.endswith("/api/students")
    assert f.severity == "critical" and f.fix.available
    for field in ("aadhaar", "parent_pan", "phone", "dob"):
        assert field in f.evidence.summary
    assert not any(x.evidence.location.url.endswith("/health") for x in findings)


def test_api_scan_evidence_is_masked(target):
    dumped = json.dumps([f.model_dump() for f in api_scan.scan(target)])
    assert "XXXX XXXX" in dumped
    for raw in raw_values(target):
        assert raw not in dumped


def test_idor_probe_finds_v2(target):
    findings = idor_probe.scan(target)
    assert [f.check for f in findings] == ["api_idor"]
    f = findings[0]
    assert f.evidence.summary.startswith("user 2 read the record of user 3")
    assert f.evidence.location.url.endswith("/api/students/{student_id}")
    dumped = json.dumps(f.model_dump())
    for raw in raw_values(target, ids={3}):
        assert raw not in dumped


def test_idor_probe_no_finding_when_owner_checked():
    users = {"user_a": {"id": 1, "email": "a@example.test"}, "user_b": {"id": 2, "email": "b@example.test"}}

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/openapi.json":
            return httpx.Response(200, json={"paths": {"/api/students/{student_id}": {"get": {}}}})
        if path == "/api/login":
            email = json.loads(req.content)["email"]
            u = next(u for u in users.values() if u["email"] == email)
            return httpx.Response(200, json={"access_token": f"t{u['id']}", "user": u})
        owner = req.headers.get("authorization") == f"Bearer t{path.rsplit('/', 1)[1]}"
        return httpx.Response(200, json={"id": int(path.rsplit('/', 1)[1]), "email": "x@example.test"}) if owner \
            else httpx.Response(403, json={"detail": "forbidden"})

    cfg = {k: {**v, "password": "x"} for k, v in users.items()}
    assert idor_probe.scan("http://mock", users=cfg, transport=httpx.MockTransport(handler)) == []


def test_demo_logins_come_from_config():
    assert {"user_a", "user_b", "admin"} <= set(DEMO_USERS)
