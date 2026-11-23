# Block 01a: scan integrity, static mode, fingerprints (Session A, first, about 40 min)

Read dpdp-evolve-00-master.md first. This block changes the engine core additively. Nothing else can start safely before it lands (02 needs fingerprints and static mode).

## Why
Today a scanner crash only logs "scanner_error". api.py `_run` never passes the `errors` list to run_scan, so a crashed browser_scan gives fewer findings and a better score. Scan IDs are positional. Scans need a stable fingerprint, and a mode that runs without a live app.

## Inspect first (read, do not change yet)
engine/dpdp_lens/runner.py (run_scan, step, LATE_SCANNERS, app_root_of), api.py (`_run`, start_scan), models.py, checks.py, checks_doc.py, scanners/log_scan.py (uses repo.rglob("*.py"): check it skips .git, node_modules, .venv, dist, build, __pycache__ and symlinks that leave the root), config_scan.py `scan(app_root)`, frontend_scan.py `scan(app_root)`, consent_scan.py `scan(target_url, app_root)`, fixer/verify.py `_key`.

## Tasks
1. models.py: add ScanError, Coverage and the additive fields from master section 5. Regenerate contract/finding.schema.json, update contract/sample-scan.json and dashboard/src/sample-scan.json (new fields, same values otherwise), docs/03. Old sample and golden JSON must still validate (tests/test_contract.py).
2. checks.py: add `proof` to Check per master section 5. Regenerate docs/CHECKS.md with the engine command from README. Keep test_checks_doc green.
3. runner.py:
   - Always collect scanner errors internally. If the caller passes `errors`, still append to it (verify.py depends on that). Put them in ScanResult.scan_errors with kind failed or timeout. Set complete=False if any exist.
   - Add `SCANNER_CHECKS`: scanner name to the check ids it can produce (api_scan: api_pii_exposure; idor_probe: api_idor; db_scan: db_plaintext_pii; log_scan: log_pii; erasure_scan: erasure_incomplete; children_scan: children_no_parental_consent; contact_scan: missing_contact; browser_scan: tracker_before_consent, consent_bundled; notice_drift: notice_drift; config_scan: the six config_*; frontend_scan: fe_pii_in_storage; consent_scan: consent_not_recorded, consent_no_withdrawal). Build Coverage from it: checks_run = checks of scanners that finished OK.
   - Add `mode="static"`: runs only log_scan, config_scan, frontend_scan and the consent_not_recorded half of consent_scan (split it so consent_no_withdrawal is skipped when there is no target). target_url and db_path may be empty in static mode. Everything else goes to coverage.checks_skipped. Static skips are not errors and do not set complete=False.
   - Walkers: make log_scan, config_scan and frontend_scan skip .git, node_modules, .venv, dist, build, __pycache__, and not follow symlinks that resolve outside the scan root. Cap at 5000 files and 1 MB per file. A cap hit is recorded as ScanError kind "capped" and complete=False.
   - Fill fingerprint on every finding (task 4) and proof from checks.py. Fill scanner_version (importlib.metadata, fallback "0.1.0").
   - Full mode output for TutorNest must stay identical apart from new fields.
4. fingerprint.py: `fingerprint(finding, root) -> str` exactly per master section 6. Tests: same scan twice equal; line shifts do not change it; temp copy of TutorNest at a different path gives equal fingerprints; the three config_secret_committed differ; every check id in the registry has a rule (test fails if a new check has no rule).
5. api.py: pass nothing new except that scans now carry the fields. Confirm GET /scan/{id} shows scan_errors and complete. Add `complete` and scan_errors to the dashboard sample JSON only (dashboard UI work is block 04).
6. Tests: a scanner that raises gives complete=False and an entry in scan_errors; a scanner that sleeps past the timeout gives kind timeout; static mode on engine/tests/fixtures/clean_app gives 0 findings and coverage.mode "static"; static mode on the real target-app gives only static checks and lists the rest as skipped; full-mode regression test pins 21 findings, ids, score 13.

## Acceptance
- engine suite passes (count goes up, none removed), scripts/run_gates.sh 6 of 6.
- A scan where browser_scan is forced to fail returns complete=False and scan_errors non empty, and its score is not presented as clean anywhere (the dashboard banner for this is in block 04).
- README "What it does NOT do" updated: scanner failures are now reported.

STOP. Hand over per docs/14. Tell Tanish: block 01b can start, and block 02 (Session C) can start.
