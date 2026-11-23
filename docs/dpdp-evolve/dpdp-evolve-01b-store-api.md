# Block 01b: store, ingest, audit, repo checkout, API (Session A, after 01a, about 60 to 75 min)

Read dpdp-evolve-00-master.md first. Needs 01a (fingerprints, coverage, static mode).

## Inspect first
engine/dpdp_lens/api.py (create_app, scans dict, inputs, save/load of .dpdp-state, fix_finding, fix_modes), fixer/verify.py (verify_fix signature, needs repo_path and db_path), target-app/backend/seed.py and app/db.py (how TUTORNEST_DB picks the database file), recognizers.py (find_pii, for the PII guard).

## Tasks
1. store.py: SQLite per master section 8. WAL mode, `Store(path)` with `":memory:"` for tests, one connection per thread or a lock, schema created in code with a `schema_version` pragma. No ORM. Parameterised queries only.
2. audit.py: `record(store, type, actor, repo_id=None, scan_id=None, human_id=None, policy_version="", result="", meta=None)`. Each event: hash = sha256(prev_hash + canonical JSON of the event without hash). `verify_chain(store) -> {ok, checked, first_bad}`. PII guard: refuse or mask any meta value that `find_pii` matches. Event types: repo_connected, scan_started, scan_completed, scan_incomplete, scan_failed, finding_created, finding_resolved, finding_reopened, status_changed, baseline_set, watch_changed, fix_started, fix_verified, fix_failed, policy_changed. Docstring and README say tamper-evident only: anyone who can write the DB file can rewrite the whole chain.
3. ingest.py: `ingest_scan(store, repo_id, scan, trigger, actor) -> ScanDelta` implementing master section 7 exactly (coverage-aware resolution, reopen, suppressed, human ID allocation in one transaction). Baseline rules and health per master sections 9 and 10. Pure logic where possible so tests need no network.
4. repo_scan.py: `checkout(full_name, ref, token) -> contextmanager Path`:
   - validate `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`, check DPDP_ALLOWED_REPOS first (empty means refuse).
   - `git clone --depth 1 --no-recurse-submodules --single-branch` into tempfile.mkdtemp mode 0700. Token goes through a GIT_ASKPASS helper script written into the temp dir (or http.extraheader via env GIT_CONFIG_*), never in the URL or argv. Pass `-c core.hooksPath=/dev/null -c protocol.file.allow=never -c core.fsmonitor=false`. Timeout 120 s, size cap 200 MB (check after clone, delete and fail if over). Always delete the temp dir in `finally`. Redact the token from any error text.
   - `scan_checkout(dir, scan_id, mode="static")`: repo_path = dir/backend if it exists else dir; calls run_scan in static mode; sets scan.repo, branch, commit (git rev-parse HEAD).
   - Tests use a local bare repo made in a temp dir (file:// is only allowed in tests via an explicit flag), no network. Test: allowlist refusal, bad name, token never in captured logs or the process args, temp dir removed after success and after failure.
5. api_v2.py: all routes from master section 9 as an APIRouter built by `create_router(store, ...)`. api.py gets ONE include line and creates the Store from DPDP_DB (default <state dir>/dpdp.db). `create_app(..., store=None)` stays test friendly. Scan routes reuse the legacy scans dict, state files and id counter (refactor `_run` minimally into something both paths call). Mutating routes check X-DPDP-Token with hmac.compare_digest. PATCH status writes the audit event and an outbox row in one transaction. Rejections per master section 7 (manual fixed, missing reason).
6. Fix route: `POST /findings/{human_id}/fix`. For a repo finding: re-checkout the commit stored on the scan, create a temp DB by running the repo's own seed with TUTORNEST_DB pointing at a temp file (only allowed because the repo is in DPDP_FIX_REPOS), then call the existing verify_fix and the legacy golden fallback. Result sets status fixed when verified, records fix events, and never writes into the stored scan JSON. If anything infrastructure-related fails, fall back to cached golden exactly as the legacy route does and label it cached.
7. Tests: transitions table (every row of master section 7), incomplete scan never resolves anything, static scan never resolves a live-probe finding, baseline never auto-replaced, suppressed never counted in at_risk, audit chain verifies and a flipped byte breaks it, outbox rows, token required, PII grep over the SQLite file after a full TutorNest ingest (no Aadhaar, PAN, phone), restart safety (open the same DB file again, ids continue).

## Acceptance
- engine suite and scripts/run_gates.sh pass. Legacy endpoints behave as before (existing tests untouched).
- With a local bare repo of TutorNest as the "remote": connect, scan, ingest, PATCH a status, GET /findings, GET /audit/verify all work through the HTTP API in one integration test.
- README: new env vars table, new endpoints summary, limits (allowlist, static only for connected repos, tamper-evident wording).

STOP. Hand over per docs/14. Tell Tanish: block 03 can integrate against real endpoints, block 04 can read real data, block 05 can start.
