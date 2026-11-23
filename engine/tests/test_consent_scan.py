from pathlib import Path

import httpx
import pytest

from dpdp_lens.scanners import consent_scan
from dpdp_lens.scanners.consent_scan import has_consent_record, scan

CLEAN = Path(__file__).parent / "fixtures" / "clean_app"
TARGET_APP = Path(__file__).resolve().parents[2] / "target-app"


def spec(monkeypatch, paths):
    monkeypatch.setattr(consent_scan.httpx, "get", lambda url, **k: httpx.Response(
        200, json={"paths": {p: {} for p in paths}}, request=httpx.Request("GET", url)))


def write(tmp_path, files):
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return tmp_path


@pytest.mark.parametrize("files", [
    {"app/models.py": "class Signup:\n    name: str\n    consent_given: bool\n"},
    {"app/models.py": "class Consent:\n    __tablename__ = 'consents'\n    id = 1\n"},
    {"app/db.py": 'cur.execute("""\nCREATE TABLE IF NOT EXISTS students (\n  id INTEGER,\n  consent_at TEXT\n)\n""")\n'},
    {"schema.sql": "CREATE TABLE consent_log (id INTEGER);\n"},
])
def test_a_consent_field_column_or_table_counts(tmp_path, files):
    assert has_consent_record(write(tmp_path, files))[0] is True


@pytest.mark.parametrize("files", [
    {"app/main.py": "# TODO consent check\nx = 'consent'\ndef consent(): ...\n"},  # comments, strings and functions are not a record
    {"frontend/src/App.jsx": "const consent = true", "tests/test_a.py": "class T:\n    consent = 1\n"},
    {"app/db.py": 'cur.execute("""\nCREATE TABLE students (\n  id INTEGER\n)\n""")  # consent later\n'},
])
def test_comments_front_end_tests_and_other_tables_do_not_count(tmp_path, files):
    found, read = has_consent_record(write(tmp_path, files))
    assert found is False


def test_both_findings_when_nothing_is_there(tmp_path, monkeypatch):
    spec(monkeypatch, ["/api/signup", "/api/login"])
    found = scan("http://x", write(tmp_path, {"app/main.py": "x = 1\n"}))
    assert [(f.check, f.layer, f.severity) for f in found] == [("consent_not_recorded", "code", "medium"), ("consent_no_withdrawal", "api", "medium")]
    assert "no consent record found in the schema or source" in found[0].severity_reason
    assert "does not record consent" not in found[0].model_dump_json()  # wording rule: never claim more than a static scan knows
    assert "none of the 2 API routes" in found[1].severity_reason


@pytest.mark.parametrize("path", ["/api/consent", "/api/consent/withdraw", "/me/opt-out", "/unsubscribe", "/api/revoke"])
def test_any_consent_related_route_clears_the_withdrawal_finding(tmp_path, monkeypatch, path):
    spec(monkeypatch, ["/api/signup", path])
    assert [f.check for f in scan("http://x", write(tmp_path, {"a.py": "x = 1\n"}))] == ["consent_not_recorded"]


def test_fixture_with_a_consent_table_and_a_withdraw_route_has_neither(monkeypatch):
    spec(monkeypatch, ["/api/consent/withdraw"])
    assert scan("http://x", CLEAN) == []


def test_target_app_has_both(monkeypatch):
    spec(monkeypatch, ["/api/signup", "/api/login", "/api/students"])
    assert [f.check for f in scan("http://x", TARGET_APP)] == ["consent_not_recorded", "consent_no_withdrawal"]


def test_unreachable_spec_raises_so_the_runner_logs_a_scanner_error(tmp_path, monkeypatch):
    monkeypatch.setattr(consent_scan.httpx, "get", lambda url, **k: httpx.Response(404, request=httpx.Request("GET", url)))
    with pytest.raises(httpx.HTTPStatusError):
        scan("http://x", tmp_path)
