import json
import sqlite3

import httpx

from dpdp_lens.scanners import erasure_scan


def count(db, table):
    con = sqlite3.connect(db)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


def test_erasure_scan_finds_v7_and_cleans_up(fresh_target):
    url, db = fresh_target
    before = (count(db, "students"), count(db, "students_backup"))
    findings = erasure_scan.scan(url, str(db))
    assert [f.check for f in findings] == ["erasure_incomplete"]
    f = findings[0]
    assert f.severity == "high" and f.layer == "db"
    assert f.evidence.location.table == "students, students_backup"
    assert "erasure-probe" not in json.dumps(f.model_dump())  # no raw marker values
    assert (count(db, "students"), count(db, "students_backup")) == before  # probe rows removed


def test_erasure_scan_repeats_with_same_result(fresh_target):
    url, db = fresh_target
    a, b = erasure_scan.scan(url, str(db)), erasure_scan.scan(url, str(db))
    assert a == b and len(a) == 1


def stub_target(db, hard_delete):
    """Tiny fake of signup, login and delete on a temp DB. It also writes the email to an audit log."""
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE students (id INTEGER PRIMARY KEY, email TEXT, aadhaar TEXT, is_deleted INTEGER DEFAULT 0)")
    con.execute("CREATE TABLE audit_log (msg TEXT)")
    con.commit()
    con.close()

    def handler(req: httpx.Request) -> httpx.Response:
        con = sqlite3.connect(db)
        try:
            if req.url.path == "/api/signup":
                b = json.loads(req.content)
                cur = con.execute("INSERT INTO students (email, aadhaar) VALUES (?, ?)", (b["email"], b["aadhaar"]))
                con.execute("INSERT INTO audit_log VALUES (?)", (f"signup {b['email']}",))
                con.commit()
                return httpx.Response(201, json={"id": cur.lastrowid})
            if req.url.path == "/api/login":
                return httpx.Response(200, json={"access_token": "t"})
            sid = int(req.url.path.rsplit("/", 1)[1])
            con.execute("DELETE FROM students WHERE id=?" if hard_delete else "UPDATE students SET is_deleted=1 WHERE id=?", (sid,))
            con.commit()
            return httpx.Response(200, json={"success": True})
        finally:
            con.close()

    return httpx.MockTransport(handler)


def test_hard_delete_is_clean_and_audit_log_is_ignored(tmp_path):
    db = tmp_path / "stub.db"
    assert erasure_scan.scan("http://stub", str(db), transport=stub_target(db, hard_delete=True)) == []
    assert count(db, "audit_log") == 1  # logs may be kept (Rule 8(3)); cleanup does not touch them


def test_soft_delete_is_flagged(tmp_path):
    db = tmp_path / "stub.db"
    findings = erasure_scan.scan("http://stub", str(db), transport=stub_target(db, hard_delete=False))
    assert [f.evidence.location.table for f in findings] == ["students"]
    assert count(db, "students") == 0  # cleaned up
