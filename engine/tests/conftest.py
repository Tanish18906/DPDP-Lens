import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from dpdp_lens import config, runner

BACKEND = Path(__file__).resolve().parents[2] / "target-app" / "backend"
FRONTEND = BACKEND.parent / "frontend"


def seed_copy(tmp: Path):
    """Temp copy of the backend plus a fresh seeded temp DB (demo.db stays clean). Returns (backend, db, env)."""
    backend = tmp / "backend"
    shutil.copytree(BACKEND, backend, ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.log"))
    db = tmp / "test.db"
    env = {**os.environ, "TUTORNEST_DB": str(db)}
    subprocess.run([sys.executable, "seed.py"], cwd=backend, env=env, check=True, capture_output=True)
    return backend, db, env


@contextmanager
def run_target(tmp: Path):
    """TutorNest on a free port with its own seeded temp DB. Yields (url, db_path)."""
    backend, db, env = seed_copy(tmp)
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
        yield url, db
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)


@pytest.fixture(autouse=True)
def no_frontend(monkeypatch):
    """A frontend left running on :5173 must not change test results. Tests that need one pass its URL."""
    monkeypatch.setattr(config, "FRONTEND_URL", None)


REAL_LATE_SCANNERS = list(runner.LATE_SCANNERS)


@pytest.fixture(autouse=True)
def no_late_scanners(monkeypatch):
    """The config scan reads the real target-app files, so it would change every full scan count. Tests that want it
    use the with_late_scanners fixture."""
    monkeypatch.setattr(runner, "LATE_SCANNERS", [])


@pytest.fixture
def with_late_scanners(monkeypatch):
    monkeypatch.setattr(runner, "LATE_SCANNERS", REAL_LATE_SCANNERS)


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
def target_server(tmp_path_factory):
    """Shared target for read-only tests. The erasure probe cleans up after itself, so sharing is safe."""
    with run_target(tmp_path_factory.mktemp("tutornest")) as server:
        yield server


@pytest.fixture
def target(target_server):
    return target_server[0]


@pytest.fixture
def target_db(target_server):
    """The DB file the shared target is using."""
    return target_server[1]


@pytest.fixture
def fresh_target(tmp_path):
    """Own target per test, for tests that change its data. Yields (url, db_path)."""
    with run_target(tmp_path) as server:
        yield server
