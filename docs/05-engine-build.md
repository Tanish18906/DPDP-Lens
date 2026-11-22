# 05 Engine build (owner: Tanish, agent: Claude Code)

Package: engine/dpdp_lens. Read 02, 03, 04 first. Work in small steps. Each scanner is one commit with its own pytest.

## Module layout
    models.py          Finding, ScanResult, scoring (done in step 1)
    recognizers.py     PII detectors and maskers
    runner.py          runs scanners, assigns ids, builds ScanResult
    scanners/
      api_scan.py      api_pii_exposure
      idor_probe.py    api_idor
      db_scan.py       db_plaintext_pii
      log_scan.py      log_pii
      erasure_scan.py  erasure_incomplete
      contact_scan.py  missing_contact
      browser_scan.py  tracker_before_consent, consent_bundled
      children_scan.py children_no_parental_consent (stretch)
      notice_drift.py  notice_drift
    fixer/
      sandbox.py       copy, free port, start and stop process group
      templates.py     deterministic patches for V1, V3, V5
      verify.py        re-scan, pytest, diff, score
    api.py             FastAPI wrapper
    report.py          HTML report
    browser.py         launch helper (bundled Chromium, fallback channel="chrome")
    data/services.json Disconnect tracker list

## Recognizers (do first, with tests)
Return a list of (type, start, end, masked) from a text value, with optional column name hint.
- Aadhaar: regex [2-9]\d{3}[ -]?\d{4}[ -]?\d{4} AND stdnum.in_.aadhaar.is_valid. About 10 percent of random 12 digit numbers pass Verhoeff, so also require context: column name contains aadhaar, aadhar, uid, or nearby word within 20 chars. A bare valid 12 digit number with no context is NOT flagged. Add a test for this.
- PAN: \b[A-Z]{3}[PCHFATBLJG][A-Z](?!0000)\d{4}[A-Z]\b
- Indian mobile: (?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{9}\b, context word phone, mobile, contact or column name hint.
- Email: simple regex.
- DOB: column name dob, birth, or ISO date in a column with such a name.
- Column name context is checked first, value check second. Column names like aadhaar, aadhar, pan, phone, mobile, email, dob, parent_pan.
- Maskers per doc 03.
Tests: valid and invalid Aadhaar (stdnum generated), PAN positive and negative, phone with and without context, a 12 digit order id that must NOT be flagged.

## Scanners

### api_scan (api_pii_exposure)
1. GET target/openapi.json. List paths and methods.
2. For every GET path with no path parameter, call without Authorization.
3. For 200 responses with JSON, walk the body, run recognizers on field names and values.
4. If PII found: one finding per endpoint. Evidence: url, kind http, summary "GET /api/students returned 15 records with aadhaar, phone, dob without login", masked_sample from the first record.
5. Skip paths that are clearly login or health. Cap at 50 requests, no request bodies, GET only.
Test: against the running target, V1 is found, a public health route is not.

### idor_probe (api_idor)
1. Log in as demo user A and demo user B (credentials from a config file, env or CLI flags, never hard coded in the scanner).
2. Find routes with an id path parameter. As A, request B's record and A's own record.
3. If A gets B's record (200 with B's data), finding. Evidence: summary "user 2 read the record of user 5".
Test: V2 found. After a fix that checks ownership, not found.

### db_scan (db_plaintext_pii)
1. Open the SQLite file read only (file:path?mode=ro). Reflect tables and columns.
2. Per column: column name hint first, then sample 20 non null rows and run recognizers.
3. Flag columns where Aadhaar or PAN appear in plaintext. Phone and email alone are low value, report them in the evidence list, not as separate findings.
4. One finding per table or column group. Evidence: table, column, masked sample.
5. Do not flag columns holding hashed values (bcrypt, sha256 prefix patterns).
Test: V4 found, password hash column not flagged.

### log_scan (log_pii)
1. Preferred: a semgrep rule that matches logger.info, logger.debug, logger.warning, logging.info and print where an argument or f string mentions a PII name (email, phone, aadhaar, pan, dob, password, token).
2. Fallback when semgrep fails: Python ast walk over *.py in the repo, same logic.
3. Evidence: file, line, the code line with variable names kept but no data (this is code, not data).
Test: V3 found. A log call with only a user_id is not flagged.

### erasure_scan (erasure_incomplete)
1. Create a synthetic user through the signup API (marker email erasure-probe@example.test).
2. Call DELETE for that user.
3. Search every table in the DB for the marker values. Ignore tables named like logs or audit (Rule 8(3) allows logs for at least 1 year).
4. If PII remains (soft delete flag, students_backup copy), finding. Evidence: tables where it remained.
5. Clean up: nothing else to do, the probe data is synthetic.
Test: V7 found.

### contact_scan (missing_contact)
Fetch the notice page and the frontend home. Look for words like DPO, data protection officer, grievance, contact, with an email or phone pattern nearby. If none, a low finding. Evidence: the pages checked.

### browser_scan (tracker_before_consent, consent_bundled)
1. Launch via browser.py. Open the signup page. Do NOT click anything.
2. Record every request event (not only responses, so blocked or offline third party hosts still count). Collect hosts that differ from the target host.
3. Classify hosts with services.json (categories like Advertising, Analytics, Social). Any Advertising, Analytics or Social host before consent gives tracker_before_consent. Evidence kind network, summary with the host and category.
4. Find checkboxes: if a consent checkbox is already checked, or the consent label bundles terms and marketing in one box, consent_bundled. Evidence kind dom with the element text.
5. For safety in the demo, the target page stubs external hosts through page.route so no data really leaves the machine, but the request event still fires.
Test: V5 and V6 found.

### children_scan (stretch)
Sign up with age 14 and no parent data through the API. If accepted with 200 or 201, finding. Clause Act s9(1), Rule 10. Do not use real data.

### notice_drift
1. Declared fields: read the notice page text, extract fields listed (name, email, phone and so on) using a keyword map.
2. Observed fields: union of PII field types seen by db_scan, api_scan and browser_scan, each with where entries like db:students.aadhaar, api:/api/students, request:connect.facebook.net.
3. Undeclared = observed minus declared.
4. Produce a notice_drift finding if undeclared is not empty. Always fill the notice_drift block in the scan JSON.
Test: undeclared equals dob, aadhaar, parent_pan on the target.

## Runner
Run scanners in order api_scan, idor_probe, db_scan, log_scan, erasure_scan, contact_scan, browser_scan, notice_drift. Catch exceptions per scanner. Assign ids F-001 upward in fixed order. Attach clauses from clauses.json. Compute counts and score.

## Fix and verify (V1, V3, V5 only)
Patches are deterministic string templates keyed by check id. They match a known marker or snippet in the planted code (see doc 06). If the snippet is not found, return an error, never guess.
Loop:
1. tmp = copytree(repo_path, ignore .git, node_modules, .venv, __pycache__)
2. copy demo.db into tmp and point the app at it with an env var
3. apply template to tmp, then py_compile the changed file
4. start the patched backend on a free port in its own process group
5. wait for /openapi.json to answer (timeout 15 seconds)
6. re-run the single failed scanner against the patched URL
7. run pytest on target-app/tests with the base URL pointed at the patched app
8. build a unified diff with difflib from original to patched files
9. kill the process group in a finally block, delete tmp
10. set fix.verified true only if the re-scan found no finding AND pytest passed. Fill score_before and score_after.
Cached golden patch mode: if live mode fails or a flag is set, return the saved result for that finding with mode "cached_golden". The UI must show this label.

Patch intent:
- V1: require admin auth on the route and drop aadhaar and parent_pan from the public response.
- V3: replace the log line with one that logs only the user id.
- V5: remove the tracker script tag from the page head and load it only after the consent button handler.

## Browser helper
Try playwright chromium.launch(). On failure, try launch(channel="chrome"). Log which one was used. Do not auto update Chrome before the demo.

## Tests
- Unit: recognizers, masking, scoring.
- Per scanner: run against the live target (a pytest fixture starts the target on a free port with a fresh seeded DB).
- Fix loop: V1 end to end, verified true, tests pass.
- The contract test checks that every scan JSON validates against the schema.

## Definition of done
- By Mon 03:30: CLI scan writes valid JSON with at least 4 findings (api, idor, db, log).
- By Mon 09:30: dashboard shows a real scan from the engine.
- By Mon 17:00: V1 fix verified live and in cached mode.
- By Mon 22:00: V3 and V5 fixes verified, browser_scan and notice_drift working.
