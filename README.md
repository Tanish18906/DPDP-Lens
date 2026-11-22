# DPDP-Lens

DPDP Lens is a cross-layer readiness auditor for India's Digital Personal Data Protection Act 2023 and DPDP Rules 2025. It scans a running app across four layers (database, backend code, running API, browser) and produces evidence-backed findings mapped to Act sections and Rules. It then proves a fix: it patches a copy of the app, re-runs the failed check, runs the app's tests, and shows the diff and the score change. A "Notice vs Runtime Truth" drift detector compares the personal data fields the public privacy notice lists against the fields actually found in the database, API responses and third-party requests.

It is a readiness report, never a compliance certificate. The main DPDP duties apply from 13 May 2027.

Built at Hack-a-Sol 5.0, IIIT Naya Raipur, Cyber track (CS-01 Full-Stack Data Protection (DPDP) Compliance Auditor). Everything runs on localhost against our own synthetic demo app. All demo data is fake.

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
