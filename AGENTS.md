# AGENTS.md  (read this first, every session)

**GIT: read docs/14-git-rules.md (once the first question below is answered). It overrides everything else on git.**

## 0. FIRST ACTION. DO THIS BEFORE ANYTHING ELSE.

Do not read other files, write files, install anything, download anything or run any command yet.
Your first message must be exactly this question and nothing else:

    Who is running you: Tanish or Anmol?

Wait for the answer. Then:
1. If Tanish: follow section 8 (ENGINE). You are the engine builder. Also follow sections 1 to 7 and 10 to 12.
2. If Anmol: follow section 9 (TARGET APP + DASHBOARD). Also follow sections 1 to 7 and 10 to 12.
3. Ask one more question: "Which OS and which Python and Node versions do you have?" Adapt the setup commands to the answer. Tanish is on Ubuntu with 8 GB RAM. Anmol's machine is unknown.
4. Then show the setup commands for that person and ask: "OK to run these?" Wait for yes.

## ASK-BEFORE RULES (always apply)
Ask the human and wait for yes before you:
- install or download anything (pip, npm, playwright, curl, git clone)
- delete or overwrite any file
- run git push, git rebase, git reset, or anything with --force
- touch any file outside your own folders (section 3)
- change contract/ (only Tanish owns it, and he tells Anmol when it changes)
- start any server or scan

Work in small steps. For every step: say what you are about to do in two lines, ask "go?", do it, show a short result, then stop at any line marked STOP and wait. Never run ahead to the next step on your own. Keep replies short and plain.

---

## 1. The project

Team of two (Tanish and Anmol) at Hack-a-Sol 5.0, IIIT Naya Raipur, Cyber track. Problem statement title only: "CS-01 Full-Stack Data Protection (DPDP) Compliance Auditor". We have only the title, no description.

Product (working name DPDP Lens): a cross-layer readiness auditor for India's DPDP Act 2023 and DPDP Rules 2025. It scans a running app across four layers (database, backend code, running API, browser), produces evidence-backed findings mapped to Act sections and Rules, then proves a fix: patch a COPY of the app, re-run the failed check, run the app's tests, show the diff and the score change. The audit is the product, the verified fix is the proof.

Headline extension: "Notice vs Runtime Truth" drift detector. It compares the personal data fields the public privacy notice lists against the fields actually found in the DB, in API responses and in third-party requests.

It is a readiness report, never a compliance certificate. Main DPDP duties apply from 13 May 2027.

Market reality: dcomply, Privado and several Indian consent SaaS tools exist. Never claim "nobody scans code". Our edge is cross-layer proof plus verified fixes.

Judging weights: Innovation 25, Technical execution 25, Impact 20, Track fit 15, Presentation 15.

## 2. Hard rules

- All code is written during the hackathon. Commit small and often. Both humans must be able to explain every file.
- AI tools used (Claude Code, Antigravity) are declared in README.md. Every library and data file is credited in README.md with its licence.
- Everything runs on localhost. Scan only our own demo app. Non-destructive requests only.
- ALL demo data is SYNTHETIC. Fake names, fake phones, fake PAN, fake Aadhaar numbers generated to pass the Verhoeff check. Never use real personal data, never real people.
- Evidence never stores raw PII. Mask it (Aadhaar XXXX XXXX 1234, email a***@x.com, phone 98XXXXXX10).
- Never patch the original target app folder. Patch a temp copy only.
- Keep it simple. Do not add features that are not in this file without asking.

## 3. Repo layout, ports, ownership

Public GitHub repo: dpdp-lens. One repo, separate folders so we never edit the same file.

    contract/        finding.schema.json, sample-scan.json, clauses.json      OWNER: Tanish
    engine/          Python package dpdp_lens, tests/, pyproject.toml         OWNER: Tanish
    target-app/
      backend/       FastAPI + SQLite demo app "TutorNest"                    OWNER: Tanish for V1 to V4 (phase T1), Anmol edits only V7 and V8 (phase A6)
      frontend/      Vite React signup page                                    OWNER: Anmol
      tests/         pytest tests for the target app                           OWNER: Anmol
    dashboard/       Vite React + Tailwind dashboard                           OWNER: Anmol
    docs/            threat-model.md, demo-script.md                           OWNER: Tanish
    README.md                                                                  OWNER: Tanish
    AGENTS.md        this file (also copied to CLAUDE.md and GEMINI.md)

Ports: target backend 8000, target frontend 5173, engine API 8100, dashboard 5174.

## 4. Scan result JSON (the ONLY interface between engine and dashboard)

    {
      "scan_id": "S-001",
      "target": "http://localhost:8000",
      "scanned_at": "ISO8601",
      "score": 0-100,
      "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
      "findings": [
        {
          "id": "F-001",
          "check": "api_pii_exposure",
          "layer": "db|code|api|browser|notice",
          "severity": "critical|high|medium|low",
          "title": "short title",
          "explanation": "plain English, 2 sentences",
          "clauses": [{"ref": "Act s8(5)", "note": "reasonable security safeguards"},
                      {"ref": "Rule 6(1)(b)", "note": "access control"}],
          "evidence": {
            "kind": "http|db|code|network|dom",
            "summary": "what was observed",
            "masked_sample": "masked value only",
            "location": {"file": "", "line": 0, "url": "", "table": "", "column": ""}
          },
          "status": "open|verified_fixed",
          "fix": {"available": true, "diff": "unified diff or null", "verified": false,
                  "rescan_passed": null, "tests_passed": null,
                  "score_before": null, "score_after": null}
        }
      ],
      "notice_drift": {
        "declared": ["name", "email", "phone"],
        "observed": [{"field": "aadhaar", "where": ["db:students.aadhaar", "api:/api/students", "request:facebook.com"]}],
        "undeclared": ["dob", "aadhaar", "parent_pan"]
      }
    }

Score = 100 minus weights (critical 20, high 10, medium 5, low 2), floor at 0.
The dashboard builds against contract/sample-scan.json and never waits for the engine.

## 5. Engine API (FastAPI, port 8100, CORS open for localhost)

- POST /scan with {target_url, repo_path, db_path} returns {scan_id}
- GET /scan/{id} returns the JSON above
- POST /findings/{id}/fix runs fix-and-verify, returns the updated finding and new score
- GET /report/{scan_id} returns an HTML report
- CLI: python -m dpdp_lens scan --target http://localhost:8000 --repo target-app/backend --db target-app/backend/demo.db --out scan.json

## 6. Verified clause map (checked against the Act and Rules text. Use only these.)

- Act s5 notice. Rule 3: notice stands alone, plain language, itemises the personal data and specific purposes, links to withdraw consent, exercise rights, complain to the Board.
- Act s6(1) consent free, specific, informed, unambiguous, clear affirmative action. s6(4) withdrawal as easy as giving. s6(6) stop processing after withdrawal. s6(10) fiduciary must prove notice and consent.
- Act s8(1) fiduciary stays responsible even for its processors. s8(2) processors only under a valid contract. s8(5) reasonable security safeguards. s8(6) breach notice to Board and each affected person. s8(7) erase when consent is withdrawn or purpose is served. s8(9) publish contact of DPO or other person. s8(10) grievance mechanism. s2(u) defines personal data breach.
- Rule 6(1): (a) encryption, obfuscation, masking or virtual tokens, (b) access control, (c) logs, monitoring and review, (d) backups and continuity, (e) retain logs and personal data 1 year, (f) processor contract security terms, (g) effective technical and organisational measures.
- Rule 7 breach: notify each affected person promptly (what happened, consequences, mitigation, protective steps, business contact). Notify the Board without delay and give a detailed report within 72 hours.
- Rule 8(3): keep personal data, traffic data and logs at least 1 year, then erase unless law requires more. Rule 8(1) and 8(2) (erasure after inactivity with 48 hours notice) apply ONLY to e-commerce and social media with 2 crore or more users and online gaming with 50 lakh or more. DO NOT flag Rule 8(1) or 8(2) for a small app.
- Rule 9 publish business contact. Rule 14(1) publish how to make a rights request. Rule 14(3) publish grievance process, respond within 90 days at most. Rule 14(4) nomination.
- Act s9(1) verifiable parental consent for under 18. s9(3) no tracking, behavioural monitoring or targeted ads aimed at children. Rule 10 verify the parent is an identifiable adult. Rule 12 and Fourth Schedule exempt some classes (educational institutions only for tracking and behavioural monitoring tied to educational activities or enrolled child safety). So the planted tracker must be a marketing or ad pixel, not learning analytics.
- Act s17(3): government MAY notify startups as exempt from s5, s8(3), s8(7), s10, s11. No such notification found. s8(5) is never exempted under s17(1).
- Penalties (Act Schedule): s8(5) up to Rs 250 crore. s8(6) and s9 up to Rs 200 crore. Other provisions up to Rs 50 crore.
- Main duties (Rules 3, 5 to 16, 22, 23) apply from 13 May 2027.
- Unverified, do not cite: online gaming erasure period, Seventh Schedule purposes.

contract/clauses.json maps each check id to its clause list from above.

## 7. The 8 planted violations (the target app contains exactly these plus a missing DPO contact)

- V1 GET /api/students needs no login and returns name, phone, dob, aadhaar, parent_pan. [Act s8(5), Rule 6(1)(b)] critical. VERIFIED FIX 1.
- V2 GET /api/students/{id} works for any logged in user (IDOR). [Act s8(5), Rule 6(1)(b)] critical.
- V3 Signup logs email and aadhaar in plaintext via logger.info. [Act s8(5), Rule 6(1)(a)] high. VERIFIED FIX 2.
- V4 Aadhaar and parent PAN stored in plaintext columns. [Act s8(5), Rule 6(1)(a)] high.
- V5 Facebook pixel script loads on the signup page before any consent click. [Act s6(1), s9(3)] high. VERIFIED FIX 3.
- V6 Consent box is pre ticked and bundled into T&C. The notice does not itemise data. [Act s5, s6(1), Rule 3] medium.
- V7 DELETE /api/students/{id} only sets is_deleted=1. PII stays in students and a students_backup table. [Act s8(7), s12] high.
- V8 Signup accepts age 14 with no parental verification. [Act s9(1), Rule 10] high.
- Extra: no DPO or grievance contact on the site. [Act s8(9), s8(10), Rule 9, Rule 14(3)] low.
- Notice drift: the public notice lists name, email, phone only. The app also collects dob, aadhaar, parent_pan and sends data to facebook.com.

Each violation lives in a small, obvious place in the code so the engine's fix templates can patch it cleanly.

---

## 8. TANISH: ENGINE (Claude Code)

Engine = Python 3.12 package dpdp_lens + FastAPI wrapper + CLI. Machine is Ubuntu, 8 GB RAM. NO Presidio, NO spaCy, NO torch.

### 8a. Setup commands (show them, ask "OK to run these?", then run)

    cd dpdp-lens
    python3 -m venv .venv && source .venv/bin/activate
    pip install fastapi "uvicorn[standard]" httpx python-stdnum pydantic pytest playwright
    playwright install chromium
    pip install semgrep          # optional and heavy. If it fails or is slow, skip it. The fallback is Python ast.
    mkdir -p engine/dpdp_lens/data
    # Disconnect services.json (tracker classification, licence CC BY-NC-SA, credit it in README):
    curl -L -o engine/dpdp_lens/data/services.json \
      https://raw.githubusercontent.com/disconnectme/disconnect-tracking-protection/master/services.json
    # If that URL fails, ask the human for the right one. Do not invent a different source.

Pre-download everything now. Wi-Fi at the venue is shared and slow. Keep a phone hotspot ready for any LLM API calls.

### 8b. Steps

Follow the phases in docs/13-work-split.md. That file is the single source of truth for steps.

### 8c. Milestones

See docs/10-implementation-plan.md. Freeze Tue 00:30, submit target 04:00, hard limit 06:30.

### 8d. Cut order if behind
SARIF, then children signup check, then drift detector, then browser scan. Never cut the fix and verify loop.

---

## 9. ANMOL: TARGET APP + DASHBOARD (Antigravity)

### 9a. Setup commands (show them, ask "OK to run these?", then run)

First ask which OS Anmol is on and adapt (Windows users: use PowerShell equivalents, activate venv with .venv\Scripts\activate).

    cd dpdp-lens
    python -m venv .venv && source .venv/bin/activate
    pip install fastapi "uvicorn[standard]" pyjwt python-stdnum pytest httpx
    # frontend (needs Node 20 or newer)
    cd target-app && npm create vite@latest frontend -- --template react && cd frontend && npm install && cd ../..
    npm create vite@latest dashboard -- --template react
    cd dashboard && npm install && npm install -D tailwindcss @tailwindcss/vite && cd ..

Pre-download everything now. Venue Wi-Fi is shared and slow.

### 9b. Steps

Follow the phases in docs/13-work-split.md. That file is the single source of truth for steps.

### 9c. Rules for Anmol
- Do not edit engine/ or contract/. If you need a schema change, tell Tanish and wait.
- The target app is deliberately vulnerable. It must only ever run on localhost. Never deploy it publicly.

---

## 10. Git workflow

- Both commit to main, in their own folders only.
- Before every push: git pull --rebase origin main. Resolve conflicts by asking the human.
- Small commits, plain messages: "add api_scan", "plant V3 log leak".
- Do not commit .venv, node_modules, *.db with real data (our demo.db is synthetic, it is fine), or any secrets or API keys.

## 11. Demo facts to keep in mind while building

- Live demo is mandatory. The story: scan the app, show the findings with clauses, click Fix on V1, see the diff, the re-scan pass, the tests pass and the score jump. Then show the drift panel.
- Everything on the demo path needs a fallback that works offline.
- Cached golden patch mode must be clearly labelled in the UI.

## 12. If stuck

If something fails twice, stop, show the exact error to the human and ask. Do not silently work around a problem by changing the contract, skipping tests, or switching libraries.
