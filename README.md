# DPDP Lens

**Does your app do what your privacy notice says?** DPDP Lens is a cross-layer readiness auditor for India's Digital Personal Data Protection Act 2023 and DPDP Rules 2025. It scans a running app across four layers (database, backend code, running API, browser), produces evidence-backed findings mapped to Act sections and Rules, then proves a fix: it patches a COPY of the app, re-runs the failed check, runs the app's tests, and shows the diff and the score change.

Built at Hack-a-Sol 5.0, IIIT Naya Raipur, Cyber track (CS-01 Full-Stack Data Protection (DPDP) Compliance Auditor). Everything runs on localhost against our own synthetic demo app.

## The problem

The main DPDP duties apply from **13 May 2027**. Under the Act's Schedule, failing to keep reasonable security safeguards (s8(5)) can cost up to Rs 250 crore, and most startups have no privacy team. Existing tools (dcomply, Privado, Indian consent SaaS) each cover part of the problem. Our edge is cross-layer proof plus verified fixes, not "nobody scans code".

## What it does

- **Four layers, one report.** Database, backend code, running API and browser are scanned together. Each finding has masked evidence and the Act section or Rule it relates to.
- **Verified fix.** Fixes are applied to a temp copy of the app, never the original. A fix counts as `verified` only when the re-scan no longer finds the issue AND the app's tests pass. The status is computed, never set by hand.
- **Notice vs Runtime Truth.** Compares the personal data fields the public notice lists against the fields found in the DB and in unauthenticated API responses. Fields collected but not declared are flagged.
- **HTML report.** `GET /report/{scan_id}` gives a self-contained, printable report.

Fixes exist for three findings: `api_pii_exposure` (V1), `log_pii` (V3) and `tracker_before_consent` (V5). Each has a cached golden result for offline demos. The dashboard labels it clearly as "Cached golden patch mode" when it is used.

## Architecture

    Dashboard (React, :5174) --> Engine API (FastAPI, :8100) --> Target app TutorNest (:8000, frontend :5173)
                                       |--> scanners: db, code, api, browser, notice
                                       '--> fix sandbox: temp copy of the app, patch, re-scan, pytest

The only interface between engine and dashboard is the scan JSON (`contract/finding.schema.json`, example in `contract/sample-scan.json`).

## Quick start (localhost only)

One-time setup (Python 3.12, Node 20 or newer):

    python3 -m venv .venv && source .venv/bin/activate
    pip install fastapi "uvicorn[standard]" httpx python-stdnum pydantic pyjwt pytest jsonschema playwright
    playwright install chromium    # or have Google Chrome installed, the browser scan falls back to it
    (cd target-app/frontend && npm install)
    (cd dashboard && npm install)

Then start everything:

    ./run_demo.sh

It re-seeds the synthetic `demo.db`, starts the target backend (:8000), the target frontend (:5173), the engine API (:8100) and the dashboard (:5174), and stops them all on Ctrl-C. Open http://localhost:5174 and click scan. It refuses to start if one of those ports is busy.

The erasure and children checks sign up synthetic users and remove their own rows, so a live scan still writes to `demo.db` briefly. `run_demo.sh` re-seeds it on every start.

CLI scan (backend must be running):

    cd engine && ../.venv/bin/python -m dpdp_lens scan --target http://localhost:8000 \
      --repo ../target-app/backend --db ../target-app/backend/demo.db --out scan.json

Tests:

    cd engine && ../.venv/bin/python -m pytest

## Checks

Severity and clauses come from `contract/clauses.json` (checked against the Act and Rules text).

| Check id | Layer | Severity | Clauses | What it detects | Verified fix |
|----------|-------|----------|---------|-----------------|--------------|
| `api_pii_exposure` | api | critical | Act s8(5), Rule 6(1)(b) | Unauthenticated GET returns PII fields | yes |
| `api_idor` | api | critical | Act s8(5), Rule 6(1)(b) | One logged-in user reads another's record | no |
| `log_pii` | code | high | Act s8(5), Rule 6(1)(a) | Log call includes a PII variable | yes |
| `db_plaintext_pii` | db | high | Act s8(5), Rule 6(1)(a) | Aadhaar or PAN stored in plaintext columns | no |
| `tracker_before_consent` | browser | high | Act s6(1), s9(3) | Third-party tracker request before any consent click | yes |
| `consent_bundled` | browser | medium | Act s5, s6(1), Rule 3 | Pre-ticked or bundled consent, notice does not itemise data | no |
| `erasure_incomplete` | db | high | Act s8(7) | PII remains after a delete | no |
| `children_no_parental_consent` | api | high | Act s9(1), Rule 10 | Signup of a 14 year old accepted with no parental consent step | no |
| `missing_contact` | notice | low | Act s8(9), s8(10), Rule 9, Rule 14(3) | No DPO or grievance contact | no |
| `notice_drift` | notice | medium | Act s5, Rule 3 | Collected fields not declared in the notice | no |

Score = 100 minus weights (critical 20, high 10, medium 5, low 2), floor 0, open findings only.

## What it does NOT do

- It is a readiness report, **never a compliance certificate**. A clean scan does not mean compliance.
- Localhost and private-IP targets only. Scan only apps you own.
- A small subset of DPDP duties is checked. Not detected yet: the `age` field in notice drift.
- Only a FastAPI + SQLite target is tested. Scans and fix results live in memory and are lost when the engine restarts.
- No authentication on the engine API. See [docs/threat-model.md](docs/threat-model.md).

## Safe use

Use only on your own apps. Use synthetic data. Treat reports as sensitive. Never run on production. The demo app TutorNest is deliberately vulnerable: run it on localhost only, never deploy it. All demo data is synthetic (fake names, phones, PAN and Aadhaar numbers that pass the Verhoeff check). Evidence never stores raw PII.

## AI tools used

Claude Code (engine, docs, dashboard wiring) and Antigravity (target app, dashboard scaffold, target app tests). All code was written during the hackathon. Both team members can explain every file.

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
| PyJWT | MIT |
| jsonschema | MIT |
| pytest | MIT |
| Playwright for Python | Apache-2.0 |
| React, React DOM | MIT |
| Vite, `@vitejs/plugin-react` | MIT |
| Tailwind CSS, `@tailwindcss/vite` | MIT |
| oxlint | MIT |

## Team

Tanish (engine, contract, docs) and Anmol (target app frontend, dashboard, tests).
