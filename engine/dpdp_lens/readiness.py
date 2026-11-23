"""DPDP readiness report for one connected repo and one stored scan (block 11). Built only from the store: the scans row
(coverage, errors, versions), the findings rows (status, last finding JSON with clauses, masked evidence and fix result), the
audit events and the audit chain check. `build` returns plain data (the JSON variant), `render` turns it into one printable HTML page.

It is a readiness report from automated checks, never a compliance audit report or a certificate. An incomplete scan or an
Unknown health is said in the first lines and the report is never shown as clean. Evidence is the masked text the scanners
stored, passed through audit.clean once more, so no raw personal data can reach the page. Every dynamic value is escaped.

The signed link (sign_link, check_link) lets a browser open the report without the X-DPDP-Token header: HMAC with the engine's
token, 15 minutes, bound to one repo id and one scan id."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from html import escape

from . import audit, ingest
from .checks import CHECKS
from .report import CSS, FOOTER, MARK, SEVERITY_ORDER
from .store import Store

TITLE = "DPDP readiness report"
DISCLAIMER = "This is a readiness report based on automated checks. It is not legal advice and not a compliance certificate."
LINK_TTL = 15 * 60
LIVE_PROOF = ("probed", "observed")


class ReportError(Exception):
    """status is the HTTP status the API answers with."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


# ---- signed links

def sign_link(secret: str, repo_id: int, scan_id: str, now: float | None = None, ttl: int = LINK_TTL) -> str:
    now = time.time() if now is None else now
    payload = base64.urlsafe_b64encode(json.dumps({"r": repo_id, "s": scan_id, "exp": int(now + ttl), "n": secrets.token_hex(4)}).encode()).decode().rstrip("=")
    return f"{payload}.{hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()}"


def check_link(secret: str, sig: str, repo_id: int, scan_id: str, now: float | None = None) -> bool:
    """True only for a link we signed, not expired, for exactly this repo and this scan. Any other case is False."""
    payload, _, mac = (sig or "").partition(".")
    if not secret or not payload or not mac:
        return False
    if not hmac.compare_digest(mac, hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()):
        return False
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return claims["r"] == repo_id and claims["s"] == scan_id and (time.time() if now is None else now) < int(claims["exp"])
    except (ValueError, KeyError, TypeError):
        return False


# ---- the data

def pick_scan(store: Store, repo_id: int, scan_id: str | None):
    """The named scan of this repo, else the latest complete one, else the latest of any status (so an incomplete or failed scan
    is reported as such). 404 when there is none."""
    if scan_id:
        row = store.one("SELECT * FROM scans WHERE repo_id=? AND scan_id=?", (repo_id, scan_id))
        if row is None:
            raise ReportError(404, f"no scan {scan_id} for this repo")
        return row
    row = store.one("SELECT * FROM scans WHERE repo_id=? AND status='complete' ORDER BY rowid DESC LIMIT 1", (repo_id,)) or \
        store.one("SELECT * FROM scans WHERE repo_id=? ORDER BY rowid DESC LIMIT 1", (repo_id,))
    if row is None:
        raise ReportError(404, "this repo has no scan yet: run /dpdp scan first")
    return row


def _fix_text(fix: dict, status: str, mode: dict | None) -> str:
    if fix.get("verified"):
        how = {"live": "live sandbox run", "cached_golden": "cached verified patch (replay)"}.get((mode or {}).get("mode"), "verified fix")
        parts = [f"Verified ({how})", "re-scan of the fixed copy: " + ("passed" if fix.get("rescan_passed") else "not passed"),
                 "app tests: " + {True: "passed", False: "not passed", None: "not run"}[fix.get("tests_passed")]]
        if fix.get("score_before") is not None and fix.get("score_after") is not None:
            parts.append(f"score {fix['score_before']} to {fix['score_after']}")
        return "; ".join(parts)
    if status == "fixed":
        return "No longer found by a later scan (no fix was run here)"
    return "A verified fix template exists, not run yet" if fix.get("available") else "No automatic fix: needs a change by the owner"


def build(store: Store, repo_id: int, scan_id: str | None = None) -> dict:
    repo = ingest.repo_row(store, repo_id)  # raises StatusError(404)
    scan = pick_scan(store, repo_id, scan_id)
    coverage, errors = json.loads(scan["coverage_json"] or "{}"), json.loads(scan["errors_json"] or "[]")
    health = ingest.health(store, repo_id)
    total = len(CHECKS)
    run = set(coverage.get("checks_run", []))
    skipped = set(coverage.get("checks_skipped", []))
    not_run = [{"check": cid, "reason": "needs a running app, so a static scan skips it" if cid in skipped
                else "its scanner did not finish: see the scan errors"} for cid in CHECKS if cid not in run]
    complete = scan["status"] == "complete"
    warnings = []
    if scan["status"] == "failed":
        warnings.append(f"Scan failed: scan {scan['scan_id']} produced no results. This is not a clean result.")
    elif not complete:
        warnings.append(f"Scan incomplete: results are partial (scan {scan['scan_id']}). This is not a clean result.")
    latest = store.one("SELECT scan_id, status FROM scans WHERE repo_id=? ORDER BY rowid DESC LIMIT 1", (repo_id,))
    if latest["scan_id"] != scan["scan_id"] and latest["status"] != "complete":
        warnings.append(f"The latest scan {latest['scan_id']} is {latest['status']}: this report shows the older scan {scan['scan_id']}.")
    if health["status"] == "unknown" and not warnings:
        warnings.append("Health is Unknown: " + "; ".join(health["reasons"][:3]) + ". This is not a clean result.")

    rows = store.all("SELECT f.* FROM scan_findings sf JOIN findings f ON f.human_id=sf.human_id WHERE sf.scan_id=?", (scan["scan_id"],))
    fix_modes = {}
    for e in store.all("SELECT human_id, meta_json FROM events WHERE repo_id=? AND type='fix_verified' ORDER BY id", (repo_id,)):
        fix_modes[e["human_id"]] = json.loads(e["meta_json"])
    findings = []
    for r in sorted(rows, key=lambda r: (SEVERITY_ORDER.get(r["severity"], 9), r["human_id"])):
        last = json.loads(r["last_finding_json"])
        ev, loc = last.get("evidence") or {}, (last.get("evidence") or {}).get("location") or {}
        where = f"{loc['file']}:{loc['line']}" if loc.get("file") and loc.get("line") else loc.get("file") or loc.get("url") or ""
        findings.append({
            "human_id": r["human_id"], "check": r["check_id"], "severity": r["severity"], "title": r["title"],
            "clauses": [{"ref": c["ref"], "note": c["note"]} for c in last.get("clauses", [])], "location": where,
            "proof": "live" if r["proof"] in LIVE_PROOF else "static", "proof_detail": r["proof"],
            "status": r["status"], "status_reason": audit.clean(r["status_reason"]), "status_by": audit.clean(r["status_by"]),
            "evidence": {"summary": audit.clean(ev.get("summary", "")), "masked_sample": audit.clean(ev.get("masked_sample", ""))},
            "fix": {"text": _fix_text(last.get("fix") or {}, r["status"], fix_modes.get(r["human_id"])), **{
                k: (last.get("fix") or {}).get(k) for k in ("available", "verified", "rescan_passed", "tests_passed", "score_before", "score_after")}}})
    by_sev, by_status, open_sev = ({k: 0 for k in SEVERITY_ORDER}, {k: 0 for k in ingest.STATUSES}, {k: 0 for k in SEVERITY_ORDER})
    for f in findings:
        by_sev[f["severity"]] += 1
        by_status[f["status"]] += 1
        if f["status"] in ingest.LIVE:
            open_sev[f["severity"]] += 1
    chain = audit.verify_chain(store)
    static = coverage.get("mode") == "static"
    limits = [
        "A connected repository is scanned statically: files are read and the app is never run. "
        + (f"{len(skipped)} of {total} checks need a running app and were not run." if static else "This scan also ran live checks against a running app."),
        "Precision and recall numbers (docs/ACCURACY.md) are measured on our own small corpus, not on code in general.",
        "The audit trail is tamper-evident, not tamper-proof: anyone who can write the database file can rewrite the whole chain.",
        "A clause reference marks a likely gap against that provision. It is not a legal finding, and main DPDP duties apply from 13 May 2027.",
        "Health and the finding statuses are as of the moment this report was made, the scan facts are as of the scan."]
    return {
        "title": TITLE, "disclaimer": DISCLAIMER, "warnings": warnings, "complete": complete and not warnings,
        "repo": {"id": repo_id, "full_name": repo["full_name"], "branch": repo["branch"] or "default branch"},
        "scan": {"scan_id": scan["scan_id"], "status": scan["status"], "trigger": scan["trigger_kind"], "commit": scan["commit_sha"],
                 "started_at": scan["started_at"], "finished_at": scan["finished_at"], "policy_version": scan["policy_version"],
                 "scanner_version": scan["scanner_version"]},
        "generated_at": audit.now(),
        "scope": {"mode": coverage.get("mode") or "none", "checks_total": total, "checks_run": len(run), "run": sorted(run), "not_run": not_run,
                  "scanners_failed": coverage.get("scanners_failed", []), "scan_errors": [
                      {"scanner": e.get("scanner", ""), "kind": e.get("kind", ""), "message": audit.clean(e.get("message", ""))} for e in errors]},
        "health": {"status": health["status"], "reasons": health["reasons"]},
        "summary": {"findings": len(findings), "by_severity": by_sev, "by_status": by_status, "open_by_severity": open_sev},
        "findings": findings,
        "audit": {"chain_ok": chain["ok"], "chain_checked": chain["checked"], "first_bad": chain["first_bad"],
                  "events_for_repo": store.one("SELECT COUNT(*) AS n FROM events WHERE repo_id=?", (repo_id,))["n"]},
        "limits": limits}


def coverage_line(report: dict) -> str:
    s = report["scope"]
    return f"{'static checks only' if s['mode'] == 'static' else s['mode']} ({s['checks_run']} of {s['checks_total']})"


# ---- the page

def h(v) -> str:
    return escape(str(v), quote=True)


EXTRA_CSS = """
.warn { border: 2px solid var(--critical); background: #fff; color: var(--critical); border-radius: 6px; padding: 10px 14px; margin: 14px 0; font-weight: 700; }
.warn.ok { border-color: var(--ok); color: var(--ok); }
button.print { font: inherit; padding: 6px 14px; border: 1px solid var(--ok); background: var(--ok); color: #fff; border-radius: 6px; cursor: pointer; }
td.small, .small { font-size: 13px; } td ul { margin: 0; padding-left: 16px; } .ev { color: var(--muted); font-size: 13px; margin-top: 4px; } td:first-child code { white-space: nowrap; }
@media print { button.print { display: none; } th, td { font-size: 11px; } }
"""


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{h(x)}</th>" for x in headers)
    return f"<table><thead><tr>{head}</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table>"


def render(r: dict, nonce: str = "") -> str:
    s, sc = r["scan"], r["scope"]
    warn = "".join(f'<p class="warn" role="alert">{h(w)}</p>' for w in r["warnings"])
    sev = " ".join(f'<span class="count"><b>{n}</b>{h(k)}</span>' for k, n in r["summary"]["by_severity"].items())
    status = " ".join(f'<span class="count"><b>{n}</b>{h(k.replace("_", " "))}</span>' for k, n in r["summary"]["by_status"].items())
    not_run = _table(["Check", "Why it did not run"], [[f"<code>{h(x['check'])}</code>", h(x["reason"])] for x in sc["not_run"]]) if sc["not_run"] else "<p>Every check ran.</p>"
    errors = ("<ul>" + "".join(f"<li><code>{h(e['scanner'])}</code> {h(e['kind'])}: {h(e['message'])}</li>" for e in sc["scan_errors"]) + "</ul>") if sc["scan_errors"] else "<p>No scan errors.</p>"
    frows = []
    for f in r["findings"]:
        clauses = "<ul>" + "".join(f"<li>{h(c['ref'])}: {h(c['note'])}</li>" for c in f["clauses"]) + "</ul>"
        ev = f'<div class="ev">{h(f["evidence"]["summary"])}' + (f" <code>{h(f['evidence']['masked_sample'])}</code>" if f["evidence"]["masked_sample"] else "") + "</div>"
        status_cell = h(f["status"].replace("_", " ")) + (f'<div class="ev">{h(f["status_reason"])} ({h(f["status_by"])})</div>' if f["status_reason"] or f["status_by"] else "")
        frows.append([f'<code>{h(f["human_id"])}</code>', f'<span class="pill {h(f["severity"])}">{h(f["severity"])}</span>', f'{h(f["title"])}{ev}', clauses,
                      f'<code>{h(f["location"])}</code>', f'<span class="tag" title="{h(f["proof_detail"])}">{h(f["proof"])}</span>', status_cell, h(f["fix"]["text"])])
    findings = _table(["ID", "Severity", "Finding and masked evidence", "DPDP clauses", "Location", "Proof", "Status", "Fix"], frows) if frows else "<p>No findings were stored for this scan.</p>"
    a = r["audit"]
    chain = (f'<p class="ok">Audit chain intact: {a["chain_checked"]} events checked.</p>' if a["chain_ok"]
             else f'<p class="bad">Audit chain BROKEN: the first bad event is number {h(a["first_bad"])} ({a["chain_checked"]} events were fine before it). Do not rely on the history.</p>')
    script = f'<script nonce="{h(nonce)}">document.getElementById("print").addEventListener("click",function(){{window.print()}})</script>' if nonce else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{h(TITLE)}: {h(r['repo']['full_name'])}</title><style>{CSS}{EXTRA_CSS}</style></head><body>
<div class="brand">{MARK}<span>DPDP Lens</span></div>
<h1>{h(TITLE)}</h1><p class="muted">{h(r['repo']['full_name'])} · scan {h(s['scan_id'])} · made {h(r['generated_at'])}</p>
<p><button id="print" class="print" type="button">Print / Save as PDF</button></p>
{warn}
<h2>What this report is</h2><p class="notice">{h(r['disclaimer'])}</p>
<h2>Scan</h2><dl><dt>Repository</dt><dd>{h(r['repo']['full_name'])}</dd><dt>Branch</dt><dd>{h(r['repo']['branch'])}</dd>
<dt>Commit</dt><dd><code>{h(s['commit'] or 'not recorded')}</code></dd><dt>Scan</dt><dd>{h(s['scan_id'])} ({h(s['status'])}, {h(s['trigger'])})</dd>
<dt>Date</dt><dd>{h(s['finished_at'])}</dd><dt>Policy version</dt><dd>{h(s['policy_version'] or 'none recorded')}</dd><dt>Scanner version</dt><dd>{h(s['scanner_version'] or 'none recorded')}</dd></dl>
<h2>Scope</h2><p><b>{h(coverage_line(r))}</b>, mode {h(sc['mode'])}.</p>{not_run}<h3>Scan errors</h3>{errors}
<h2>Health</h2><p class="reason">{h(r['health']['status'].replace('_', ' ').title())}</p><ul>{''.join(f'<li>{h(x)}</li>' for x in r['health']['reasons']) or '<li>No reasons recorded.</li>'}</ul>
<h2>Summary</h2><p>{r['summary']['findings']} findings in this scan, by severity:</p><div class="summary">{sev}</div><p>By status (as of now):</p><div class="summary">{status}</div>
<h2>Findings</h2>{findings}
<h2>Audit trail</h2>{chain}<p>{a['events_for_repo']} audit events are recorded for this repository.</p>
<h2>Limits</h2><ul>{''.join(f'<li>{h(x)}</li>' for x in r['limits'])}</ul>
<footer>{h(FOOTER)}</footer>{script}</body></html>"""
