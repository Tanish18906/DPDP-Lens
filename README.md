# DPDP-Lens

DPDP Lens is a cross-layer readiness auditor for India's Digital Personal Data Protection Act 2023 and DPDP Rules 2025. It scans a running app across four layers (database, backend code, running API, browser) and produces evidence-backed findings mapped to Act sections and Rules. It then proves a fix: it patches a copy of the app, re-runs the failed check, runs the app's tests, and shows the diff and the score change. A "Notice vs Runtime Truth" drift detector compares the personal data fields the public privacy notice lists against the fields actually found in the database, API responses and third-party requests.

It is a readiness report, never a compliance certificate. The main DPDP duties apply from 13 May 2027.

Built at Hack-a-Sol 5.0, IIIT Naya Raipur, Cyber track (CS-01 Full-Stack Data Protection (DPDP) Compliance Auditor). Everything runs on localhost against our own synthetic demo app. All demo data is fake.

## Quick start (localhost only)

    python3 -m venv .venv && source .venv/bin/activate
    pip install fastapi "uvicorn[standard]" httpx python-stdnum pydantic pyjwt pytest playwright

    # 1. Target app (deliberately vulnerable, synthetic data). demo.db is generated, not committed.
    cd target-app/backend
    python seed.py                                    # creates demo.db, run it before starting the backend
    uvicorn app.main:app --host 127.0.0.1 --port 8000

    # 2. Scan it (new terminal, repo root)
    cd engine && python -m dpdp_lens scan --target http://localhost:8000 \
      --repo ../target-app/backend --db ../target-app/backend/demo.db --out scan.json

    # 3. Engine API for the dashboard (port 8100)
    cd engine && python -m uvicorn dpdp_lens.api:app --host 127.0.0.1 --port 8100

The erasure check signs up and deletes a synthetic user, so a live scan writes to `demo.db`. Run `python seed.py` again to reset it.

## AI tools used

Claude Code and Antigravity. Both team members can explain every file.

## Contract schema

`contract/finding.schema.json` is generated from the Pydantic models. To regenerate after changing `engine/dpdp_lens/models.py`:

    cd engine && python -c "import json; from dpdp_lens.models import ScanResult; open('../contract/finding.schema.json','w').write(json.dumps(ScanResult.model_json_schema(), indent=2)+'\n')"

## Credits

| Component | Licence |
|-----------|---------|
| Disconnect `services.json` (tracker classification), https://github.com/disconnectme/disconnect-tracking-protection | CC BY-NC-SA 4.0, Copyright 2010-2026 Disconnect, Inc. |
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| HTTPX | BSD-3-Clause |
| python-stdnum | LGPL-2.1-or-later |
| Pydantic | MIT |
| pytest | MIT |
| Playwright for Python | Apache-2.0 |
| Semgrep (optional) | LGPL-2.1 |

More credits are added as libraries and data files join the project.
