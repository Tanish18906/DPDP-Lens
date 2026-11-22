# STATUS (Tanish)
- [x] T0 contract and skeleton (commit 391aeb2)
- [x] T1 target backend V1 to V4 (built by Anmol, verified)
- [x] T2 recognizers (recognizers.py, test_recognizers.py: 14 tests pass)
- [x] T3 api_scan and idor_probe (config.py, scanners/api_scan.py, scanners/idor_probe.py, conftest.py target fixture, test_api_scanners.py: 5 tests pass)
- [x] T4 db_scan and log_scan (scanners/db_scan.py, scanners/log_scan.py ast version, test_db_scan.py, test_log_scan.py, fresh_db and raw_pii fixtures)
- [x] T5 runner and CLI scan (runner.py, `scan` command in __main__.py, test_runner.py). Live scan of :8000 gave 4 findings, score 40.
- [x] T6 engine API on :8100 (api.py, test_api.py). POST /scan then GET /scan/{id} equals the CLI output. Fix endpoint returns 501 until T10.
- [x] T7 erasure_scan and contact_scan (scanners/erasure_scan.py, scanners/contact_scan.py, wired into runner.py, test_erasure_scan.py, test_contact_scan.py). Default scan is now 6 findings, score 28.
- [ ] T8 browser helper and browser_scan (skipped for now, T9 was done first. A5 is pushed, so it can start.)
- [x] T9 fix sandbox (fixer/sandbox.py, test_sandbox.py: 3 tests pass). `with Sandbox(repo, db) as sb:` copies the app and DB, patch files under `sb.repo`, then `sb.start()` returns the URL. Exiting kills the process group and deletes the temp dir.

## Notes for later
- V3 patch snippet is `logger.info("signup email=%s aadhaar=%s", req.email, req.aadhaar)` in app/main.py. V1 snippet is under `# PLANTED V1` in app/main.py.
- Engine and fix-loop tests must use a temp copy of the DB through TUTORNEST_DB so demo.db stays clean.
- Scanners return Findings with id="" and clauses=[]. The runner (T5) assigns ids and attaches clauses from contract/clauses.json.
- Test fixture `target` (engine/tests/conftest.py) is session scoped. The erasure test (T7) mutates the DB, so give it its own fixture or a fresh copy.
- log_scan has the ast version only. A semgrep rule was skipped (optional per docs/05). Add one only if time is left after the 22:00 cut line.
- db_scan makes one finding per table. students_backup is empty in a fresh seed, but once rows exist (V7 delete) it gets its own db_plaintext_pii finding, so check the score effect when T7 and T5 meet.
- runner.py: new scanners (erasure, contact, browser, notice_drift) are added to the SCANNERS list in the doc 05 order. notice_drift is still None in the ScanResult until T13. Scanner errors and timeouts go to the `dpdp_lens` logger as `scanner_error`, not into the JSON (the contract has no field for them).
- test_runner.py uses `jsonschema` (only a transitive dependency of semgrep, not listed in pyproject.toml). Add it to pyproject dev deps if semgrep is ever dropped.
- api.py: scans are kept in memory only (lost on restart), no file copy yet. GET /report/{scan_id} is T14, POST /findings/{id}/fix is T10. Start the engine with `cd engine && ../.venv/bin/python -m uvicorn dpdp_lens.api:app --host 127.0.0.1 --port 8100`. A run_demo.sh (T15) should do this. The dashboard can switch USE_MOCK to false once it is running (A7).
- POST /scan only accepts localhost or private-IP targets and existing repo_path and db_path (threat T3).
- erasure_scan WRITES to the target DB: it signs up a synthetic user, deletes it, then removes its own marker rows. A live scan therefore touches target-app/backend/demo.db (tracked in git). Do not commit demo.db after a live scan: re-seed with `cd target-app/backend && ../../.venv/bin/python seed.py`, or scan a copy. Tests only use temp copies.
- contact_scan is strict: only dpo, "data protection officer" or grievance within 100 chars of an email or phone counts (a plain "contact us" does not). It reads visible text only (HTML comments, scripts, styles are ignored). It checks /notice and, when running, the frontend at config.FRONTEND_URL (:5173).
- For Anmol (A5/A6): notice.html shows a visible line "(Notice Drift Note: Notice does not declare Date of Birth, Aadhaar, Parent PAN ...)". T13 reads the notice text for declared fields, so that line would make dob, aadhaar and parent_pan look declared. It should be an HTML comment. Also keep any footer on the frontend free of DPO or grievance wording, or the missing_contact finding disappears.
- Test fixtures: `target` and `target_db` share one session target (safe because the probe cleans up). Use `fresh_target` for tests that change data.
- Sandbox for T10: the copy ignores .git, node_modules, .venv, __pycache__, *.db, *.log, so py_compile, patching and pytest of target-app/tests all work on `sb.repo` and `sb.url`. Sandbox only runs `app.main:app` with uvicorn. For V5 (frontend tag) the frontend folder must be copied separately.
- Demo logins: aarav.sharma@example.test and diya.patel@example.test (StudentPass123!), admin@tutornest.test (AdminPass123!). Read them from config, not hard-coded in scanners.
