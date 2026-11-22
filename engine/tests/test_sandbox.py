import hashlib
import os
import sqlite3

import httpx
import pytest

from conftest import BACKEND
from dpdp_lens.fixer.sandbox import Sandbox


def tree_hash(root):
    """Hash of source files only (no caches, logs or DBs)."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".log", ".db"):
            h.update(str(p.relative_to(root)).encode() + p.read_bytes())
    return h.hexdigest()


def gone(pid):
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_copy_ignores_junk_and_copies_db(tmp_path):
    repo = tmp_path / "fake"
    for rel in ("keep.txt", "app/main.py", ".git/HEAD", "node_modules/x.js", ".venv/y", "__pycache__/z.pyc",
                "demo.db", "a.log"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x")
    db = tmp_path / "src.db"
    db.write_bytes(b"db-bytes")
    with Sandbox(repo, db) as sb:
        root = sb.root
        assert sorted(p.relative_to(sb.repo).as_posix() for p in sb.repo.rglob("*") if p.is_file()) == [
            "app/main.py", "keep.txt"]
        assert sb.db.read_bytes() == b"db-bytes" and sb.db != db
    assert not root.exists()


def test_real_sandbox_is_isolated_and_leaves_nothing_behind(fresh_db):
    db_before, tree_before = fresh_db.read_bytes(), tree_hash(BACKEND)
    with Sandbox(BACKEND, fresh_db) as sb:
        url = sb.start()
        assert httpx.get(f"{url}/health").json()["status"] == "ok"
        r = httpx.post(f"{url}/api/signup", json={
            "name": "Sandbox Probe", "email": "sandbox@example.test", "phone": "9000000002",
            "dob": "2000-01-01", "age": 25, "aadhaar": "234123412346", "password": "ProbePass123!"})
        assert r.status_code == 201
        con = sqlite3.connect(sb.db)
        assert con.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 16  # the write went to the copy
        con.close()
        pid, root = sb.pid, sb.root
    assert gone(pid)
    with pytest.raises(httpx.ConnectError):
        httpx.get(f"{url}/health", timeout=1)
    assert not root.exists()
    assert fresh_db.read_bytes() == db_before and tree_hash(BACKEND) == tree_before


def test_failed_start_reports_log_and_cleans_up(tmp_path):
    repo = tmp_path / "broken"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "__init__.py").write_text("")
    (repo / "app" / "main.py").write_text("def broken(:\n")
    db = tmp_path / "src.db"
    db.write_bytes(b"x")
    with Sandbox(repo, db, start_timeout=5) as sb:
        root = sb.root
        with pytest.raises(RuntimeError, match="exited with code"):
            sb.start()
        assert "SyntaxError" in sb._log_tail()
        pid = sb.pid
    assert gone(pid) and not root.exists()
