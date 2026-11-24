# DPDP Lens

**Does your app do what your privacy notice says?** DPDP Lens is a Slack-first readiness platform for India's Digital Personal Data Protection Act 2023 and DPDP Rules 2025, built on a deterministic scanner. It is a **readiness report, not a compliance certificate**.

Five parts, as built:

1. **Policy-as-code.** A versioned policy file (`engine/dpdp_lens/policies/default.yaml`) decides block, warn or info for each check, and an optional `.dpdp-lens.yml` in the scanned repo adjusts it.
2. **CI/CD with SARIF.** `python -m dpdp_lens ci` scans a checkout, judges it by the policy, writes SARIF 2.1.0, a JSON result and a Markdown summary, and exits 0, 1 or 2. A GitHub Actions workflow is in `docs/ci-example/`.
3. **Scheduled monitoring.** The engine re-scans a connected repository every N minutes you choose (`/dpdp watch`). It runs on the schedule you set and nothing is watched between two scans. A failed or incomplete scan turns the repository to Unknown, never green.
4. **Tamper-evident audit trail.** Every status change, scan and fix is an append-only event that holds the hash of the one before. It is tamper-evident, not tamper-proof.
5. **Controlled self-healing with human approval.** Fix and verify patches a temp copy of the code, re-scans it and runs the repository's tests. In Slack only listed approvers can run it, and only for repositories in `DPDP_FIX_REPOS`.

**Detection is deterministic**: regular expressions, checksums (Verhoeff for Aadhaar), Python `ast`, config parsing and a headless browser. There is no machine learning and no LLM in detection, policy, fingerprints or status logic.

Repositories connected from Slack are scanned **static only: 16 of the 26 checks** (the ones that read files). The other 10 need a running app and run against the demo app TutorNest.

Built at Hack-a-Sol 5.0, IIIT Naya Raipur, Cyber track (CS-01 Full-Stack Data Protection (DPDP) Compliance Auditor). Everything runs on localhost against our own synthetic demo app.

## The problem

The main DPDP duties apply from **13 May 2027**. Under the Act's Schedule, failing to keep reasonable security safeguards (s8(5)) can cost up to Rs 250 crore, and most startups have no privacy team. Existing tools (dcomply, Privado, Indian consent SaaS) each cover part of the problem. Our edge is cross-layer proof plus verified fixes, not "nobody scans code".

## What it does

DPDP Lens scans a running app and its source across the database, backend code, config files, running API, browser and privacy notice, produces evidence-backed findings with file and line mapped to Act sections and Rules, then proves a fix: it patches a COPY of the app, re-runs the failed check, runs the app's tests, and shows the diff and the score change.

- **Cross-layer, one report.** Database, backend code, config files (`.env`, Dockerfile, compose), front end source, running API, browser and the privacy notice are scanned together. Each finding has masked evidence, a file and line where there is one, the Act section or Rule it relates to, a severity with a one sentence reason, and a recommended fix.
- **Verified fix.** Fixes are applied to a temp copy of the app, never the original. A fix counts as `verified` only when the re-scan no longer finds the issue AND the app's tests pass. The status is computed, never set by hand.
- **Notice vs Runtime Truth.** Compares the personal data fields the public notice lists against the fields found in the DB and in unauthenticated API responses. Fields collected but not declared are flagged.
- **HTML report.** `GET /report/{scan_id}` gives a self-contained, printable report.

Verified fixes: 9 of the 11 static findings in the demo repo (`Tanish18906/acme-tutornest`) have one, and so do the live and consent findings of TutorNest. Fourteen checks have a fix template (the API, log, tracker, consent, erasure and under-18 checks, `fe_pii_in_storage`, `config_secret_committed` for `.env` and compose files, and the Docker, CORS, debug and database port config checks). Two findings have none, on purpose: `config_secret_committed` in `backend/app/auth.py` (a signing key in source: rotating it is the owner's job) and `consent_not_recorded` (needs a design decision, no safe automatic patch). The Terraform, Kubernetes, bucket and security group checks, plaintext columns and the notice items have no fix either. A fix counts as verified only when the re-scan no longer finds the issue, nothing new appears, applying it twice changes nothing and the repo's own tests pass. Every fix is verified in a sandbox copy: **the repository is unchanged unless a pull request is opened** (see below). Each fix prints two lines, "Verified: ..." and "Not verified / you still must: ..."; a fix of a secret says to rotate it. Two fixes are partial and say so: the under-18 fix (V8) only requires a well-formed parent PAN, it does not verify the parent (Rule 10), and the consent fix (V6) unticks the box and drops the marketing wording, while the notice still does not list every field, so `notice_drift` stays open. Cached golden results exist for offline demos and are labelled "Cached golden patch mode".

## Architecture

    Dashboard (React, :5174) --> Engine API (FastAPI, :8100) --> Target app TutorNest (:8000, frontend :5173)
                                       |--> scanners: db, code, config, frontend, api, browser, notice, consent
                                       '--> fix sandbox: temp copy of the app, patch, re-scan, pytest

    Slack (Socket Mode) <--> bot process (python -m dpdp_lens.slackbot) --HTTP + X-DPDP-Token--> Engine API
    GitHub (allowlisted repos) --shallow clone--> static scan --> SQLite store (findings, audit chain, outbox)
    GitHub Actions: python -m dpdp_lens ci --> same checks --> policy --> SARIF, summary, exit code

The only interface between engine and dashboard is the scan JSON (`contract/finding.schema.json`, example in `contract/sample-scan.json`).

## 5 minute quickstart (Slack demo, localhost only)

Needs Python 3.12 or newer (checked on 3.12 and 3.14), Node 20 or newer (checked on 22), git and a Slack app (set it up once with [docs/slack-bot.md](docs/slack-bot.md)).

    python3 -m venv .venv && source .venv/bin/activate
    pip install -e "engine[slack]" pyjwt pytest jsonschema
    (cd dashboard && npm install)
    cp scripts/demo_env.example scripts/demo_env     # fill in every value; the real file is git-ignored
    scripts/demo_up.sh                               # preflight, then engine :8100, dashboard :5174 and the Slack bot
    # open http://localhost:5174, then in Slack: /dpdp connect Tanish18906/acme-tutornest
    scripts/demo_down.sh

`demo_up.sh` runs `scripts/preflight.py` before and after it starts anything: one PASS, WARN or FAIL line per check with a one-line fix, and it never prints a secret. `scripts/demo_reset.sh` deletes the findings database and saved scans for a clean start (only after you type `yes`). What each preflight line means and what to do when it fails: [docs/demo-runbook.md](docs/demo-runbook.md). More: [docs/slack-bot.md](docs/slack-bot.md) (Slack setup), [docs/ACCURACY.md](docs/ACCURACY.md) (measured precision and recall), [docs/threat-model.md](docs/threat-model.md) (threat model).

`playwright install chromium` is only needed for the browser scan, the PDF report and the gates (or have Google Chrome installed, the browser scan falls back to it). To run the tests: `cd engine && python -m pytest`; four tests in `tests/test_verify.py` skip until you also run `npm install` in `target-app/frontend` (the V5 fix builds that front end).

## Local demo without Slack (scan and fix on TutorNest)

One-time setup (Python 3.12 or newer, Node 20 or newer):

    python3 -m venv .venv && source .venv/bin/activate
    pip install -e "engine[slack]" pyjwt pytest jsonschema
    playwright install chromium    # or have Google Chrome installed, the browser scan falls back to it
    (cd target-app/frontend && npm install)
    (cd dashboard && npm install)    # npm may rewrite package-lock.json (npm version differences), do not commit that

Then start everything:

    ./run_demo.sh

It re-seeds the synthetic `demo.db`, starts the target backend (:8000), the target frontend (:5173), the engine API (:8100) and the dashboard (:5174), and stops them all on Ctrl-C. Open http://localhost:5174 and click scan. It refuses to start if one of those ports is busy.

The erasure and children checks sign up synthetic users and remove their own rows, so a live scan still writes to `demo.db` briefly. `run_demo.sh` re-seeds it on every start.

CLI scan (backend must be running, venv from the quick start active):

    cd engine && python -m dpdp_lens scan --target http://localhost:8000 \
      --repo ../target-app/backend --db ../target-app/backend/demo.db --out scan.json

Tests:

    cd engine && python -m pytest

## Checks

26 checks. Severity and clauses come from `contract/clauses.json` (checked against the Act and Rules text). The full list, the recommended fix per check and every rule we wrote (recognizers, secret rule, config rules) is in [docs/CHECKS.md](docs/CHECKS.md), generated by `cd engine && python -m dpdp_lens checks --md`.

| Check id | Layer | Severity | Clauses | What it detects | Verified fix |
|----------|-------|----------|---------|-----------------|--------------|
| `api_pii_exposure` | api | critical | Act s8(5), Rule 6(1)(b) | A GET route answers without a login and returns personal data. | yes (V1) |
| `api_idor` | api | critical | Act s8(5), Rule 6(1)(b) | A logged-in user can read another user's record by changing the id in the route. | yes (V2) |
| `log_pii` | code | high | Act s8(5), Rule 6(1)(a) | A logging call in the source includes personal data fields. | yes (V3) |
| `db_plaintext_pii` | db | high | Act s8(5), Rule 6(1)(a) | A table column holds Aadhaar or PAN values as readable text. | no |
| `tracker_before_consent` | browser | high | Act s6(1), Act s9(3) | The signup page requests a known tracker host before any click. | yes (V5) |
| `consent_bundled` | browser | medium | Act s5, Act s6(1), Rule 3 | The consent checkbox is pre ticked, or one box covers terms and marketing. | yes (V6, partial) |
| `erasure_incomplete` | db | high | Act s8(7) | After a delete request, a synthetic user's data is still in the database. | yes (V7) |
| `children_no_parental_consent` | api | high | Act s9(1), Rule 10 | A signup for a 14 year old is accepted with no parent data. | yes (V8, partial) |
| `missing_contact` | notice | low | Act s8(9), Act s8(10), Rule 9, Rule 14(3) | No page lists a data protection officer or grievance contact with an email or phone. | no |
| `notice_drift` | notice | medium | Act s5, Rule 3 | The app handles personal data fields that the public notice does not list. | no |
| `config_secret_committed` | config | high | Act s8(5), Rule 6(1)(b), Rule 6(1)(g) | A key named like a secret, password, token or API key has a literal value in a config file or source. | yes (not for source files such as auth.py) |
| `config_env_in_image` | config | high | Act s8(5), Rule 6(1)(g) | A Dockerfile copies a .env file, or sets a secret with ENV or ARG. | yes |
| `config_container_root` | config | medium | Act s8(5), Rule 6(1)(g) | A Dockerfile has no USER instruction, or the last USER is root. | yes |
| `config_cors_wildcard` | config | medium | Act s8(5), Rule 6(1)(b) | allow_origins holds "*", or the Access-Control-Allow-Origin header is *. | yes |
| `config_debug_enabled` | config | medium | Act s8(5), Rule 6(1)(g) | DEBUG is true in an env file, debug=True is in app code, or a container command uses reload. | yes |
| `config_db_exposed` | config | high | Act s8(5), Rule 6(1)(b) | A compose file publishes a database port without binding it to 127.0.0.1. | yes |
| `config_s3_public` | config | high | Act s8(5), Rule 6(1)(b), Rule 6(1)(g) | A storage bucket or ACL grants public read access to stored files. | no |
| `config_security_group_ingress_anywhere` | config | high | Act s8(5), Rule 6(1)(b), Rule 6(1)(g) | A security group or firewall rule allows inbound traffic from 0.0.0.0/0 on a database or administration port. | no |
| `config_storage_unencrypted` | config | high | Act s8(5), Rule 6(1)(a) | A database, volume, or storage resource has encryption explicitly disabled. | no |
| `config_tf_hardcoded_secret` | config | high | Act s8(5), Rule 6(1)(b), Rule 6(1)(g) | A Terraform provider or resource block holds a hardcoded access key or secret. | no |
| `config_k8s_privileged` | config | medium | Act s8(5), Rule 6(1)(g) | A Kubernetes manifest sets privileged true, runAsUser 0, or allowPrivilegeEscalation true. | no |
| `config_k8s_host_network` | config | medium | Act s8(5), Rule 6(1)(g) | A Kubernetes manifest configures hostNetwork true, exposing node network traffic. | no |
| `config_k8s_secret_in_env` | config | high | Act s8(5), Rule 6(1)(b), Rule 6(1)(g) | A Kubernetes container env entry sets a secret value as a literal string instead of referencing a Secret. | no |
| `fe_pii_in_storage` | frontend | medium | Act s8(5), Rule 6(1)(a) | localStorage or sessionStorage setItem is called with a key or value that names personal data. | yes |
| `consent_not_recorded` | code | medium | Act s6(10), Act s6(1) | No consent table, column or model field exists in the schema or the backend source. | no, on purpose |
| `consent_no_withdrawal` | api | medium | Act s6(4), Act s6(6) | No route in the OpenAPI spec is about consent, withdrawal, revoking, opting out or unsubscribing. | no |

Score = 100 minus weights (critical 10, high 5, medium 2, low 1), floor 0, open findings only. The weights live in one place, `SEVERITY_WEIGHTS` in `engine/dpdp_lens/models.py`.

## Scanner accuracy

`cd engine && python -m dpdp_lens eval` measures the static scanners and the personal data recognizers against a labelled corpus in `engine/tests/accuracy/` (one small app per case, marked pos or neg, with hard negatives such as placeholder secrets, numbers that look like an Aadhaar or a phone number, test files and comments) and prints precision and recall per check. `--md` prints the table for docs/ACCURACY.md, `--json` the full report. A test fails when any number drops below its floor. On the current corpus: precision 97%, recall 100%, and the static scan of TutorNest finds all 11 expected findings with none extra. The precision and recall numbers are measured on **our own labelled corpus of 152 cases** (74 true positives, 2 false positives, 0 misses, 76 true negatives, written by us). They are **not a real-world benchmark** and describe that corpus only, not code in general; live checks (API, database, browser) are not in it. [docs/ACCURACY.md](docs/ACCURACY.md) has the table, every miss and the history of each change.

## CS-01 coverage map

The official CS-01 text asks for a scanner that finds where personal data is mishandled in code and configuration and maps each finding to the Act and Rules. Where each item lives:

| CS-01 item | Where it is covered |
|------------|---------------------|
| M1 code and config: front end | `frontend_scan` (form fields, browser storage), `browser_scan` (the running page) |
| M1 back end | `log_scan`, `config_scan` (secrets, CORS, debug in source), `consent_scan` (schema and source) |
| M1 API routes | `api_scan`, `idor_probe`, `children_scan`, `erasure_scan`, `consent_scan` (OpenAPI spec) |
| M1 database schemas | `db_scan` (the live SQLite file), locator (`CREATE TABLE` line in source) |
| M1 infrastructure files | `config_scan`: `.env`, Dockerfile, docker-compose, yaml, json, toml, ini, cfg, conf |
| M2 personal data detection | recognizers (Aadhaar with Verhoeff, PAN, mobile, email, date of birth, name) used by the DB, API, log, front end and notice scans |
| M3 DPDP mapping | `contract/clauses.json`, one clause list per check, verified against the Act and Rules |
| M4 risk classification with a justification | severity per check (`engine/dpdp_lens/checks.py`) and a `severity_reason` sentence built from the scan facts, never from a model |
| M5 compliance report | `GET /report/{scan_id}` (HTML and PDF), `reports/tutornest-report.html`: evidence with file and line, provision, severity, recommended fix |
| Bonus: consent flow | `tracker_before_consent`, `consent_bundled`, `consent_not_recorded`, `consent_no_withdrawal` |
| Bonus: code level fixes | 7 verified patches on a temp copy (V1, V2, V3, V5, V6, V7, V8), diff download, SARIF export |
| Bonus: live testing | the API, IDOR, deletion and under-18 probes run against the running app |
| Deliverable: scanner and source | `engine/` |
| Deliverable: report for our target app | `reports/` (`tutornest-report.html`, `tutornest-scan.json`, `tutornest.sarif`), made by `scripts/make_sample_report.sh` |
| Deliverable: checks and rules we wrote | [docs/CHECKS.md](docs/CHECKS.md) |

## Planted violations (TutorNest)

TutorNest is our own deliberately vulnerable demo app. **We planted every violation below ourselves. All values are synthetic and fake.** Each planted spot is marked `PLANTED Vn` in the code.

| Id | Where | What | Check |
|----|-------|------|-------|
| V1 | `GET /api/students` | no login, returns name, phone, dob, Aadhaar, parent PAN | `api_pii_exposure` |
| V2 | `GET /api/students/{id}` | any logged in user reads any record | `api_idor` |
| V3 | signup handler | email and Aadhaar written to the log | `log_pii` |
| V4 | `students` table | Aadhaar and parent PAN stored as plain text | `db_plaintext_pii` |
| V5 | signup page | Facebook pixel loads before any consent click | `tracker_before_consent` |
| V6 | signup page and notice | consent box pre-ticked and bundled, notice does not itemise | `consent_bundled`, `notice_drift` |
| V7 | `DELETE /api/students/{id}` | only sets a flag, data stays in `students` and `students_backup` | `erasure_incomplete` |
| V8 | signup | age 14 accepted with no parental step | `children_no_parental_consent` |
| V9 | `target-app/backend/.env` | fake `JWT_SECRET`, `DB_PASSWORD`, `SMTP_PASSWORD` and `DEBUG=true` | `config_secret_committed`, `config_debug_enabled` |
| V10 | `target-app/backend/Dockerfile` | copies `.env` into the image, no `USER` | `config_env_in_image`, `config_container_root` |
| V11 | CORS block in `app/main.py` | `allow_origins=["*"]` with credentials | `config_cors_wildcard` |
| V12 | `target-app/docker-compose.yml` | a legacy `db` service publishes port 5432 with a weak password | `config_db_exposed`, `config_secret_committed` |
| V13 | signup component | name, date of birth and Aadhaar saved in `localStorage` | `fe_pii_in_storage` |
| V14 | absence | no consent is recorded anywhere | `consent_not_recorded` |
| V15 | absence | no consent withdrawal route | `consent_no_withdrawal` |
| (extra) | site | no DPO or grievance contact | `missing_contact` |

One more finding is real and has no `PLANTED` marker: `app/auth.py` has a hard-coded `SECRET_KEY` (a demo value). `config_scan` reports it as a third `config_secret_committed`, so a full scan has 21 findings. `backend/.env` is committed on purpose (a `.gitignore` exception and `git add -f`), so gitleaks or GitHub secret scanning may flag it. It holds fake values only.

## Clean control

`engine/tests/fixtures/clean_app/` is a small app with a non root Dockerfile, no secrets, specific CORS origins, no debug, a compose file that binds its database to 127.0.0.1, a front end that keeps no personal data in browser storage, a consent table and a withdrawal route. The tests assert that it produces 0 config findings, 0 front end findings and neither consent finding, so the scanners are not just flagging everything.

## Sample report

`./scripts/make_sample_report.sh` scans TutorNest and writes `reports/tutornest-scan.json`, `reports/tutornest-report.html` and `reports/tutornest.sarif`, then checks them for raw personal data and for the planted secret values. Only masked values are in the files.

## Interactive shell (CLI)

    cd engine && python -m dpdp_lens        # no arguments opens the shell

Inline output, no full screen: `●` for an action, `⎿` for its results, a spinner with elapsed seconds while a step runs, a `/` command menu (arrow keys, Tab), a bottom bar with target, last scan id, score and open findings. Piped or in CI it prints the same lines with no colour and no spinner.

| Command | What it does |
|---------|--------------|
| `/scan [--target URL] [--repo PATH] [--db PATH]` | scan, defaults are the TutorNest demo values (printed first) |
| `/findings`, `/show F-001` | grouped list (critical first), one finding in full |
| `/fix F-001 [--cached]` | verified fix on a copy, coloured diff, score change. Cached mode is always labelled |
| `/report [path]` | HTML report, default `reports/last-scan.html` |
| `/checks`, `/status`, `/help`, `/clear`, `/exit` | |

Example (real output of a scan of TutorNest, shortened):

    ❯ /scan
    ● Scan  http://localhost:8000
      ⎿ API        found 1
      ⎿ DATABASE   found 1
      ⎿ CONFIG     found 8
    Score 13/100 · 2 critical · 10 high · 8 medium · 1 low
    ❯ /fix F-001
    ● Fix F-001  (runs on a copy, your code is not touched)
      ⎿ Patched   app/main.py
      ⎿ Re-scan   passed
      ⎿ Tests     passed
      ⎿ Verified  ✓  2.0s
    Score 13 → 23 (+10)

The `scan` command has two more flags: `--pretty` prints the grouped list instead of the JSON (`--out` still writes the JSON), and `--fail-on critical|high|medium|low|none` (default `none`) exits 1 when an open finding is at or above that severity, for CI. Text from a finding can come from the scanned app, so the shell strips escape and control characters from it before printing.

## CI use (policy and SARIF)

Install the engine from a checkout with `pip install -e "<checkout>/engine"`. A plain `pip install git+...#subdirectory=engine` does not work: the policy file and `contract/clauses.json` sit outside the installed package.

    cd engine && python -m dpdp_lens ci --repo-dir .. --sarif out.sarif --json out.json --summary out.md
    python -m dpdp_lens ci --repo-dir <checkout> --write-baseline      # once: accepts today's findings
    python -m dpdp_lens ci --repo-dir <checkout> --new-only            # pull requests: only new findings fail
    python -m dpdp_lens scan --static --repo <backend>                 # the file-reading checks only, no app, no database

`ci` runs the static checks and judges them with `engine/dpdp_lens/policies/default.yaml` (critical and high block, medium warn, low info). Exit 0 = pass or warn, 1 = blocking findings, 2 = the scan was incomplete or the config, policy or baseline is invalid (never a pass). An optional `.dpdp-lens.yml` in the scanned repo sets `policy`, `block_on`, `warn_on`, `categories`, `new_only`, `baseline` and `suppress` (see `docs/ci-example/dpdp-lens.config.yml`).

On this repository `ci --repo-dir ..` exits 1 (blocking findings), because it contains the deliberately vulnerable demo app; `ci --repo-dir ../target-app --write-baseline` followed by `--new-only` exits 0.

Copy `docs/ci-example/dpdp-lens.yml` to `.github/workflows/` of the repo to scan. It uploads SARIF (code scanning annotations need a public repo or GitHub Code Security, and GitHub shows them in a pull request only on lines the pull request changed), writes a step summary, keeps the JSON and SARIF as an artifact, and posts to Slack if the secret `SLACK_WEBHOOK_URL` is set and the decision is not pass. SARIF lists only findings that have a repo file; live API, database and browser findings stay in the JSON.

A live scan can also write SARIF (`scan ... --out scan.json --sarif scan.sarif`, or `GET /scan/{scan_id}/sarif`): one rule per check, one result per open finding that has a file, severity mapped to error (critical, high), warning (medium) and note (low), clauses in the rule help text, masked text only. The SARIF output is validated against the official 2.1.0 schema in the tests. An upload to GitHub code scanning and the Slack webhook step have not been tried against GitHub or Slack.

## Finding store and repo API

Findings of connected repos get stable IDs (DPDP-001, never reused), a triage status (open, in_progress, fixed, false_positive, wont_fix) and an append-only audit log, in one SQLite file (`DPDP_DB`, default `.dpdp-state/dpdp.db`, WAL mode). A scan resolves a finding only when its check actually ran in that scan (`coverage.checks_run`), so an incomplete or static scan never marks something fixed that it could not look at. "Fixed" is set by a scan or a verified fix, never by hand.

| Env var | Meaning |
|---------|---------|
| `DPDP_API_TOKEN` | Required header value `X-DPDP-Token` for every change (POST, PATCH, PUT on the routes below). Unset: all changes are refused. |
| `DPDP_ALLOWED_REPOS` | Comma separated `owner/name` list that may be connected and scanned. Empty: none. |
| `DPDP_FIX_REPOS` | Comma separated list whose code may be run by a live fix. Empty: none. |
| `DPDP_DB` | Path of the SQLite file. |
| `DPDP_MONITOR` | `0` turns the scheduled re-scan thread off. Any other value (or unset) leaves it on. It only runs inside the real engine server, never in tests or in `scripts/run_gates.sh`. |
| `DPDP_STATE_DIR` | Folder of saved scans (exists already). |
| `GITHUB_TOKEN` | Optional, for private repos. Read from the environment only, given to git through `GIT_ASKPASS`, never in a URL, argument, log or event. |

| Route | What it does |
|-------|--------------|
| `POST /repos`, `GET /repos` | Connect an allowlisted repo (403 if not allowlisted, 422 for a bad name), list repos with health. |
| `POST /repos/{id}/scan` | Shallow clone, static scan, store (202, `{scan_id}`). The scan is also reachable by the legacy `/scan/{id}`, `/report/{id}` and SARIF routes. |
| `GET /scans/{scan_id}/delta`, `GET /repos/{id}/health`, `GET /repos/{id}/history` | New, reopened and resolved findings, healthy / changed / at_risk / unknown, scan history. |
| `GET /repos/{id}/diff?scan_id=` | A scan (default the latest) against the baseline: new, resolved and persistent finding IDs, and `complete`. Resolved only counts checks the scan ran. 404 when there is no baseline. |
| `POST /repos/{id}/baseline`, `POST /repos/{id}/watch` | Set the baseline explicitly (a scan never replaces it), set the re-scan interval. |
| `GET /findings`, `GET /findings/{id}`, `PATCH /findings/{id}/status`, `PUT /findings/{id}/slack` | List with filters, detail with events, change status, link a Slack message. |
| `POST /findings/{id}/fix?mode=live\|cached` | Fix and verify a stored finding (same loop as before, on a fresh checkout of the scanned commit). The stored scan is never edited. |
| `GET /outbox?after=N`, `GET /audit/events`, `GET /audit/verify` | Change feed for the Slack bot (rows `{id, kind, human_id, repo_id, scan_id}`), audit events, hash chain check. |

Scheduled monitoring (nothing is watched between two scans). `POST /repos/{id}/watch {minutes}` makes the engine re-scan that repo every N minutes (1 to 10080). The schedule is stored in SQLite, so a restart keeps it, and a window missed while the engine was down runs once. One scan runs at a time. A failed clone, a crash or an incomplete scan is stored as such and the repo turns "unknown"; so does a repo with no complete scan in twice its interval ("stale"). `GET /repos/{id}/health` shows `failed_streak` and `last_error`. The monitor adds two outbox kinds, written in the same transaction as the change that caused them: `scan_delta` (a scheduled scan found a new or reopened critical or high finding) and `health_changed` (health moved into or out of at_risk or unknown, so an unchanged state alerts once, not on every scan). Manual scans never queue these two kinds.

### Feed (dashboard)

The dashboard's **Feed** view lists the findings of every connected repository (IDs like DPDP-014), with status tabs and counts, a repository filter, search, a detail drawer (reason, law, masked evidence, recommended fix, timeline), a health pill per repository (reasons on hover and for screen readers) and a red banner when the latest scan of a repository is incomplete or failed. It polls the engine every 5 seconds (no websockets), so a status changed in Slack shows up here without a reload, and the other way round. In live mode it shows engine data only; sample mode shows the sample scan, read only, labelled SAMPLE. The Findings view gets the same red banner when its scan has `complete: false`.

To change a status or run a fix from the page, give the dashboard the engine's token when you start it: `VITE_DPDP_TOKEN=<same value as DPDP_API_TOKEN> npm run dev`. **Demo only:** a `VITE_` variable is bundled into the page, so it is not a secret. This is acceptable because the engine and the dashboard bind to localhost. Without it the Feed is read only and says so.

Health is "unknown" whenever the latest scan is incomplete or failed, never green. For health, "blocking" means a critical or high finding (`BLOCKING` in `engine/dpdp_lens/ingest.py`); health does not read the policy file, `ci` does.

## Slack bot

The Slack bot is a separate process (`python -m dpdp_lens.slackbot`, started from `engine/`) built on slack-bolt in Socket Mode, so it needs no public URL. It talks to the engine only through the HTTP API with the `X-DPDP-Token` header. Install it with `pip install -e "engine[slack]"`. Setup steps, the Slack app manifest (paste it under Create New App, From a manifest) and a manual checklist are in [docs/slack-bot.md](docs/slack-bot.md).

Commands: `/dpdp connect owner/repo [branch]`, `/dpdp connect` (no argument: connect through the GitHub App, approvers), `repos` (approvers), `scan`, `status`, `findings [open|all]`, `report [owner/repo]` (approvers), `diff` (latest scan against the baseline), `baseline`, `watch <minutes>|off`, `help`. `/dpdp findings` answers ephemerally with interactive rows, critical first, paged in messages of at most 50 blocks so nothing is dropped; each row has View Details, Change Status and, for approvers on repos in `DPDP_FIX_REPOS`, Fix and verify. Ids on cards and rows are plain text. Each finding also gets one card with View Details, Change Status and, for repos in `DPDP_FIX_REPOS`, Fix and verify. "VERIFIED" is shown only when the engine returns `verified: true`, and a cached replay is labelled as one. An incomplete scan starts with "Scan incomplete: results are partial", a scan with no result says "Scan failed", and health reads Unknown in both cases, never green. `/dpdp report` replies (ephemeral) with a signed 15 minute link to the readiness report and a one line summary.

| Env var (bot) | Meaning |
|---------------|---------|
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | `xoxb-...` bot token and `xapp-...` app-level token (scope `connections:write`). Required. |
| `DPDP_API_TOKEN` | Same value as the engine's. Required. |
| `SLACK_CHANNEL` | Channel id that accepts commands and gets scheduled alerts. Required unless `SLACK_ALLOWED_CHANNELS` is set. |
| `SLACK_ALLOWED_CHANNELS` | Comma separated channel ids that accept commands (replaces `SLACK_CHANNEL` for that purpose). |
| `SLACK_APPROVERS` | Comma separated Slack member ids who may change a status, run a fix, set a baseline or schedule scans. Empty: nobody. |
| `DPDP_FIX_REPOS` | Which repos get a Fix and verify button (the engine enforces it too). |
| `DPDP_ALLOW_PR` | Default off. `1` lets an approver open a pull request with a verified fix, only for repos in `DPDP_FIX_REPOS` that are connected through the GitHub App. |
| `GITHUB_APP_ID` | The GitHub App id (a number). With the next two, `/dpdp connect` with no argument installs the app and lists the shared repos. All three or the app flow is off. |
| `GITHUB_APP_SLUG` | The app's slug (the last part of `github.com/apps/<slug>`), used for the install link. |
| `GITHUB_APP_PRIVATE_KEY_PATH` | Path of the app's `.pem` file (mode 600, never in the repo). The engine reads it only to sign a short lived JWT. |
| `ENGINE_URL`, `DASHBOARD_URL` | Defaults `http://127.0.0.1:8100` and `http://localhost:5174`. |

Limits:
- Socket Mode only, one workspace, one bot process. Commands work only in the allowed channels.
- Only approvers can change a status, fix, set a baseline or schedule scans. Anyone in an allowed channel can read details.
- Connected repos get the static checks only (16 of 26), so the coverage line reads "static checks only (n of 26)".
- The "already alerted" memory is in the bot process: after a restart, a repo that is still unhealthy can get one more alert.
- The outbox poller starts at the end of the outbox, so status changes made while the bot was down are not replayed to Slack (the next change refreshes the card).
- Tokens come from the environment only and are removed from every log line and every error shown in Slack. Cards and replies hold masked evidence only.

## GitHub App, readiness report and pull requests

**GitHub App.** Instead of one fixed repo, `/dpdp connect` with no argument shows a Connect GitHub button. You install the app on your account, pick repositories, and a dropdown in Slack lists the shared ones. The old path (`DPDP_ALLOWED_REPOS` plus `GITHUB_TOKEN`, and `/dpdp connect owner/repo`) keeps working. Setup, permissions and limits: [docs/github-app-setup.md](docs/github-app-setup.md). Scans and clones use a read-only installation token. Limits: single tenant, no webhooks, no OAuth user login, a connected repo gets the static checks only, and a fix runs only for repos in `DPDP_FIX_REPOS`.

**Readiness report.** `GET /repos/{id}/report` (HTML to print, or `?format=json`) is titled "DPDP readiness report": scope (which of the 26 checks ran and why others did not), health, findings with clause references and masked evidence, fix results, the audit chain check and a limits section. An incomplete scan or Unknown health is said in the first lines. A browser opens it through a signed 15 minute link (`POST /repos/{id}/report-link`), from `/dpdp report` in Slack or the Report button in the Feed. Details: [docs/readiness-report.md](docs/readiness-report.md).

**Open pull request (off by default).** With `DPDP_ALLOW_PR=1`, an approver can click Open pull request after a live VERIFIED fix of a repo in `DPDP_FIX_REPOS` that is connected through the GitHub App. The engine pushes a new branch `dpdp-lens/fix-<id>-<sha7>` from the scanned commit and opens a pull request; it never merges, never touches the default branch, never force-pushes. It uses a separate installation token limited to that one repository (Contents and Pull requests write) that is never used for scans. The app needs those two write permissions for this only. Limits: one pull request per finding, live verified fixes only (a cached replay is refused), the finding stays Fixed and is resolved only by a later scan of the merged code, and the store is at schema version 4. Details: [docs/github-app-setup.md](docs/github-app-setup.md).

## Limits (what it does NOT do)

- It is a readiness report, **never a compliance certificate**. A clean scan does not mean compliance.
- A scanner that fails, times out or hits a limit is reported in `scan_errors` and sets `complete: false`; the score of such a scan is not a clean result. A file over 1 MB is skipped and recorded (the scanner still returns findings from its other files, but its checks are then not counted as run in `coverage`); more than 5000 files stops that scanner. Lockfiles, `*.min.js`, `*.map` and build folders are skipped silently. The Feed and the Findings view of the dashboard show a red banner for it.
- When two findings in one scan share a fingerprint, the second gets an occurrence number, so fixing the first can make the second look new.
- Localhost and private-IP targets only. Scan only apps you own.
- A small subset of DPDP duties is checked. Not detected yet: the `age` field in notice drift. JavaScript and TypeScript source is scanned for vendor token shapes only (AWS, GitHub, Slack, Stripe), not for secrets by key name. Its log calls are read by a tokenizer, not a parser, so a regex literal with a quote in it can confuse it. Consent kept outside the scanned source cannot be seen.
- Only a FastAPI + SQLite target is tested. Finished scans and fix results are saved as JSON in `.dpdp-state/` (git-ignored, `DPDP_STATE_DIR` overrides) and reloaded when the engine restarts. A scan that is still running when the engine stops is lost.
- No authentication on the legacy scan routes (`POST /scan`, fix, report). The repo, finding and audit routes above need the `X-DPDP-Token` header for every change. See [docs/threat-model.md](docs/threat-model.md).
- Connected repos: only repos in `DPDP_ALLOWED_REPOS` can be connected (empty means none), and they get the static checks only (16 of 26, no live probes). Only repos in `DPDP_FIX_REPOS` get a live fix, because the fix runs that repo's own `seed.py`, app and tests.
- Live Fix and verify can show a CACHED label: when the checkout or the sandbox fails, the engine replays a saved verified result for that fix and says so. A replay is not proof for the current state of the repo.
- `VITE_DPDP_TOKEN` is bundled into the dashboard page. It is for the localhost demo only, not a secret.
- The precision and recall numbers are measured on our own 152 case corpus, not a real-world benchmark.
- Fix proposals are verified in a sandbox copy. The repository is unchanged unless an approver opens a pull request, and then a person must still review and merge it.
- The audit hash chain is tamper-evident, not tamper-proof.
- A static scan of a connected repo runs only the file-based checks (16 of 26). The 10 checks that need a running app (API, database, browser, notice) run only against the demo app.
- The CI check has run for real on GitHub against `Tanish18906/acme-tutornest`: it fails a pull request that adds a new leak and passes with the baseline of the 11 accepted findings. The example workflow installs the engine from the `evolve` branch of this repo (`DPDP_LENS_REF`) until it is pinned to a commit.
- The audit log is tamper-evident, not tamper-proof: every event holds the hash of the one before, so an edited or deleted event is detected by `GET /audit/verify`, but anyone who can write the database file can rewrite the whole chain or cut events off the end.

## Safe use

Use only on your own apps. Use synthetic data. Treat reports as sensitive. Never run on production. The demo app TutorNest is deliberately vulnerable: run it on localhost only, never deploy it. All demo data is synthetic (fake names, phones, PAN and Aadhaar numbers that pass the Verhoeff check). Evidence never stores raw PII.

## AI tools used

- **Claude (chat):** planning, and writing the prompts and briefs for the other tools.
- **Claude Code (Claude models):** writing and testing the code: the engine and scanners, the fix templates and verification, the Slack bot, the dashboard, CI, the GitHub App flow, the readiness report, and the docs.
- **Antigravity:** creating the repositories, the CI wiring, bringing up the local stack, the target app and its tests, the dashboard scaffold, and the cloud configuration checks (Terraform and Kubernetes), as also recorded in `AGENTS.md`, `GEMINI.md` and `docs/14-git-rules.md`.

Dates, from `git log`: the first commit is "Initial commit" on 22 Nov 2026 22:23 IST, and every commit is dated 22 to 24 Nov 2026. The log does not record when hacking began. Both team members can explain every file.

## Contract schema

`contract/finding.schema.json` is generated from the Pydantic models. To regenerate after changing `engine/dpdp_lens/models.py`:

    cd engine && python -c "import json; from dpdp_lens.models import ScanResult; open('../contract/finding.schema.json','w').write(json.dumps(ScanResult.model_json_schema(), indent=2)+'\n')"

## Credits and licences

| Component | Licence |
|-----------|---------|
| Disconnect `services.json` (tracker classification), https://github.com/disconnectme/disconnect-tracking-protection | CC BY-NC-SA 4.0, Copyright 2010-2026 Disconnect, Inc. |
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| HTTPX | BSD-3-Clause |
| python-stdnum | LGPL-2.1-or-later |
| Pydantic | MIT |
| PyJWT (the GitHub App JWT) | MIT |
| cryptography (RS256 signing for the GitHub App) | Apache-2.0 or BSD-3-Clause |
| PyYAML | MIT |
| jsonschema | MIT |
| pytest | MIT |
| rich | MIT |
| prompt_toolkit | BSD-3-Clause |
| Playwright for Python | Apache-2.0 |
| slack-bolt, slack-sdk (Slack bot, optional extra `slack`) | MIT |
| SARIF 2.1.0 JSON schema from the OASIS SARIF Technical Committee (https://github.com/oasis-tcs/sarif-spec), vendored in `engine/tests/fixtures/` for the tests | see that repo's LICENSE.md |
| React, React DOM | MIT |
| Vite, `@vitejs/plugin-react` | MIT |
| Tailwind CSS, `@tailwindcss/vite` | MIT |
| oxlint | MIT |
| Newsreader, IBM Plex Sans, IBM Plex Mono fonts (bundled with the dashboard through `@fontsource/newsreader`, `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono`) | SIL Open Font License 1.1 |

## Team

Tanish (engine, contract, docs) and Anmol (target app frontend, dashboard, tests).
