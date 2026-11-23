"""Turns scans into finding records with stable human IDs and a triage status (master sections 6, 7 and 10).
Everything here works on the Store and plain models, so tests need no network and no running app."""
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import audit
from .checks import CHECKS
from .models import Finding, ScanResult
from .recognizers import find_pii
from .store import Store

STATUSES = ("open", "in_progress", "fixed", "false_positive", "wont_fix")
MANUAL = ("open", "in_progress", "false_positive", "wont_fix")  # "fixed" is set by a scan or a verified fix only
SUPPRESSED = ("false_positive", "wont_fix")
LIVE = ("open", "in_progress")
# shortcut: until policy.py (block 02) decides, a finding "blocks" when it is critical or high. Replace `blocks` then.
BLOCKING = ("critical", "high")


class StatusError(Exception):
    """A rejected manual transition. `status` is the HTTP status the API answers with."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass
class ScanDelta:
    scan_id: str
    repo: str
    commit: str
    complete: bool
    new: list = field(default_factory=list)
    reopened: list = field(default_factory=list)
    resolved: list = field(default_factory=list)
    persistent: int = 0
    suppressed: int = 0


def _next_human_id(store: Store) -> str:
    n = store.one("SELECT COALESCE(MAX(CAST(SUBSTR(human_id, 6) AS INTEGER)), 0) + 1 AS n FROM findings")["n"]
    return f"DPDP-{n:03d}"  # findings are never deleted, so an ID is never reused


def _outbox(store: Store, kind: str, human_id: str = "", repo_id: int | None = None, scan_id: str = ""):
    """status_changed rows carry a human_id. scan_delta and health_changed rows carry repo_id and scan_id instead."""
    store.run("INSERT INTO outbox(kind, human_id, created_at, repo_id, scan_id) VALUES (?,?,?,?,?)",
              (kind, human_id, audit.now(), repo_id, scan_id))


BAD = ("at_risk", "unknown")


def sync_health(store: Store, repo_id: int, emit: bool, now: datetime | None = None):
    """Remember the repo's health status and, when `emit`, queue a health_changed row if it moved into at_risk or unknown
    (or back out of them). An unchanged status writes nothing, so a repo that stays unknown alerts once. Runs in the caller's
    transaction, so the alert and the state change that caused it commit together. Returns (old, new) or None."""
    with store.tx():
        new = health(store, repo_id, now)["status"]
        old = repo_row(store, repo_id)["last_health"]
        if new == old:
            return None
        store.run("UPDATE repos SET last_health=? WHERE id=?", (new, repo_id))
        if emit and (new in BAD or old in BAD):
            _outbox(store, "health_changed", repo_id=repo_id)
        return old, new


def ingest_scan(store: Store, repo_id: int, scan: ScanResult, trigger: str, actor: str, started_at: str | None = None) -> ScanDelta:
    """Store the scan and apply master section 7 to the repo's findings, in one transaction.
    A finding is only resolved when the scan did not see it AND its check is in coverage.checks_run, so an incomplete
    or static scan never resolves what it could not look at."""
    ts = audit.now()
    with store.tx():
        repo = store.one("SELECT * FROM repos WHERE id=?", (repo_id,))
        if repo is None:
            raise KeyError(f"unknown repo {repo_id}")
        cov = scan.coverage
        status = "complete" if scan.complete else "incomplete"
        store.run(
            'INSERT INTO scans(scan_id, repo_id, trigger_kind, commit_sha, status, mode, started_at, finished_at, policy_version, '
            'scanner_version, errors_json, coverage_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (scan.scan_id, repo_id, trigger, scan.commit, status, cov.mode if cov else "full", started_at or ts, ts,
             scan.policy_version, scan.scanner_version,
             json.dumps([e.model_dump() for e in scan.scan_errors]), cov.model_dump_json() if cov else "{}"))
        delta = ScanDelta(scan.scan_id, repo["full_name"], scan.commit, scan.complete)
        seen = []
        for f in scan.findings:
            blob = f.model_dump_json()
            row = store.one("SELECT human_id, status FROM findings WHERE repo_id=? AND fingerprint=?", (repo_id, f.fingerprint))
            if row is None:
                hid = _next_human_id(store)
                store.run(
                    "INSERT INTO findings(human_id, repo_id, fingerprint, check_id, severity, title, layer, proof, status, status_by, "
                    "status_at, first_seen_scan, last_seen_scan, last_finding_json) VALUES (?,?,?,?,?,?,?,?, 'open', 'system', ?,?,?,?)",
                    (hid, repo_id, f.fingerprint, f.check, f.severity, f.title, f.layer, f.proof, ts, scan.scan_id, scan.scan_id, blob))
                audit.record(store, "finding_created", "system", repo_id, scan.scan_id, hid, scan.policy_version, "open")
                delta.new.append(hid)
            else:
                hid, st = row["human_id"], row["status"]
                store.run("UPDATE findings SET check_id=?, severity=?, title=?, layer=?, proof=?, last_seen_scan=?, last_finding_json=? "
                          "WHERE human_id=?", (f.check, f.severity, f.title, f.layer, f.proof, scan.scan_id, blob, hid))
                if st == "fixed":
                    store.run("UPDATE findings SET status='open', status_reason='', status_by='system', status_at=? WHERE human_id=?", (ts, hid))
                    audit.record(store, "finding_reopened", "system", repo_id, scan.scan_id, hid, scan.policy_version, "open")
                    _outbox(store, "status_changed", hid)
                    delta.reopened.append(hid)
                elif st in LIVE:
                    delta.persistent += 1
                else:
                    delta.suppressed += 1  # false_positive and wont_fix are never changed by the system
            seen.append(hid)
        covered = set(cov.checks_run) if cov else set()
        for row in store.all("SELECT human_id, check_id FROM findings WHERE repo_id=? AND status IN ('open','in_progress')", (repo_id,)):
            if row["human_id"] not in seen and row["check_id"] in covered:
                store.run("UPDATE findings SET status='fixed', status_reason=?, status_by='system', status_at=? WHERE human_id=?",
                          (f"not found in {scan.scan_id}", ts, row["human_id"]))
                audit.record(store, "finding_resolved", "system", repo_id, scan.scan_id, row["human_id"], scan.policy_version, "fixed")
                _outbox(store, "status_changed", row["human_id"])
                delta.resolved.append(row["human_id"])
        for hid in seen:
            store.run("INSERT INTO scan_findings(scan_id, human_id) VALUES (?,?)", (scan.scan_id, hid))
        if scan.branch and not repo["branch"]:
            store.run("UPDATE repos SET branch=? WHERE id=?", (scan.branch, repo_id))
        audit.record(
            store, "scan_completed" if scan.complete else "scan_incomplete", actor, repo_id, scan.scan_id, None, scan.policy_version,
            status, {"trigger": trigger, "mode": cov.mode if cov else "full", "findings": len(scan.findings), "new": len(delta.new),
                     "reopened": len(delta.reopened), "resolved": len(delta.resolved), "persistent": delta.persistent,
                     "suppressed": delta.suppressed, "errors": [{"scanner": e.scanner, "kind": e.kind} for e in scan.scan_errors]})
        if scan.complete and repo["baseline_scan_id"] is None:  # the first complete scan only, a scan never replaces a baseline
            store.run("UPDATE repos SET baseline_scan_id=? WHERE id=?", (scan.scan_id, repo_id))
            audit.record(store, "baseline_set", "system", repo_id, scan.scan_id, None, scan.policy_version, "first complete scan")
        scheduled = trigger == "schedule"  # only the monitor raises alerts, and only for what changed
        blocking_new = [h for h in delta.new + delta.reopened if store.one(
            f"SELECT 1 FROM findings WHERE human_id=? AND status='open' AND severity IN ({','.join('?' * len(BLOCKING))})", (h, *BLOCKING))]
        if scheduled and blocking_new:
            _outbox(store, "scan_delta", repo_id=repo_id, scan_id=scan.scan_id)
        sync_health(store, repo_id, emit=scheduled)
    return delta


def record_scan_failed(store: Store, repo_id: int, scan_id: str, trigger: str, actor: str, message: str, started_at: str | None = None):
    """A scan that produced no result (clone failed, crash). It is stored, so health turns unknown, never silently healthy."""
    ts = audit.now()
    with store.tx():
        store.run('INSERT INTO scans(scan_id, repo_id, trigger_kind, status, started_at, finished_at, errors_json) '
                  "VALUES (?,?,?, 'failed', ?,?,?)",
                  (scan_id, repo_id, trigger, started_at or ts, ts, json.dumps([{"scanner": "scan", "kind": "failed", "message": audit.clean(message)[:300]}])))
        audit.record(store, "scan_failed", actor, repo_id, scan_id, result=message[:300])
        sync_health(store, repo_id, emit=trigger == "schedule")  # a failed scan makes the repo unknown: alert once


# ---- manual transitions

def set_status(store: Store, human_id: str, status: str, reason: str, actor: str) -> None:
    """Master section 7, manual transitions. Raises StatusError(404 or 422)."""
    if status not in STATUSES:
        raise StatusError(422, f"status must be one of {', '.join(STATUSES)}")
    if status == "fixed":
        raise StatusError(422, "Fixed is set by a scan or a verified fix")
    reason = (reason or "").strip()
    if status in SUPPRESSED and not reason:
        raise StatusError(422, f"{status} needs a reason of 1 to 300 characters")
    if len(reason) > 300:
        raise StatusError(422, "the reason is at most 300 characters")
    if find_pii(reason):
        raise StatusError(422, "the reason must not contain personal data")
    with store.tx():
        row = store.one("SELECT repo_id, status FROM findings WHERE human_id=?", (human_id,))
        if row is None:
            raise StatusError(404, f"Unknown finding {human_id}")
        store.run("UPDATE findings SET status=?, status_reason=?, status_by=?, status_at=? WHERE human_id=?",
                  (status, reason, actor, audit.now(), human_id))
        audit.record(store, "status_changed", actor, row["repo_id"], None, human_id, result=status,
                     meta={"from": row["status"], "to": status, "reason": reason})
        _outbox(store, "status_changed", human_id)  # same transaction: the bot never misses a change the audit log has


def mark_fixed(store: Store, human_id: str, actor: str, finding: Finding, meta: dict) -> None:
    """A verified fix sets fixed and keeps the fix result in last_finding_json (the stored scan is never edited)."""
    with store.tx():
        row = store.one("SELECT repo_id, status FROM findings WHERE human_id=?", (human_id,))
        if row is None:
            raise StatusError(404, f"Unknown finding {human_id}")
        store.run("UPDATE findings SET status='fixed', status_reason=?, status_by=?, status_at=?, last_finding_json=? WHERE human_id=?",
                  ("verified fix", actor, audit.now(), finding.model_dump_json(), human_id))
        audit.record(store, "fix_verified", actor, row["repo_id"], None, human_id, result="fixed", meta=meta)
        audit.record(store, "status_changed", actor, row["repo_id"], None, human_id, result="fixed",
                     meta={"from": row["status"], "to": "fixed", "reason": "verified fix"})
        _outbox(store, "status_changed", human_id)


# ---- reads

def repo_row(store: Store, repo_id: int):
    row = store.one("SELECT * FROM repos WHERE id=?", (repo_id,))
    if row is None:
        raise StatusError(404, f"Unknown repo {repo_id}")
    return row


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def health(store: Store, repo_id: int, now: datetime | None = None) -> dict:
    """Master section 10. unknown beats at_risk: a scan that could not look at everything is never shown as green or as a
    complete list of problems. Suppressed findings (false_positive, wont_fix) never count."""
    now = now or _parse(audit.now())  # one clock: audit.now(), so tests can set it
    repo = repo_row(store, repo_id)
    last = store.one("SELECT * FROM scans WHERE repo_id=? ORDER BY rowid DESC LIMIT 1", (repo_id,))
    last_ok = store.one("SELECT * FROM scans WHERE repo_id=? AND status='complete' ORDER BY rowid DESC LIMIT 1", (repo_id,))
    counts = {s: 0 for s in STATUSES}
    for r in store.all("SELECT status, COUNT(*) AS n FROM findings WHERE repo_id=? GROUP BY status", (repo_id,)):
        counts[r["status"]] = r["n"]
    blocking = store.one(
        f"SELECT COUNT(*) AS n FROM findings WHERE repo_id=? AND status IN ('open','in_progress') AND severity IN ({','.join('?' * len(BLOCKING))})",
        (repo_id, *BLOCKING))["n"]
    reasons, status = [], None
    if last is None:
        status = "unknown"
        reasons.append("no scan yet")
    elif last["status"] != "complete":
        status = "unknown"
        reasons.append(f"latest scan {last['scan_id']} is {last['status']}")
    elif repo["watch_minutes"] and now - _parse(last_ok["finished_at"]) > timedelta(minutes=2 * repo["watch_minutes"]):
        status = "unknown"
        reasons.append(f"stale: no complete scan in {2 * repo['watch_minutes']} minutes")
    if status is None and blocking:
        status = "at_risk"
    if status is None:
        base = repo["baseline_scan_id"]
        ids = lambda sid: {r["human_id"] for r in store.all("SELECT human_id FROM scan_findings WHERE scan_id=?", (sid,))}  # noqa: E731
        added, gone = (ids(last_ok["scan_id"]) - ids(base), ids(base) - ids(last_ok["scan_id"])) if base else (set(), set())
        status = "changed" if added or gone else "healthy"
        if added or gone:
            reasons.append(f"{len(added)} added and {len(gone)} resolved since the baseline {base}")
    if blocking:
        reasons.append(f"{blocking} blocking finding(s) open")
    streak, last_error = 0, None
    for r in store.all("SELECT status, errors_json FROM scans WHERE repo_id=? ORDER BY rowid DESC LIMIT 20", (repo_id,)):
        if r["status"] == "complete":
            break
        streak += 1
        if last_error is None and (errs := json.loads(r["errors_json"] or "[]")):
            last_error = f"{errs[0].get('scanner', 'scan')}: {errs[0].get('message', '')}"
    if streak >= 2:
        reasons.append(f"the last {streak} scans failed or were incomplete")
    if streak and last_error:
        reasons.append(f"last error: {last_error}")
    if last is not None and last["mode"] == "static":
        n = len(json.loads(last["coverage_json"] or "{}").get("checks_run", []))
        reasons.append(f"static checks only ({n} of {len(CHECKS)})")
    return {"status": status, "reasons": reasons, "last_complete_scan_at": last_ok["finished_at"] if last_ok else None,
            "last_scan_status": last["status"] if last else None, "counts": counts,
            "failed_streak": streak, "last_error": last_error if streak else None}


def scan_summary(store: Store, scan_id: str) -> dict:
    """Counts of one stored scan, from its scan_completed or scan_incomplete event."""
    ev = store.one("SELECT meta_json FROM events WHERE scan_id=? AND type IN ('scan_completed','scan_incomplete') ORDER BY id DESC LIMIT 1",
                   (scan_id,))
    return json.loads(ev["meta_json"]) if ev else {}


def delta_of(store: Store, scan_id: str) -> dict:
    scan = store.one("SELECT s.*, r.full_name FROM scans s JOIN repos r ON r.id=s.repo_id WHERE s.scan_id=?", (scan_id,))
    if scan is None:
        raise StatusError(404, f"Unknown stored scan {scan_id}")
    ids = lambda kind: [r["human_id"] for r in store.all(  # noqa: E731
        "SELECT human_id FROM events WHERE scan_id=? AND type=? ORDER BY id", (scan_id, kind))]
    meta = scan_summary(store, scan_id)
    return {"scan_id": scan_id, "repo": scan["full_name"], "commit": scan["commit_sha"], "complete": scan["status"] == "complete",
            "new": ids("finding_created"), "reopened": ids("finding_reopened"), "resolved": ids("finding_resolved"),
            "persistent": meta.get("persistent", 0), "suppressed": meta.get("suppressed", 0),
            "health": health(store, scan["repo_id"])}


_SELECT = ("SELECT f.*, r.full_name, r.branch, s1.finished_at AS first_seen_at, s2.finished_at AS last_seen_at FROM findings f "
           "JOIN repos r ON r.id=f.repo_id LEFT JOIN scans s1 ON s1.scan_id=f.first_seen_scan LEFT JOIN scans s2 ON s2.scan_id=f.last_seen_scan")


def record_of(row) -> dict:
    """FindingRecord (master section 9) from a joined findings row."""
    last = json.loads(row["last_finding_json"])
    loc = last.get("evidence", {}).get("location", {})
    return {"human_id": row["human_id"], "repo": row["full_name"], "branch": row["branch"], "fingerprint": row["fingerprint"],
            "check": row["check_id"], "severity": row["severity"], "title": row["title"], "layer": row["layer"], "proof": row["proof"],
            "status": row["status"], "status_reason": row["status_reason"], "status_by": row["status_by"], "status_at": row["status_at"],
            "first_seen_at": row["first_seen_at"], "last_seen_at": row["last_seen_at"],
            "location": {"file": loc.get("file", ""), "line": loc.get("line", 0), "url": loc.get("url", "")},
            "fix_available": bool(last.get("fix", {}).get("available")), "explanation": last.get("explanation", ""),
            "slack": {"channel": row["slack_channel"], "ts": row["slack_ts"]} if row["slack_channel"] and row["slack_ts"] else None}


def get_record(store: Store, human_id: str):
    row = store.one(_SELECT + " WHERE f.human_id=?", (human_id,))
    return None if row is None else record_of(row)


def list_records(store: Store, repo_id=None, status=None, severity=None, q=None, limit=50, offset=0) -> dict:
    where, params = [], []
    if repo_id is not None:
        where.append("f.repo_id=?"), params.append(repo_id)
    if severity:
        where.append("f.severity=?"), params.append(severity)
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(f.human_id LIKE ? ESCAPE '\\' OR f.title LIKE ? ESCAPE '\\' OR f.check_id LIKE ? ESCAPE '\\' "
                     "OR json_extract(f.last_finding_json, '$.evidence.location.file') LIKE ? ESCAPE '\\')")
        params += [like] * 4
    base = (" WHERE " + " AND ".join(where)) if where else ""
    counts = {s: 0 for s in STATUSES}
    for r in store.all(f"SELECT f.status, COUNT(*) AS n FROM findings f{base} GROUP BY f.status", params):
        counts[r["status"]] = r["n"]
    if status:
        where.append("f.status=?"), params.append(status)
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    total = store.one(f"SELECT COUNT(*) AS n FROM findings f{sql_where}", params)["n"]
    rows = store.all(f"{_SELECT}{sql_where} ORDER BY f.human_id LIMIT ? OFFSET ?", (*params, limit, offset))
    return {"total": total, "counts_by_status": counts, "items": [record_of(r) for r in rows]}
