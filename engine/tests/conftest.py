import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[2] / "target-app" / "backend"


def seed_copy(tmp: Path):
    """Temp copy of the backend plus a fresh seeded temp DB (demo.db stays clean). Returns (backend, db, env)."""
    backend = tmp / "backend"
    shutil.copytree(BACKEND, backend, ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.log"))
    db = tmp / "test.db"
    env = {**os.environ, "TUTORNEST_DB": str(db)}
    subprocess.run([sys.executable, "seed.py"], cwd=backend, env=env, check=True, capture_output=True)
    return backend, db, env


@pytest.fixture
def fresh_db(tmp_path):
    return seed_copy(tmp_path)[1]


@pytest.fixture
def raw_pii(fresh_db):
    """Raw Aadhaar, PAN, phone and email from the seeded DB. Tests use them to prove findings never hold raw data."""
    con = sqlite3.connect(fresh_db)
    rows = con.execute("SELECT aadhaar, parent_pan, phone, email FROM students").fetchall()
    con.close()
    return [v for row in rows for v in row if v]


@pytest.fixture(scope="session")
def target(tmp_path_factory):
    """TutorNest on a free port, on its own seeded temp DB."""
    backend, _, env = seed_copy(tmp_path_factory.mktemp("tutornest"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=backend, env=env, start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            pytest.fail("target did not start")
        yield url
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
