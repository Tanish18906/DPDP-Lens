"""Block 01b: store, audit chain, ingest transitions, health, outbox. No network, no running app."""
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from stdnum.verhoeff import calc_check_digit

from dpdp_lens import audit, ingest
from dpdp_lens.ingest import StatusError, health, ingest_scan, set_status
from dpdp_lens.models import Coverage, ScanError, ScanResult
from dpdp_lens.store import Store
from test_contract import load_sample

LIVE_CHECK, STATIC_CHECK = "api_pii_exposure", "log_pii"
SAMPLE = {f.check: f for f in load_sample().findings}


@pytest.fixture
def store():
    s = Store(":memory:")
    s._conn().execute("INSERT INTO repos(full_name, created_at) VALUES ('acme/app', '2026-11-23T00:00:00+00:00')")
    return s


def finding(check=STATIC_CHECK, fp="aaaaaaaaaaaaaaaa", severity=None):
    f = SAMPLE.get(check) or SAMPLE[STATIC_CHECK]
    return f.model_copy(update={"check": check, "fingerprint": fp, "severity": severity or f.severity})


def scan(sid, findings=(), run=(STATIC_CHECK,), mode="static", errors=()):
    return ScanResult(scan_id=sid, target="", scanned_at="2026-11-23T00:00:00+00:00", score=100, counts={}, findings=list(findings),
                      scan_errors=list(errors), complete=not errors, repo="acme/app", commit="c" * 40,
                      coverage=Coverage(mode=mode, checks_run=list(run)))


def status_of(store, hid):
    return store.one("SELECT status FROM findings WHERE human_id=?", (hid,))["status"]


def put(store, hid, status):
    store.run("UPDATE findings SET status=? WHERE human_id=?", (status, hid))


# ---- store

def test_schema_is_versioned_and_wal_on_a_file(tmp_path):
    s = Store(tmp_path / "x.db")
    assert s.one("PRAGMA user_version")[0] == 2 and s.one("PRAGMA journal_mode")[0] == "wal"
    assert (tmp_path / "x.db").stat().st_mode & 0o777 == 0o600


def test_a_database_from_a_newer_engine_is_refused(tmp_path):
    db = sqlite3.connect(tmp_path / "x.db")
    db.execute("PRAGMA user_version=99")
    db.close()
    with pytest.raises(RuntimeError, match="newer engine"):
        Store(tmp_path / "x.db").one("SELECT 1")


def test_importing_a_store_creates_no_file(tmp_path):
    Store(tmp_path / "later.db")
    assert not (tmp_path / "later.db").exists()


def test_transaction_rolls_back_on_error(store):
    with pytest.raises(RuntimeError), store.tx():
        store.run("INSERT INTO outbox(kind, human_id, created_at) VALUES ('x','y','z')")
        raise RuntimeError
    assert store.one("SELECT COUNT(*) FROM outbox")[0] == 0


# ---- transitions (master section 7, every row)

def test_new_fingerprint_is_created_open_with_an_event(store):
    d = ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "tester")
    assert d.new == ["DPDP-001"] and status_of(store, "DPDP-001") == "open"
    assert [e["type"] for e in store.all("SELECT type FROM events WHERE human_id='DPDP-001'")] == ["finding_created"]


def test_seen_again_stays_open_and_counts_as_persistent(store):
    ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    d = ingest_scan(store, 1, scan("S-002", [finding()]), "manual", "t")
    assert (d.new, d.persistent, d.suppressed) == ([], 1, 0)
    assert store.one("SELECT last_seen_scan, first_seen_scan FROM findings")["last_seen_scan"] == "S-002"


@pytest.mark.parametrize("before", ["open", "in_progress"])
def test_not_seen_and_check_covered_is_resolved(store, before):
    ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    put(store, "DPDP-001", before)
    d = ingest_scan(store, 1, scan("S-002", []), "manual", "t")
    assert d.resolved == ["DPDP-001"] and status_of(store, "DPDP-001") == "fixed"
    assert store.one("SELECT type FROM events WHERE human_id='DPDP-001' ORDER BY id DESC")["type"] == "finding_resolved"


def test_seen_after_fixed_is_reopened(store):
    ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    ingest_scan(store, 1, scan("S-002", []), "manual", "t")
    d = ingest_scan(store, 1, scan("S-003", [finding()]), "manual", "t")
    assert d.reopened == ["DPDP-001"] and status_of(store, "DPDP-001") == "open"
    assert d.new == []  # same fingerprint, same human id


@pytest.mark.parametrize("state", ["false_positive", "wont_fix"])
def test_suppressed_findings_are_never_changed_by_the_system(store, state):
    ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    put(store, "DPDP-001", state)
    seen = ingest_scan(store, 1, scan("S-002", [finding()]), "manual", "t")
    assert seen.suppressed == 1 and status_of(store, "DPDP-001") == state
    gone = ingest_scan(store, 1, scan("S-003", []), "manual", "t")  # covered check, not seen: still not resolved
    assert gone.resolved == [] and status_of(store, "DPDP-001") == state


def test_not_seen_but_check_not_covered_changes_nothing(store):
    ingest_scan(store, 1, scan("S-001", [finding(LIVE_CHECK, "b" * 16)], run=(LIVE_CHECK,), mode="full"), "manual", "t")
    d = ingest_scan(store, 1, scan("S-002", [], run=(STATIC_CHECK,)), "manual", "t")  # a static scan cannot see a live probe
    assert d.resolved == [] and status_of(store, "DPDP-001") == "open"


def test_incomplete_scan_never_resolves_anything(store):
    ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    bad = scan("S-002", [], run=(), errors=[ScanError(scanner="log_scan", kind="failed", message="boom")])
    d = ingest_scan(store, 1, bad, "manual", "t")
    assert d.resolved == [] and d.complete is False and status_of(store, "DPDP-001") == "open"
    assert store.one("SELECT status FROM scans WHERE scan_id='S-002'")["status"] == "incomplete"


def test_a_scan_without_coverage_resolves_nothing(store):
    ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    d = ingest_scan(store, 1, scan("S-002", []).model_copy(update={"coverage": None}), "manual", "t")
    assert d.resolved == []


def test_human_ids_are_global_and_never_reused(store):
    store.run("INSERT INTO repos(full_name, created_at) VALUES ('acme/two', 'x')")
    ingest_scan(store, 1, scan("S-001", [finding(fp="1" * 16)]), "manual", "t")
    ingest_scan(store, 2, scan("S-002", [finding(fp="2" * 16)]), "manual", "t")
    ingest_scan(store, 1, scan("S-003", []), "manual", "t")  # DPDP-001 resolved
    d = ingest_scan(store, 1, scan("S-004", [finding(fp="3" * 16)]), "manual", "t")
    assert d.new == ["DPDP-003"]


def test_same_fingerprint_in_two_repos_gets_two_ids(store):
    store.run("INSERT INTO repos(full_name, created_at) VALUES ('acme/two', 'x')")
    a = ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    b = ingest_scan(store, 2, scan("S-002", [finding()]), "manual", "t")
    assert a.new == ["DPDP-001"] and b.new == ["DPDP-002"]


# ---- baseline

def test_first_complete_scan_sets_the_baseline_and_nothing_replaces_it(store):
    ingest_scan(store, 1, scan("S-001", [], errors=[ScanError(scanner="x", kind="failed", message="m")]), "manual", "t")
    assert store.one("SELECT baseline_scan_id FROM repos")[0] is None  # an incomplete scan is never a baseline
    ingest_scan(store, 1, scan("S-002", [finding()]), "manual", "t")
    ingest_scan(store, 1, scan("S-003", [finding(), finding(fp="c" * 16)]), "manual", "t")
    assert store.one("SELECT baseline_scan_id FROM repos")[0] == "S-002"


# ---- manual status

def test_manual_transitions_write_event_and_outbox_together(store):
    ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    set_status(store, "DPDP-001", "in_progress", "", "U1")
    set_status(store, "DPDP-001", "false_positive", "test data only", "U2")
    row = store.one("SELECT status, status_reason, status_by FROM findings")
    assert (row["status"], row["status_reason"], row["status_by"]) == ("false_positive", "test data only", "U2")
    assert [r["kind"] for r in store.all("SELECT kind FROM outbox")] == ["status_changed"] * 2
    ev = store.all("SELECT actor, result, meta_json FROM events WHERE type='status_changed' ORDER BY id")
    assert [e["actor"] for e in ev] == ["U1", "U2"] and json.loads(ev[1]["meta_json"])["from"] == "in_progress"


def test_a_failed_outbox_write_rolls_the_status_back(store, monkeypatch):
    ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    monkeypatch.setattr(ingest, "_outbox", lambda *a: (_ for _ in ()).throw(RuntimeError("disk")))
    with pytest.raises(RuntimeError):
        set_status(store, "DPDP-001", "in_progress", "", "U1")
    assert status_of(store, "DPDP-001") == "open"
    assert store.one("SELECT COUNT(*) FROM events WHERE type='status_changed'")[0] == 0


@pytest.mark.parametrize("args, code, text", [
    (("fixed", "because", "u"), 422, "Fixed is set by a scan or a verified fix"),
    (("false_positive", "", "u"), 422, "needs a reason"),
    (("wont_fix", "   ", "u"), 422, "needs a reason"),
    (("wont_fix", "x" * 301, "u"), 422, "at most 300"),
    (("wont_fix", "ok", "u"), None, ""),
    (("bogus", "", "u"), 422, "status must be"),
])
def test_manual_rejections(store, args, code, text):
    ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    if code is None:
        set_status(store, "DPDP-001", *args)
        return
    with pytest.raises(StatusError, match=text) as e:
        set_status(store, "DPDP-001", *args)
    assert e.value.status == code and status_of(store, "DPDP-001") == "open"


def test_a_reason_with_personal_data_is_rejected(store):
    ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    with pytest.raises(StatusError, match="personal data"):
        set_status(store, "DPDP-001", "wont_fix", "owner is a.b@example.test", "u")


def test_unknown_finding_is_404(store):
    with pytest.raises(StatusError) as e:
        set_status(store, "DPDP-999", "open", "", "u")
    assert e.value.status == 404


# ---- health

def sev(store, hid, severity):
    store.run("UPDATE findings SET severity=? WHERE human_id=?", (severity, hid))


def test_health_unknown_without_a_scan_and_after_an_incomplete_one(store):
    assert health(store, 1)["status"] == "unknown"
    ingest_scan(store, 1, scan("S-001", []), "manual", "t")
    assert health(store, 1)["status"] == "healthy"
    ingest_scan(store, 1, scan("S-002", [], run=(), errors=[ScanError(scanner="x", kind="timeout", message="m")]), "manual", "t")
    h = health(store, 1)
    assert h["status"] == "unknown" and "S-002 is incomplete" in h["reasons"][0] and h["last_scan_status"] == "incomplete"


def test_failed_scan_makes_health_unknown(store):
    ingest_scan(store, 1, scan("S-001", []), "manual", "t")
    ingest.record_scan_failed(store, 1, "S-002", "schedule", "monitor", "clone failed")
    assert health(store, 1)["status"] == "unknown"
    assert store.one("SELECT type FROM events ORDER BY id DESC")["type"] == "scan_failed"


def test_at_risk_needs_a_blocking_finding_that_is_not_suppressed(store):
    ingest_scan(store, 1, scan("S-001", [finding(severity="critical")]), "manual", "t")
    assert health(store, 1)["status"] == "at_risk"
    set_status(store, "DPDP-001", "wont_fix", "accepted risk", "u")
    ingest_scan(store, 1, scan("S-002", [finding(severity="critical")]), "manual", "t")
    assert health(store, 1)["status"] == "healthy"  # suppressed, never counted


def test_a_low_finding_does_not_make_the_repo_at_risk(store):
    ingest_scan(store, 1, scan("S-001", [finding(severity="low")]), "manual", "t")
    assert health(store, 1)["status"] == "healthy"


def test_changed_means_added_or_resolved_against_the_baseline(store):
    ingest_scan(store, 1, scan("S-001", [finding(severity="low")]), "manual", "t")
    ingest_scan(store, 1, scan("S-002", [finding(severity="low"), finding(fp="d" * 16, severity="low")]), "manual", "t")
    h = health(store, 1)
    assert h["status"] == "changed" and "1 added" in h["reasons"][0]


def test_stale_scan_makes_health_unknown_when_a_watch_is_set(store):
    ingest_scan(store, 1, scan("S-001", []), "manual", "t")
    store.run("UPDATE repos SET watch_minutes=10")
    assert health(store, 1)["status"] == "healthy"
    later = datetime.now(timezone.utc) + timedelta(minutes=21)
    h = health(store, 1, now=later)
    assert h["status"] == "unknown" and h["reasons"][0].startswith("stale")


def test_static_scan_health_says_how_many_checks_ran(store):
    ingest_scan(store, 1, scan("S-001", [], run=("a", "b", "c")), "manual", "t")
    assert "static checks only (3 of 19)" in health(store, 1)["reasons"]


# ---- audit

def test_chain_verifies_and_a_changed_byte_breaks_it(store):
    ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    set_status(store, "DPDP-001", "in_progress", "", "U1")
    ok = audit.verify_chain(store)
    assert ok["ok"] and ok["checked"] == store.one("SELECT COUNT(*) FROM events")[0] and ok["first_bad"] is None
    target = store.one("SELECT id, result FROM events WHERE type='status_changed'")
    store.run("UPDATE events SET result=? WHERE id=?", (target["result"] + "x", target["id"]))
    assert audit.verify_chain(store) == {"ok": False, "checked": target["id"] - 1, "first_bad": target["id"]}


def test_deleting_an_event_is_detected(store):
    for i in range(4):
        audit.record(store, "policy_changed", "u", result=str(i))
    store.run("DELETE FROM events WHERE id=2")
    assert audit.verify_chain(store)["first_bad"] == 3


def test_events_chain_from_a_genesis_hash(store):
    audit.record(store, "policy_changed", "u")
    audit.record(store, "policy_changed", "u")
    a, b = store.all("SELECT prev_hash, hash FROM events ORDER BY id")
    assert a["prev_hash"] == audit.GENESIS and b["prev_hash"] == a["hash"]


def test_unknown_event_type_is_refused(store):
    with pytest.raises(ValueError):
        audit.record(store, "made_up", "u")


def test_audit_masks_personal_data_and_tokens(store):
    partial = "29384756102"
    aadhaar = partial + calc_check_digit(partial)
    audit.record(store, "status_changed", "u", result="ok", meta={"note": f"aadhaar {aadhaar} and mail a.b@example.test",
                                                                  "nested": ["token xoxb-123-abc-def and ghp_" + "x" * 20]})
    raw = store.one("SELECT actor, result, meta_json FROM events")
    blob = raw["actor"] + raw["result"] + raw["meta_json"]
    assert aadhaar not in blob and "a.b@example.test" not in blob and "xoxb-123" not in blob and "ghp_x" not in blob
    assert "XXXX XXXX" in blob.replace(aadhaar[-4:], aadhaar[-4:]) and "[redacted]" in blob and audit.verify_chain(store)["ok"]


# ---- outbox and restart

def test_system_transitions_write_outbox_rows(store):
    ingest_scan(store, 1, scan("S-001", [finding()]), "manual", "t")
    ingest_scan(store, 1, scan("S-002", []), "manual", "t")  # resolved
    ingest_scan(store, 1, scan("S-003", [finding()]), "manual", "t")  # reopened
    assert [(r["kind"], r["human_id"]) for r in store.all("SELECT * FROM outbox ORDER BY id")] == [("status_changed", "DPDP-001")] * 2


def test_reopening_the_same_file_keeps_ids_events_and_the_chain(tmp_path):
    path = tmp_path / "dpdp.db"
    a = Store(path)
    a.run("INSERT INTO repos(full_name, created_at) VALUES ('acme/app', 'x')")
    ingest_scan(a, 1, scan("S-001", [finding()]), "manual", "t")
    a.close()
    b = Store(path)
    d = ingest_scan(b, 1, scan("S-002", [finding(), finding(fp="e" * 16)]), "manual", "t")
    assert d.new == ["DPDP-002"] and d.persistent == 1
    assert audit.verify_chain(b)["ok"] and b.one("SELECT COUNT(*) FROM events WHERE type='finding_created'")[0] == 2


# ---- no raw personal data in the database file

def test_no_raw_personal_data_in_the_sqlite_file_after_a_full_tutornest_ingest(target, target_db, tmp_path, with_late_scanners):
    from conftest import BACKEND
    from dpdp_lens.runner import run_scan
    db = sqlite3.connect(target_db)
    raw = [v for row in db.execute("SELECT aadhaar, parent_pan, phone, email, name FROM students").fetchall() for v in row if v]
    db.close()
    s = Store(tmp_path / "dpdp.db")
    s.run("INSERT INTO repos(full_name, created_at) VALUES ('acme/tutornest', 'x')")
    result = run_scan(target, str(BACKEND), str(target_db))
    assert len(result.findings) >= 15
    ingest_scan(s, 1, result, "manual", "t")
    set_status(s, "DPDP-001", "in_progress", "", "U1")
    s.close()
    data = b"".join(p.read_bytes() for p in tmp_path.glob("dpdp.db*"))
    assert raw and not [v for v in raw if v.encode() in data]
    text = re.sub(r"XXXX XXXX \d{4}|XXXXX\d{4}[A-Z]", "", data.decode("latin-1"))  # the masked forms are allowed
    assert not re.search(r"\b[2-9]\d{3} ?\d{4} ?\d{4}\b", text), "a 12 digit Aadhaar"
    assert not re.search(r"\b[A-Z]{5}\d{4}[A-Z]\b", text), "a PAN"
    assert not re.search(r"\b[6-9]\d{9}\b", text), "a 10 digit phone"
