"""Append-only audit events with a hash chain. TAMPER-EVIDENT, not tamper-proof: every event holds the hash of the one
before it, so an edited or deleted row breaks `verify_chain`. Anyone who can write the database file can still rewrite the
whole chain, or cut events off the end, and the check will pass. Keep a copy of the last hash elsewhere if that matters.

No raw personal data and no token ever goes into an event: every string is redacted and masked before it is stored."""
import hashlib
import json
import re
from datetime import datetime, timezone

from .recognizers import find_pii
from .store import Store

TYPES = {"repo_connected", "scan_started", "scan_completed", "scan_incomplete", "scan_failed", "finding_created",
         "finding_resolved", "finding_reopened", "status_changed", "baseline_set", "watch_changed", "fix_started",
         "fix_verified", "fix_failed", "policy_changed", "github_installed", "report_link_created"}
GENESIS = "0" * 64
_TOKEN = re.compile(r"xox[abeprs]-[A-Za-z0-9-]+|xapp-[A-Za-z0-9-]+|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}"
                    r"|eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}")  # last: a JWT (the GitHub App's)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redact(text: str) -> str:
    """Replace anything that looks like a Slack or GitHub token (ghp_, gho_, ghu_, ghs_ installation tokens, ghr_) or a JWT."""
    return _TOKEN.sub("[redacted]", text)


def clean(value):
    """Redact tokens and mask personal data in a string, a list or a dict (recursively). Other values pass through."""
    if isinstance(value, str):
        value = redact(value)
        end = len(value) + 1
        for _, a, b, masked in reversed(find_pii(value)):
            if b <= end:  # an overlapping match would garble the text, the outer one is already masked
                value, end = value[:a] + masked + value[b:], a
        return value
    if isinstance(value, dict):
        return {clean(str(k)): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def _canonical(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def _hash(prev_hash: str, event: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(event)).encode()).hexdigest()


def record(store: Store, type: str, actor: str, repo_id=None, scan_id=None, human_id=None, policy_version="", result="",
           meta=None, ts=None) -> int:
    """Append one event and return its id. Joins the caller's transaction when there is one."""
    if type not in TYPES:
        raise ValueError(f"unknown audit event type {type!r}")
    event = {"ts": ts or now(), "type": type, "actor": clean(actor), "repo_id": repo_id, "scan_id": scan_id,
             "human_id": human_id, "policy_version": policy_version, "result": clean(result), "meta": clean(meta or {})}
    with store.tx():
        last = store.one("SELECT hash FROM events ORDER BY id DESC LIMIT 1")
        prev = last["hash"] if last else GENESIS
        cur = store.run(
            "INSERT INTO events(ts, type, actor, repo_id, scan_id, human_id, policy_version, result, meta_json, prev_hash, hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (event["ts"], type, event["actor"], repo_id, scan_id, human_id, policy_version, event["result"],
             _canonical(event["meta"]), prev, _hash(prev, event)))
        return cur.lastrowid


def verify_chain(store: Store) -> dict:
    """{ok, checked, first_bad}: first_bad is the id of the first event whose hash or link does not match."""
    prev, checked = GENESIS, 0
    for row in store.all("SELECT * FROM events ORDER BY id"):
        event = {"ts": row["ts"], "type": row["type"], "actor": row["actor"], "repo_id": row["repo_id"], "scan_id": row["scan_id"],
                 "human_id": row["human_id"], "policy_version": row["policy_version"], "result": row["result"],
                 "meta": json.loads(row["meta_json"])}
        if row["prev_hash"] != prev or row["hash"] != _hash(prev, event):
            return {"ok": False, "checked": checked, "first_bad": row["id"]}
        prev, checked = row["hash"], checked + 1
    return {"ok": True, "checked": checked, "first_bad": None}
