# Threat model: DPDP Lens

Scope: the auditor itself (engine, dashboard, fix sandbox, HTML report) and its demo setup on localhost. Written by Tanish and Anmol. Last updated 2026-11-23, matches the code at that date.

## 1. What we protect
- Personal data seen during a scan (the demo data is synthetic, but the tool treats it as real).
- The target app's source and database during a fix.
- The integrity of findings and of the "verified" status (a false "verified" is worse than no fix).
- The machine running the auditor.

## 2. System and trust boundaries
Dashboard (browser, :5174) to Engine API (127.0.0.1:8100) to Target app (:8000, frontend :5173) and to a sandbox copy of the target. Third-party hosts appear only as request targets from the target page and are stubbed.
- Boundary 1: dashboard to engine.
- Boundary 2: engine to target.
- Boundary 3: engine to sandbox processes (uvicorn and a static server on free ports, plus `vite build` for the frontend fix).
- Boundary 4: the machine to the internet. We avoid crossing it.

## 3. Assumptions
- Runs on a developer laptop, localhost only.
- Scans only apps the operator owns.
- Demo data is synthetic.
- The operator trusts the code under test (see T6).

## 4. Threats and mitigations (STRIDE style)
| # | Threat | Type | Mitigation (as built) |
|---|--------|------|-----------------------|
| T1 | Auditor stores or shows raw PII in evidence, logs or reports | Information disclosure | Masking at the source (Aadhaar `XXXX XXXX 1234`, email `a***@x.com`, phone `98XXXXXX10`). Evidence holds masked samples only. Tests check that no raw Aadhaar or PAN is in the JSON. The HTML report escapes everything, has no scripts and sends a CSP header |
| T2 | Another site or local process calls the engine API and triggers scans | Spoofing, tampering | Engine runs on 127.0.0.1. CORS is open for localhost origins only. No authentication in this version, listed as a known limit |
| T3 | Scanning a target the operator does not own, or reading files outside the project | Misuse | `POST /scan` accepts only localhost or private-IP targets. `repo_path` and `db_path` must exist and sit inside the repo root (`DPDP_REPO_ROOT` overrides). Anything else is a 400 |
| T4 | A patch breaks the app or damages data | Tampering | Patches go to a temp copy with a copied DB, never the original folder. Each fix is verified alone on a copy of the original app |
| T5 | Sandbox process left running or port conflict | Denial of service | Free port per run, process-group kill and temp-dir delete on exit, 30 s scanner timeout and 60 s fix limit |
| T6 | Target code is executed by the fix loop (the sandbox runs the target's backend and `vite build`) | Elevation of privilege | Only the demo target is meant to run. Documented limit: run the auditor only on code you trust, ideally in a container |
| T7 | Destructive probes | Tampering | Scans are GET only, except the controlled `erasure_scan`. It signs up one synthetic user, deletes it and removes its own marker rows. This WRITES to the target DB, so a live scan changes `demo.db` and `run_demo.sh` re-seeds it. The `children_scan` probe signs up one synthetic minor and removes its own rows the same way. No payload fuzzing |
| T8 | A false "verified" status | Repudiation, integrity | `verified` is computed: the finding must be gone in the re-scan AND the app tests must pass. If the template's scanner failed in the re-scan, `verify_fix` raises instead of reading it as "gone". A patch that does not apply is a 422 with no fallback. A completed but unverified run is shown as unverified |
| T9 | Cached golden result shown as a live result | Repudiation | Cached results fall back only on infrastructure failure or the time limit, are written only from a verified live run, and the dashboard and report show "Cached golden patch mode" with the reason. Sample mode fixes are labelled "Simulated (sample data)" |
| T10 | Supply chain: malicious dependency or data file | Tampering | Small dependency set, licences credited in README, `services.json` committed with its source noted, no install scripts run at demo time |
| T11 | LLM data leakage | Information disclosure | No LLM is used in the engine. Nothing is sent to an LLM |
| T12 | Secrets in the repo | Information disclosure | `.gitignore` covers `.env`, `scan.json`, `demo.db` and logs. The demo JWT secret and logins are synthetic and demo-only |
| T13 | Third-party requests leak data when the browser scan loads the page | Information disclosure | External hosts are stubbed with an empty 200 (`page.route`), so nothing leaves the machine |
| T14 | Intentionally vulnerable demo app exposed to a network | Information disclosure | `run_demo.sh` binds the backend to 127.0.0.1. TutorNest must never be deployed (its JWT secret is a hard-coded demo value). README says so |

### Planted secrets
The demo app carries secrets that we planted on purpose for the scanner: `target-app/backend/.env` (V9), the Dockerfile and compose file (V10, V12) and a hard-coded `SECRET_KEY` in `app/auth.py`. Every value is synthetic and fake, works nowhere, and `.env` is committed through a `.gitignore` exception so the config scan has something real to find. Secret scanners such as gitleaks or GitHub secret scanning may flag them, and that is expected. The auditor itself never prints a secret in full: `config_scan` shows the first 2 characters plus `***`, and `scripts/make_sample_report.sh` fails if a planted value or raw personal data appears in `reports/`. If a real secret ever shows up in a scan of a real app, rotate it, because the file in the repository is the leak, not the report.

## 5. Out of scope and known limits
- No authentication on the engine API in this version.
- Finished scans and fix results are saved as JSON on disk (`.dpdp-state/`, masked evidence only, no raw PII) so an engine restart keeps them. The folder is not encrypted, so treat it as sensitive. A scan still running at restart is lost.
- Only a FastAPI + SQLite target is tested.
- Checks are a subset of DPDP duties. A clean scan does not mean compliance.
- No protection against a hostile target app beyond running on localhost.

## 6. What we would do next
Container sandbox for the fix loop, an API token for the engine, signed scan reports, more targets and stacks.

## 7. Safe use rules (also in README)
Use only on your own apps. Use synthetic data. Treat reports as sensitive. Never run on production.
