# DPDP Lens EVOLVE: master brief (every agent reads this first, then its own block brief)

Written 23 Nov 2026 night. Blocks: 01a, 01b, 02, 03, 04, 05, 06, 07 (files dpdp-evolve-NN-*.md).

## 0. Paste this to every Claude Code session before anything else
Tanish is running you. The solo-builder override applies (Anmol is out). Read AGENTS.md section 4 and docs/14-git-rules.md. For this sprint these are pre-approved: creating a venv, pip and npm installs of the packages named in your block brief, starting local servers on ports 8000, 5173, 8100, 5174, running pytest and scripts/run_gates.sh. Still ask first before: deleting files, touching lines under PLANTED markers in target-app/, changing contract/ beyond what your brief lists, anything that is not read-only in git (you never run those, docs/14). Do not ask "go?" between steps inside a brief. Work through the brief and stop at its STOP line with the hand-over block from docs/14 section A.

## 1. What we are building
A DPDP compliance agent that lives in Slack and GitHub. The existing deterministic scanner stays the detection engine. Around it:
1. Finding store with stable IDs (DPDP-001) and a triage status (Open, In Progress, Fixed, False Positive, Won't Fix). Inspired by the Veria Labs feed and Slack card. Pattern only, our own look and IDs.
2. Policy-as-code: versioned policy file decides pass, warn or fail per finding.
3. CI/CD: GitHub Actions job runs the same engine, new-findings-only against a baseline, SARIF, PR summary, exit codes.
4. Slack bot: connect a repo, scan, finding cards with Change Status and Fix and verify buttons, status sync with the dashboard.
5. Scheduled monitoring (never say real-time or continuous): re-scan every N minutes, health status, baseline diff.
6. Audit trail: append-only events with a hash chain. Say tamper-evident, never tamper-proof.
7. Controlled self-healing: existing verified fix templates, now triggered from Slack, human approval by Slack click.
Optional later: scanner accuracy work (06), approve to branch and PR (07).

```
GitHub repo (ALLOWLISTED) --shallow clone--> repo_scan (static checks, never executes repo code)
Slack (Bolt, Socket Mode) <--> bot process --HTTP + X-DPDP-Token--> engine API (FastAPI :8100)
GitHub Actions: python -m dpdp_lens ci --> same evaluate code --> SARIF, step summary, exit code
engine: runner (existing scanners) -> ingest (fingerprint, IDs, status, diff) -> policy -> SQLite store + audit events
dashboard (:5174): Feed view reads GET /findings
```
Slack MCP in your Claude Code is only a dev convenience (read or post in Slack while building). It is NOT the product bot. The product bot is a Python process using slack-bolt with its own tokens.

## 2. Deadline and cut lines
Rulebook: submit by H34. If hacking began Sun 22 Nov about 20:00, H34 is Tue 24 Nov about 06:00. Tanish confirms the real time: SUBMIT_AT = ________.
- Code freeze: SUBMIT_AT minus 2h30. After that only fixes, docs, deck, video, fresh-clone test.
- Order of value: 01a, 01b, 03 (Slack cards), 02 (CI), 05, 04 (feed), 06, 07.
- If behind, cut from the end: 07, 06, 04 (read-only), 05 monitor loop. Never cut 01a or 01b.
- Packaging (not code, human work): threat model update, README, deck PDF, 2 to 3 min video, fresh-clone test, run gates. Wi-Fi at the venue is shared: keep a phone hotspot, keep the cached fix mode (labelled), record a video of the Slack flow as fallback.

## 3. Hard rules (non-negotiable)
1. Detection stays deterministic. No ML or LLM in scanners, policy, fingerprints, status logic.
2. Existing behaviour does not change. A full scan of TutorNest must stay identical: 21 findings, ids F-001 to F-021, score 13, same checks, severities, locations. Only new additive fields may appear. `cd engine && python -m pytest` and `scripts/run_gates.sh` (6 of 6) must pass at the end of every block.
3. Contract changes are additive with defaults. Old JSON must still validate. Regenerate contract/finding.schema.json from models.py (command in README), update contract/sample-scan.json, dashboard/src/sample-scan.json and docs/03.
4. Failure is explicit. A scanner crash, timeout, clone failure, file cap or missing data is never shown as pass, healthy or fixed.
5. Static scans never execute code from the scanned repo. Only the fix sandbox runs target code, only for repos in DPDP_FIX_REPOS.
6. Allowlist. Only repos listed in DPDP_ALLOWED_REPOS can be connected. Empty means refuse all. The rulebook disqualifies scanning third-party systems, so the demo repo is our own: Tanish18906/acme-tutornest (created after the clock started).
7. Secrets only from environment. Never in argv, URLs, logs, SQLite, events, Slack messages or committed files. Redact tokens in any logged string.
8. No raw PII anywhere: SQLite, events, Slack payloads, logs. Masked evidence only. Add a test that greps the DB file and the Slack payloads for Aadhaar, PAN and 10 digit phone patterns.
9. No fake functionality. No mock data in live mode, no simulated progress, no "verified" without the computed check.
10. Wording: readiness, "likely does not meet", "scheduled monitoring", "tamper-evident". Never certificate, real-time, continuous, tamper-proof, exploit proof.
11. Git: you never run git write commands. End every block with the docs/14 hand-over block. No Co-Authored-By lines.
12. README: claim only what exists. Credit new libraries (slack-bolt MIT, slack-sdk MIT, anything else you add) with licence. Keep the AI tools declaration.
13. Do not touch lines under PLANTED markers. Tell Tanish not to stage: golden files, docs/fallback-shots, package-lock.json (known noise).

## 4. File ownership (so parallel sessions do not collide)
New under engine/dpdp_lens/: fingerprint.py, store.py, ingest.py, audit.py, api_v2.py, repo_scan.py (01a, 01b), policy.py, policies/default.yaml, ci.py (02), slackbot/ package (03), monitor.py (05).
Edits to existing files, one owner each:
- models.py, checks.py, runner.py, scanners/* walkers, api.py (one include line plus passing errors): 01a and 01b only.
- sarif.py, __main__.py (adds `ci` command): 02 only. The bot starts with `python -m dpdp_lens.slackbot`, no __main__ edit.
- dashboard/src/Feed.jsx new file, App.jsx limited edits (rail item, view switch): 04 only.
- contract/policy.schema.json: 02. contract/finding.schema.json: 01a.
Two Claude Code sessions at most, three if Tanish can supervise. Session A: 01a then 01b then 05. Session B: 03 then 04 (starts at once, codes against the API in section 9 using a fake server until 01b lands). Session C after 01a: 02.

## 5. Contract additions (models.py, all with defaults)
```
ScanError: scanner:str, kind: "failed"|"timeout"|"capped", message:str (no raw PII)
Coverage: mode: "full"|"static", checks_run:list[str], checks_skipped:list[str], scanners_failed:list[str]
ScanResult +: scan_errors:list[ScanError]=[], coverage:Coverage|None=None, complete:bool=True,
              policy_version:str="", scanner_version:str="", repo:str="", branch:str="", commit:str=""
Finding +:    fingerprint:str="", proof: "probed"|"observed"|"static"="static"
```
proof lives in checks.py (field on Check, regenerate docs/CHECKS.md, keep test_checks_doc passing): probed = api_idor, erasure_incomplete, children_no_parental_consent. observed = api_pii_exposure, db_plaintext_pii, tracker_before_consent, consent_bundled, consent_no_withdrawal, notice_drift, missing_contact. static = log_pii, all config_*, fe_pii_in_storage, consent_not_recorded. Never call probed "exploit proof". Say "behaviour confirmed by a live request".

## 6. Fingerprint and IDs
fingerprint = sha256(parts joined by "|")[:16] over: check id, then by check:
- api_pii_exposure, api_idor: URL path only (no host, no port).
- log_pii: repo-relative posix file path + sorted pii field names. No line numbers anywhere.
- db_plaintext_pii: table + sorted columns. erasure_incomplete: sorted tables.
- tracker_before_consent: tracked host. consent_bundled, children_no_parental_consent, consent_*, missing_contact, notice_drift: check id only.
- config_*: repo-relative file. fe_pii_in_storage: repo-relative file.
Paths are relative to the scanned repo root, posix, no leading "./". Same app scanned from a temp clone and from the sandbox copy must give equal fingerprints. The three config_secret_committed findings in TutorNest must have three different fingerprints (verify.py `_key` does not distinguish them. Do not touch `_key`, the fix loop depends on it).
Human ID: DPDP-001, DPDP-002 ... assigned once per (repo, fingerprint), global counter, never reused.

## 7. Status model
Statuses: open, in_progress, fixed, false_positive, wont_fix.
System transitions when ingesting a scan (coverage-aware):
- fingerprint new: create open. event finding_created.
- seen and status fixed: reopen to open. event finding_reopened.
- not seen, status open or in_progress, and the finding's check is in coverage.checks_run and its scanner did not fail: fixed. event finding_resolved.
- not seen and check not covered (static scan, scanner failed): no change.
- false_positive and wont_fix: never changed by the system. Seen findings in these states count as suppressed.
- seen otherwise: update last_seen.
Manual transitions (API and Slack): open, in_progress, false_positive, wont_fix. false_positive and wont_fix need a reason (1 to 300 chars, not PII) and actor. Manual fixed is rejected with 422: "Fixed is set by a scan or a verified fix". A verified fix sets fixed and records the fix.
Suppressed findings do not block CI or lower health but are always listed.

## 8. Store (SQLite, WAL, file DPDP_DB default <state dir>/dpdp.db, in-memory for tests)
```
repos(id, full_name UNIQUE, branch, slack_channel, watch_minutes NULL, next_run_at NULL, baseline_scan_id NULL, created_at)
scans(scan_id PK 'S-001', repo_id, trigger 'manual'|'schedule'|'ci'|'bot', commit, status 'complete'|'incomplete'|'failed', mode, started_at, finished_at, policy_version, scanner_version, errors_json)
findings(human_id PK, repo_id, fingerprint, check_id, severity, title, layer, proof, status, status_reason, status_by, status_at, first_seen_scan, last_seen_scan, last_finding_json, slack_channel, slack_ts, UNIQUE(repo_id, fingerprint))
scan_findings(scan_id, human_id)
events(id INTEGER PK, ts, type, actor, repo_id, scan_id, human_id, policy_version, result, meta_json, prev_hash, hash)
outbox(id INTEGER PK, kind, human_id, created_at)
```
Scans are immutable once stored. Fix results go to events and findings.last_finding_json, not into the stored scan JSON.

## 9. API (new, in api_v2.py, included from api.py; legacy routes unchanged)
Mutating routes need header X-DPDP-Token equal to env DPDP_API_TOKEN (if the env is unset, refuse mutating calls). Error shape stays {"error","detail"}.
- POST /repos {full_name, branch?, slack_channel?} 201. 403 not allowlisted. 422 bad name (regex owner/repo).
- GET /repos list with health, last_scan_at, next_run_at, watch_minutes, baseline_scan_id.
- POST /repos/{id}/scan {mode?: "static"} 202 {scan_id}. Clone, scan, ingest in background. Same S-NNN id space and same in-memory dict and state files as legacy scans, so /scan/{id}, /report/{id}, /scan/{id}/sarif work for repo scans.
- GET /scans/{scan_id}/delta -> {scan_id, repo, commit, complete, new:[human_id], reopened:[], resolved:[], persistent:int, suppressed:int, health}.
- GET /repos/{id}/health -> {status: "healthy"|"changed"|"at_risk"|"unknown", reasons:[str], last_complete_scan_at, last_scan_status, counts:{open,in_progress,fixed,false_positive,wont_fix}}.
- GET /repos/{id}/history?limit=20 -> scans with counts, new, resolved.
- POST /repos/{id}/baseline {scan_id?, actor} explicit only. First complete scan sets a baseline only if none exists. A scan never replaces a baseline.
- POST /repos/{id}/watch {minutes|null, actor}. min 1, max 10080.
- GET /findings?repo_id&status&severity&q&limit&offset -> {total, counts_by_status, items:[FindingRecord]}.
- GET /findings/{human_id} -> FindingRecord + events + last finding JSON.
- PATCH /findings/{human_id}/status {status, reason?, actor} -> FindingRecord. Writes audit event and an outbox row.
- PUT /findings/{human_id}/slack {channel, ts}.
- POST /findings/{human_id}/fix?mode=live|cached {actor} sync, same payload as legacy fix plus FindingRecord. 403 if repo not in DPDP_FIX_REPOS. cached is labelled.
- GET /outbox?after=0 -> [{id, kind, human_id}] (bot polls every 2 seconds).
- GET /audit/events?repo_id&type&limit, GET /audit/verify -> {ok, checked, first_bad}.
FindingRecord: {human_id, repo, branch, fingerprint, check, severity, title, layer, proof, status, status_reason, status_by, status_at, first_seen_at, last_seen_at, location:{file,line,url}, fix_available, slack:{channel,ts}|null}.

## 10. Health
- unknown: latest scan incomplete or failed, or no complete scan in 2 x watch interval, or no scan yet.
- at_risk: any non-suppressed open or in_progress finding with policy action "block".
- changed: not at_risk, and findings were added or resolved versus the baseline.
- healthy: complete recent scan, nothing blocking, nothing changed versus baseline.
Static mode health always carries the reason "static checks only (n of 19)".

## 11. Env vars
DPDP_API_TOKEN, DPDP_ALLOWED_REPOS, DPDP_FIX_REPOS, DPDP_DB, DPDP_STATE_DIR (exists), GITHUB_TOKEN, SLACK_BOT_TOKEN (xoxb), SLACK_APP_TOKEN (xapp, connections:write), SLACK_APPROVERS (comma Slack user ids), SLACK_CHANNEL, ENGINE_URL (default http://127.0.0.1:8100), DASHBOARD_URL (default http://localhost:5174). Document all in README.

## 12. Target demo (what everything is for)
1. Slack: /dpdp connect Tanish18906/acme-tutornest. A burst of finding cards (static scan, banner says n of 19 checks).
2. Dashboard Feed shows the same IDs and statuses.
3. Change a status in Slack, it changes in the dashboard and the audit log shows who.
4. Fix and verify the log_pii finding from Slack: VERIFIED, status flips to Fixed.
5. Push a PR that logs an Aadhaar: CI fails on the one new finding only, SARIF annotation, Slack alert.
6. Break a scanner: Slack and dashboard say Unknown, scan incomplete. Never green.
7. Show /audit/verify and the event timeline.
