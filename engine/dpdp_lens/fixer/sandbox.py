"""Sandbox copy of the target app: temp copy, own DB, free port, process group killed on exit.
The original app folder and DB are never written (AGENTS.md section 2).

    with Sandbox(repo, db) as sb:
        ...patch files under sb.repo...
        url = sb.start()
"""
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

IGNORE = shutil.ignore_patterns(".git", "node_modules", ".venv", "__pycache__", "*.db", "*.log")
START_TIMEOUT = 15  # seconds to wait for /openapi.json


class Sandbox:
    def __init__(self, repo_path, db_path, app: str = "app.main:app", start_timeout: float = START_TIMEOUT):
        self.src_repo, self.src_db = Path(repo_path), Path(db_path)
        self.app, self.start_timeout = app, start_timeout
        self.proc = None
        self.url = ""

    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix="dpdp-lens-"))
        self.repo, self.db, self.log = self.root / "repo", self.root / "sandbox.db", self.root / "server.log"
        try:
            shutil.copytree(self.src_repo, self.repo, ignore=IGNORE)
            shutil.copy(self.src_db, self.db)
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc):
        self.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    def _log_tail(self, lines: int = 15) -> str:
        try:
            return "\n".join(self.log.read_text(errors="replace").splitlines()[-lines:])
        except OSError:
            return ""

    def start(self) -> str:
        """Start the copy on a free port and wait until it answers. Returns its base URL."""
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = {**os.environ, "TUTORNEST_DB": str(self.db)}
        with open(self.log, "wb") as out:
            self.proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", self.app, "--host", "127.0.0.1", "--port", str(port)],
                cwd=self.repo, env=env, start_new_session=True, stdout=out, stderr=subprocess.STDOUT)
        self.url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"sandbox app exited with code {self.proc.returncode}:\n{self._log_tail()}")
            try:
                if httpx.get(f"{self.url}/openapi.json", timeout=1).status_code == 200:
                    return self.url
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise RuntimeError(f"sandbox app did not answer /openapi.json in {self.start_timeout}s:\n{self._log_tail()}")

    def stop(self) -> None:
        """Kill the whole process group, children included."""
        if not self.proc:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(self.proc.pid, sig)
            except ProcessLookupError:
                break
            try:
                self.proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                continue
        self.proc.wait()
