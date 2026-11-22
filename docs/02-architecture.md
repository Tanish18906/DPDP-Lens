# 02 Architecture

## Components

    +--------------------+        HTTP         +----------------------+
    | Dashboard (React)  | <-----------------> | Engine API (FastAPI) |
    | port 5174          |   scan JSON, fix    | port 8100            |
    +--------------------+                     +----------+-----------+
                                                          |
                         +--------------------------------+------------------------------+
                         |                |                |               |             |
                   api_scan /        db_scan        log_scan        browser_scan    fix loop
                   idor_probe     (read only      (semgrep or      (Playwright)    (sandbox copy)
                         |          sqlite3)         ast)               |              |
                         v                |                |               v              v
                +-----------------------------------------------------------------------------+
                |  Target app "TutorNest" (deliberately vulnerable, localhost only)           |
                |  backend FastAPI + SQLite :8000     frontend Vite React :5173                |
                +-----------------------------------------------------------------------------+

## Data flow of one scan
1. Dashboard or CLI sends target_url, repo_path, db_path to the engine.
2. The runner executes the scanners one by one. Each scanner returns zero or more Finding objects.
3. Each Finding gets its clause list from contract/clauses.json by check id.
4. The runner computes the score from open findings and builds notice_drift.
5. The ScanResult JSON is stored in memory and in a file, and returned to the caller.
6. For a fix: the engine copies the target to a temp dir, patches the copy, starts it on a free port, re-runs the failed check, runs pytest, builds a diff, updates the finding and the score.

## Layers and what reads them
| Layer | What we look at | How | Reads |
|-------|-----------------|-----|-------|
| db | plaintext PII columns, leftover PII after delete | read only sqlite3 | demo.db |
| code | PII in log calls, planted source patterns | semgrep rule or Python ast | repo folder |
| api | unauthenticated PII, IDOR | httpx using /openapi.json | running backend |
| browser | trackers before consent, pre ticked box, notice text, contact | Playwright | running frontend |
| notice | declared vs observed fields, missing contact | text extraction plus comparison | notice page, other layers |

## Tech choices and why
- Python 3.12, FastAPI, httpx, python-stdnum, pydantic, pytest, playwright, semgrep CE (optional, ast fallback).
- No Presidio, no spaCy, no torch. The dev laptop has 8 GB RAM. We use regex, Verhoeff checksum and column name context.
- Playwright uses bundled Chromium, falls back to channel="chrome" (system Chrome).
- Tracker classification: Disconnect services.json (CC BY-NC-SA, credit in README).
- Dashboard: React + Vite + Tailwind. No router, no state library.
- Everything is local. No cloud calls are required for a scan or a fix. An LLM may only be used to explain a fix. It is never required.

## Folder layout
    contract/        finding.schema.json, clauses.json, sample-scan.json
    engine/dpdp_lens/ models.py, recognizers.py, runner.py, api.py, report.py,
                      scanners/, fixer/, data/services.json
    engine/tests/
    target-app/backend, frontend, tests
    dashboard/
    docs/

## Ports
target backend 8000, target frontend 5173, engine API 8100, dashboard 5174. Patched sandbox copies use a random free port.

## Key design rules
1. One interface between engine and dashboard: the scan JSON. Neither side reads the other's code.
2. Evidence is always masked. The auditor must not leak PII itself.
3. Never patch the original target folder.
4. Scanners are independent. One scanner crashing must not kill the scan: catch, record a "scanner_error" note, continue.
5. Every scanner has a hard timeout (30 seconds).
6. Deterministic output: same target gives the same findings and ids (ids assigned in a fixed order).

## Failure and fallback
| Failure | Fallback |
|---------|----------|
| No Wi-Fi at demo | everything is local, no change |
| Chromium missing | use system Chrome channel |
| semgrep fails | Python ast rule |
| Engine slow or crashing live | cached golden scan JSON plus cached golden patch, clearly labelled in the UI |
| LLM unavailable | not needed, fixes are template based |
