# STATUS (Tanish)
- [x] T0 contract and skeleton (commit 391aeb2)
- [x] T1 target backend V1 to V4 (built by Anmol, verified)
- [x] T2 recognizers (recognizers.py, test_recognizers.py: 14 tests pass)
- [x] T3 api_scan and idor_probe (config.py, scanners/api_scan.py, scanners/idor_probe.py, conftest.py target fixture, test_api_scanners.py: 5 tests pass)
- [x] T4 db_scan and log_scan (scanners/db_scan.py, scanners/log_scan.py ast version, test_db_scan.py, test_log_scan.py, fresh_db and raw_pii fixtures)
- [x] T5 runner and CLI scan (runner.py, `scan` command in __main__.py, test_runner.py). Live scan of :8000 gave 4 findings, score 40.
- [x] T6 engine API on :8100 (api.py, test_api.py). POST /scan then GET /scan/{id} equals the CLI output. Fix endpoint returns 501 until T10.

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
- Demo logins: aarav.sharma@example.test and diya.patel@example.test (StudentPass123!), admin@tutornest.test (AdminPass123!). Read them from config, not hard-coded in scanners.
