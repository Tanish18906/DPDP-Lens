# 03 Data contract and API

Source of truth in code: contract/finding.schema.json (generated from engine/dpdp_lens/models.py). This doc explains it. Only Tanish changes the contract, and tells Anmol first.

## Scan result (summary)
Top level fields: scan_id, target, scanned_at, score (0 to 100), counts {critical, high, medium, low}, findings[], notice_drift.

Finding fields: id, check, layer (db, code, api, browser, notice), severity (critical, high, medium, low), title, explanation, clauses[{ref, note}], evidence{kind, summary, masked_sample, location{file,line,url,table,column}}, status (open, verified_fixed), fix{available, diff, verified, rescan_passed, tests_passed, score_before, score_after}.

notice_drift: declared[], observed[{field, where[]}], undeclared[].

## Scoring
Score = 100 minus weights over OPEN findings only: critical 20, high 10, medium 5, low 2. Floor 0. A finding with status verified_fixed costs nothing, so the score rises after a verified fix. counts also count open findings only.

## Masking rules for evidence
- Aadhaar: XXXX XXXX 1234
- PAN: XXXXX1234X pattern kept to last 5 characters, first 5 masked
- Phone: 98XXXXXX10
- Email: a***@domain.com
- DOB: show year only
Never store or return a raw value anywhere (JSON, logs, report).

## Check ids
| check id | layer | severity | clauses | detection | fixable |
|----------|-------|----------|---------|-----------|---------|
| api_pii_exposure | api | critical | Act s8(5), Rule 6(1)(b) | unauthenticated GET returns PII fields | yes (V1) |
| api_idor | api | critical | Act s8(5), Rule 6(1)(b) | user A can read user B | no |
| log_pii | code | high | Act s8(5), Rule 6(1)(a) | log call includes PII variable | yes (V3) |
| db_plaintext_pii | db | high | Act s8(5), Rule 6(1)(a) | Aadhaar or PAN in plaintext columns | no |
| tracker_before_consent | browser | high | Act s6(1), s9(3) | third party tracker request before any click | yes (V5) |
| consent_bundled | browser | medium | Act s5, s6(1), Rule 3 | pre ticked or bundled consent, notice not itemised | no |
| erasure_incomplete | db | high | Act s8(7) | PII remains after delete (outside logs) | no |
| children_no_parental_consent | api | high | Act s9(1), Rule 10 | under 18 signup accepted with no parent step | no |
| missing_contact | notice | low | Act s8(9), s8(10), Rule 9, Rule 14(3) | no DPO or grievance contact | no |
| notice_drift | notice | medium | Act s5, Rule 3 | collected fields not in the notice | no |

## Engine API (FastAPI, port 8100, CORS open for localhost)
- POST /scan body {target_url, repo_path, db_path} returns {scan_id}
- GET /scan/{scan_id} returns the full scan JSON. While running it returns {status:"running", step, done, total, steps_ms} (additive, U3): `step` is the scanner now running, `done` the number finished, `steps_ms` the finished steps as [{step, ms}] with measured milliseconds.
- GET /scan/{scan_id}/timings returns {steps: [{step, ms}]} for every step of that scan, measured by the engine (additive, U3). Kept in memory only, so it is empty after an engine restart.
- POST /findings/{finding_id}/fix?scan_id=...&mode=live|cached runs the fix loop and returns {finding, score_before, score_after, mode, fallback_reason, verification} where mode is "live" or "cached_golden". `verification` (additive, U3) is null for a cached result. For a live run it is {steps: [{step, ms}] for copy, patch, start, rescan, tests in that order, total_ms, sandbox (temp folder, deleted after the run), port (of the patched app), rescan_check (scanner of the finding), rescan_findings, rescan_result ("gone" or "still found"), pytest_summary (the last line pytest printed)}. All values are measured or copied from the run, never set by hand.
- The scan JSON contract (contract/finding.schema.json) is unchanged by U3: the new fields live on the running status, the timings route and the fix response, not in ScanResult.
- GET /report/{scan_id} returns an HTML report
- GET /health returns {ok:true}

Errors: return JSON {error, detail} with a proper HTTP status. The dashboard shows the message.

## CLI
    python -m dpdp_lens scan --target http://localhost:8000 --repo target-app/backend --db target-app/backend/demo.db --out scan.json
    python -m dpdp_lens sample          # prints the sample scan
    python -m dpdp_lens fix --scan scan.json --finding F-001
