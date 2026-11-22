import hashlib
import json
import sqlite3

from stdnum import verhoeff

from dpdp_lens.scanners import db_scan


def test_db_scan_finds_v4(fresh_db):
    findings = db_scan.scan(str(fresh_db))
    assert [f.check for f in findings] == ["db_plaintext_pii"]
    f = findings[0]
    assert f.evidence.location.table == "students"
    assert f.evidence.location.column == "aadhaar, parent_pan"
    assert f.severity == "high" and f.layer == "db"
    assert "Also seen: email, phone, dob" in f.evidence.summary  # evidence list only, not separate findings
    assert "password_hash" not in f.evidence.location.column  # hash column not flagged


def test_db_scan_read_only_and_masked(fresh_db, raw_pii):
    before = hashlib.sha256(fresh_db.read_bytes()).hexdigest()
    dumped = json.dumps([f.model_dump() for f in db_scan.scan(str(fresh_db))])
    assert hashlib.sha256(fresh_db.read_bytes()).hexdigest() == before
    assert "XXXX XXXX" in dumped
    for raw in raw_pii:
        assert raw not in dumped


def test_db_scan_ignores_hashes_order_ids_phone_and_email(tmp_path):
    db = tmp_path / "x.db"
    order_id = "23412341234" + verhoeff.calc_check_digit("23412341234")  # Verhoeff-valid, but not an Aadhaar
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE orders (password_hash TEXT, order_id TEXT, phone TEXT, email TEXT)")
    con.execute("INSERT INTO orders VALUES (?, ?, ?, ?)",
                (hashlib.sha256(b"x").hexdigest(), order_id, "9876543210", "a@example.test"))
    con.commit()
    con.close()
    assert db_scan.scan(str(db)) == []
