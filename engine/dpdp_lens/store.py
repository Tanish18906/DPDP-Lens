"""SQLite store for connected repos, scans, findings, audit events and the outbox (docs/dpdp-evolve master section 8).
No ORM, parameterised queries only. One connection guarded by a lock, so any thread may use a Store. The file is opened
on first use, so importing the API creates nothing. ":memory:" is for tests.

Column names differ from the brief in two places because they are SQL keywords: scans.trigger_kind, scans.commit_sha.
scans also has coverage_json (the scan's Coverage), which health needs."""
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 3
# 1 to 2 (block 05): repos.last_health (the status an alert was last decided on), outbox.repo_id and outbox.scan_id (scan_delta and health_changed rows)
MIGRATIONS = {1: "ALTER TABLE repos ADD COLUMN last_health TEXT; ALTER TABLE outbox ADD COLUMN repo_id INTEGER; "
                 "ALTER TABLE outbox ADD COLUMN scan_id TEXT NOT NULL DEFAULT '';",
              # 2 to 3 (block 08): GitHub App installations, and which installation a repo was connected through (NULL: the env allowlist and GITHUB_TOKEN)
              2: "CREATE TABLE installations(installation_id INTEGER PRIMARY KEY, account_login TEXT NOT NULL, account_type TEXT NOT NULL, "
                 "created_at TEXT NOT NULL); ALTER TABLE repos ADD COLUMN installation_id INTEGER;"}

SCHEMA = """
CREATE TABLE repos(
  id INTEGER PRIMARY KEY, full_name TEXT NOT NULL UNIQUE, branch TEXT NOT NULL DEFAULT '', slack_channel TEXT NOT NULL DEFAULT '',
  watch_minutes INTEGER, next_run_at TEXT, baseline_scan_id TEXT, created_at TEXT NOT NULL, last_health TEXT, installation_id INTEGER);
CREATE TABLE installations(installation_id INTEGER PRIMARY KEY, account_login TEXT NOT NULL, account_type TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE scans(
  scan_id TEXT PRIMARY KEY, repo_id INTEGER NOT NULL REFERENCES repos(id), trigger_kind TEXT NOT NULL, commit_sha TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK (status IN ('complete','incomplete','failed')), mode TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL, finished_at TEXT NOT NULL, policy_version TEXT NOT NULL DEFAULT '', scanner_version TEXT NOT NULL DEFAULT '',
  errors_json TEXT NOT NULL DEFAULT '[]', coverage_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE findings(
  human_id TEXT PRIMARY KEY, repo_id INTEGER NOT NULL REFERENCES repos(id), fingerprint TEXT NOT NULL, check_id TEXT NOT NULL,
  severity TEXT NOT NULL, title TEXT NOT NULL, layer TEXT NOT NULL, proof TEXT NOT NULL DEFAULT 'static',
  status TEXT NOT NULL CHECK (status IN ('open','in_progress','fixed','false_positive','wont_fix')),
  status_reason TEXT NOT NULL DEFAULT '', status_by TEXT NOT NULL DEFAULT '', status_at TEXT NOT NULL,
  first_seen_scan TEXT NOT NULL, last_seen_scan TEXT NOT NULL, last_finding_json TEXT NOT NULL,
  slack_channel TEXT, slack_ts TEXT, UNIQUE(repo_id, fingerprint));
CREATE INDEX findings_repo_status ON findings(repo_id, status);
CREATE TABLE scan_findings(scan_id TEXT NOT NULL REFERENCES scans(scan_id), human_id TEXT NOT NULL REFERENCES findings(human_id),
  PRIMARY KEY(scan_id, human_id));
CREATE TABLE events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, type TEXT NOT NULL, actor TEXT NOT NULL, repo_id INTEGER, scan_id TEXT,
  human_id TEXT, policy_version TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT '', meta_json TEXT NOT NULL DEFAULT '{}',
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE INDEX events_repo ON events(repo_id);
CREATE INDEX events_human ON events(human_id);
CREATE TABLE outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, human_id TEXT NOT NULL, created_at TEXT NOT NULL,
  repo_id INTEGER, scan_id TEXT NOT NULL DEFAULT '');
"""


class Store:
    def __init__(self, path=":memory:"):
        self.path = str(path)
        self._db = None
        self._lock = threading.RLock()
        self._depth = 0

    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            memory = self.path == ":memory:"
            if not memory:
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)  # we run BEGIN and COMMIT ourselves
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=5000")
            if not memory:
                db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                db.close()
                raise RuntimeError(f"{self.path} was written by a newer engine (schema {version}, this one knows {SCHEMA_VERSION})")
            if 0 < version < SCHEMA_VERSION:  # an older file: apply each step, one transaction per step
                for v in range(version, SCHEMA_VERSION):
                    db.executescript(f"BEGIN;{MIGRATIONS[v]}PRAGMA user_version={v + 1};COMMIT;")
            if version == 0:
                db.executescript(f"BEGIN;{SCHEMA}PRAGMA user_version={SCHEMA_VERSION};COMMIT;")
                if not memory:
                    try:
                        os.chmod(self.path, 0o600)  # best effort: the file holds finding metadata and the audit chain
                    except OSError:
                        pass
            self._db = db
        return self._db

    @contextmanager
    def tx(self):
        """One transaction. Nested use joins the outer one, so a status change and its audit event commit together."""
        with self._lock:
            db = self._conn()
            outer = self._depth == 0
            if outer:
                db.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self
            except BaseException:
                self._depth -= 1
                if outer:
                    db.execute("ROLLBACK")
                raise
            self._depth -= 1
            if outer:
                db.execute("COMMIT")

    def run(self, sql: str, params=()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn().execute(sql, params)

    def all(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn().execute(sql, params).fetchall()

    def one(self, sql: str, params=()):
        with self._lock:
            return self._conn().execute(sql, params).fetchone()

    def close(self):
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None
