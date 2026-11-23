import json
import sqlite3

import httpx
import pytest

from conftest import BACKEND
from dpdp_lens import runner
from dpdp_lens.htmltext import list_items, visible_text
from dpdp_lens.models import NoticeDrift, ObservedField
from dpdp_lens.recognizers import is_name_column
from dpdp_lens.scanners import db_scan, notice_drift
from dpdp_lens.scanners.notice_drift import declared_fields, field_name


# --- declared fields
def test_declared_fields_come_from_the_list_items_only():
    html = ("<h2>Data</h2><ul><li><strong>Name</strong></li><li>Email Address</li><li>Phone Number</li></ul>"
            "<p><em>(Notice Drift Note: does not declare Date of Birth, Aadhaar, Parent PAN)</em></p>"
            "<!-- Aadhaar --><script>var dob = 1</script>")
    assert declared_fields(html) == ["name", "email", "phone"]


def test_declared_fields_fall_back_to_visible_text_without_a_list():
    assert declared_fields("<p>We collect your name, e-mail and mobile number.</p><!-- aadhaar -->") == ["name", "email", "phone"]
    assert declared_fields("<p>We collect your date of birth, Aadhaar and PAN.</p>") == ["dob", "aadhaar", "pan", "parent_pan"]
    assert declared_fields("<p>Nothing here.</p>") == []


@pytest.mark.parametrize("item,expected", [
    ("Full Name", ["name"]), ("Student's name", ["name"]), ("Username", []), ("Surname", [])])
def test_declared_name_keyword(item, expected):
    assert declared_fields(f"<ul><li>{item}</li></ul>") == expected


@pytest.mark.parametrize("column,expected", [
    ("name", True), ("Full_Name", True), ("parent_name", True), ("username", False), ("name_hash", False), (None, False)])
def test_is_name_column(column, expected):
    assert is_name_column(column) is expected


def test_name_needs_a_non_empty_value(tmp_path):
    db = tmp_path / "n.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE a (name TEXT, username TEXT)")
    con.execute("CREATE TABLE b (full_name TEXT)")
    con.executemany("INSERT INTO a VALUES (?, ?)", [("", "x"), (None, "y")])
    con.execute("INSERT INTO b VALUES ('Test Person')")
    con.commit()
    con.close()
    assert db_scan.observe_names(str(db)) == [("b", "full_name")]


def test_html_helpers_ignore_comments_scripts_and_styles():
    html = "<style>li {}</style><ul><li>A <b>b</b></li></ul><!-- hidden --><script>x</script>"
    assert visible_text(html) == "A b" and list_items(html) == ["A b"]


@pytest.mark.parametrize("pii_type,column,expected", [
    ("pan", "parent_pan", "parent_pan"), ("pan", "Parent_PAN", "parent_pan"), ("pan", "pan", "pan"),
    ("aadhaar", "aadhaar", "aadhaar"), ("phone", "mobile", "phone")])
def test_field_name(pii_type, column, expected):
    assert field_name(pii_type, column) == expected


# --- against the real target (V1 still open, so the API exposes data too)
def test_real_target_drift(target, target_db):
    drift = notice_drift.build(target, str(target_db))
    assert drift.declared == ["name", "email", "phone"]
    assert [o.field for o in drift.observed] == ["name", "email", "phone", "dob", "aadhaar", "parent_pan"]
    assert drift.undeclared == ["dob", "aadhaar", "parent_pan"]  # name is observed and declared: no false drift
    where = {o.field: o.where for o in drift.observed}
    assert where["name"] == ["db:students.name", "api:/api/students"]
    assert where["aadhaar"] == ["db:students.aadhaar", "api:/api/students"]
    assert "db:students.parent_pan" in where["parent_pan"] and "api:/api/students" in where["dob"]


def test_drift_finding_names_fields_but_never_values(target, target_db):
    con = sqlite3.connect(target_db)
    raw = [v for row in con.execute("SELECT aadhaar, parent_pan, phone, email, dob FROM students") for v in row if v]
    con.close()
    drift = notice_drift.build(target, str(target_db))
    f = notice_drift.finding(drift, f"{target}/notice")
    assert (f.check, f.layer, f.severity, f.fix.available) == ("notice_drift", "notice", "medium", False)
    assert f.evidence.summary == "The notice lists name, email, phone. Also found in the app: dob, aadhaar, parent_pan"
    assert f.evidence.masked_sample == "dob, aadhaar, parent_pan"
    dumped = json.dumps([drift.model_dump(), f.model_dump()])
    assert not [v for v in raw if v in dumped]


def test_drift_is_deterministic(target, target_db):
    assert notice_drift.build(target, str(target_db)) == notice_drift.build(target, str(target_db))


def test_unreachable_notice_raises(tmp_path):
    with pytest.raises(RuntimeError, match="privacy notice"):
        notice_drift.build("http://127.0.0.1:9", str(tmp_path / "x.db"))


# --- in the runner
def test_runner_fills_the_block_and_appends_the_finding_last(target, target_db):
    r = runner.run_scan(target, str(BACKEND), str(target_db))
    assert r.findings[-1].check == "notice_drift" and r.findings[-1].id == "F-008"
    assert r.notice_drift.undeclared == ["dob", "aadhaar", "parent_pan"]
    assert [c.ref for c in r.findings[-1].clauses] == ["Act s5", "Rule 3"]


def test_no_finding_when_everything_is_declared(monkeypatch, target, target_db):
    monkeypatch.setattr(notice_drift, "build", lambda t, d, root=None: NoticeDrift(
        declared=["email"], observed=[ObservedField(field="email", where=["db:students.email"])], undeclared=[]))
    r = runner.run_scan(target, str(BACKEND), str(target_db))
    assert "notice_drift" not in [f.check for f in r.findings] and r.notice_drift.declared == ["email"]


def test_unreadable_notice_leaves_the_block_null_and_the_scan_alive(monkeypatch, target, target_db):
    def broken(t, d):
        raise RuntimeError("notice down")

    monkeypatch.setattr(notice_drift, "build", broken)
    r = runner.run_scan(target, str(BACKEND), str(target_db))
    assert r.notice_drift is None and len(r.findings) == 7 and r.score == 59


# --- per-field detail (optional block in the contract)
def test_undeclared_detail_on_the_real_target(target, target_db):
    drift = notice_drift.build(target, str(target_db))
    assert [d.field for d in drift.undeclared_detail] == drift.undeclared == ["dob", "aadhaar", "parent_pan"]
    assert all(d.needs_review and d.review_note == notice_drift.REVIEW_NOTE for d in drift.undeclared_detail)
    assert drift.undeclared_detail[1].where == ["db:students.aadhaar", "api:/api/students"]


def test_frontend_places_are_added_after_db_and_api_and_undeclared_does_not_change(target, target_db):
    drift = notice_drift.build(target, str(target_db), BACKEND.parent)
    assert drift.undeclared == ["dob", "aadhaar", "parent_pan"]
    where = {o.field: o.where for o in drift.observed}
    assert where["aadhaar"][:2] == ["db:students.aadhaar", "api:/api/students"] and where["aadhaar"][2].startswith("frontend:frontend/src/App.jsx:")
    assert [o.field for o in drift.observed] == ["name", "email", "phone", "dob", "aadhaar", "parent_pan"]


def test_undeclared_detail_review_only_for_sensitive_fields(monkeypatch):
    obs = [ObservedField(field=f, where=[f"db:t.{f}"]) for f in ("email", "dob")]
    monkeypatch.setattr(notice_drift, "observed_fields", lambda t, d: obs)
    monkeypatch.setattr(notice_drift.httpx, "get", lambda *a, **k: httpx.Response(
        200, text="<ul><li>Name</li></ul>", request=httpx.Request("GET", "http://x/notice")))
    drift = notice_drift.build("http://x", "x.db")
    assert [(d.field, d.needs_review, bool(d.review_note)) for d in drift.undeclared_detail] == [
        ("email", False, False), ("dob", True, True)]


def test_older_scan_without_detail_still_validates():
    assert NoticeDrift(declared=[], observed=[], undeclared=[]).undeclared_detail is None
