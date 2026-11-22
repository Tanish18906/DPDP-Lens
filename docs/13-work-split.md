# 13 Work split (agents read this right after AGENTS.md)

## FIRST ACTION
If you have not asked yet, ask exactly this and nothing else, then wait:

    Who are you: Tanish or Anmol?

- Tanish: you follow the T phases below. You are the engine builder (Claude Code).
- Anmol: you follow the A phases below. You build the dashboard, tests and demo parts (Antigravity).
Then read docs/00-index.md and the docs it lists for that person, and read docs/STATUS-tanish.md or docs/STATUS-anmol.md to see which phases are already done.

## HOW PHASES WORK (rules for the agent)
1. One phase per session. Do NOT chain phases. Do not start phase N+1 because phase N went well.
2. The human tells you which phase to run ("Start phase T3"). If they did not, show the next unfinished phase from the STATUS file and ask "Start this one?".
3. At the start of a phase: say in 3 lines what you will build, which files you will touch, and the gate (how we know it is done). Ask "go?". Wait.
4. Stay inside the phase. If you find a missing piece that belongs to another phase, write it in the STATUS file under "Notes for later" and keep going. Do not build it.
5. Phases are 30 to 60 minutes. If one is taking more than 90 minutes, stop and tell the human what is blocking it.
6. End of every phase, in this order: run the gate command and the tests, fix failures, commit with a clear message, `git pull --rebase origin main`, push (ask first, as AGENTS.md says), update your STATUS file, then reply with at most 6 lines: what works, the gate result, what is not done, then "Phase X done. Next is phase Y. Say 'next' to start it." STOP.
7. Only edit your own files and folders (AGENTS.md section 3). Never edit the other person's STATUS file.
8. If something fails twice, stop and show the exact error. Do not work around it by changing the contract, skipping tests or switching libraries.
9. Never mark a phase done if its gate has not passed. Say it is not done and why.

## STATUS files
docs/STATUS-tanish.md and docs/STATUS-anmol.md. Each person's agent edits only its own. Format:

    # STATUS (Tanish)
    - [x] T0 contract and skeleton (commit 391aeb2)
    - [ ] T1 ...
    ## Notes for later
    - ...

## Prompt template the human uses
> Start phase T3. Read AGENTS.md and docs/13-work-split.md first. Do only this phase. Stop at the end.

---

## TANISH PHASES (engine, Claude Code)

T0 Contract and skeleton. DONE. (contract files, models, scoring, sample scan, CLI sample, README skeleton)

T1 Target backend V1 to V4 (30 to 40 min)
Build target-app/backend per docs/06. FastAPI + sqlite3, working signup, login, /api/me, admin list, delete, health. Seed 15 synthetic students (4 under 18, Verhoeff valid fake Aadhaar). Plant V1, V2, V3, V4 with `# PLANTED Vn` markers. Logging to a file.
Gate: `python target-app/backend/seed.py` creates demo.db. The app runs on :8000. `curl localhost:8000/api/students` returns records with no login. A signup writes the leaky line into the log file.
Do not write tests or V5 to V8.

T2 Recognizers (30 min)
engine/dpdp_lens/recognizers.py and masking helpers per docs/05, plus tests.
Gate: pytest passes, including the test that a bare 12 digit number with no context is NOT flagged as Aadhaar.

T3 api_scan and idor_probe (40 min)
Per docs/05. Tests start the target on a free port with a fresh seeded DB.
Gate: pytest finds V1 and V2, and does not flag /health.

T4 db_scan and log_scan (40 min)
Per docs/05 (semgrep rule with ast fallback).
Gate: pytest finds V4 and V3, does not flag the password hash or a log line with only a user id.

T5 Runner and CLI scan (30 min)
runner.py: runs scanners in order, catches errors per scanner, assigns ids, attaches clauses, computes score, writes JSON. CLI `scan` command.
Gate: `python -m dpdp_lens scan --target http://localhost:8000 --repo target-app/backend --db target-app/backend/demo.db --out scan.json` writes JSON that validates against contract/finding.schema.json with at least 4 findings. THIS IS THE MID EVAL SLICE.

T6 Engine API (30 min)
api.py on :8100 with /scan, /scan/{id}, /health, CORS for localhost. Fix endpoint can return "not implemented" for now.
Gate: curl POST /scan then GET /scan/{id} returns the same JSON as the CLI.

T7 erasure_scan and contact_scan (30 min)
Per docs/05. Needs V7 and the missing contact from Anmol (A6). If not pushed yet, test against a small fixture and write a note.
Gate: pytest passes.

T8 Browser helper and browser_scan (45 min)
browser.py (bundled Chromium, fallback channel="chrome"), browser_scan with services.json classification. Needs V5 and V6 from Anmol (A5).
Gate: pytest finds tracker_before_consent and consent_bundled.

T9 Fix sandbox (45 min)
fixer/sandbox.py: copytree, copy DB, free port, start and stop the process group, wait for /openapi.json. No patches yet.
Gate: a test starts a sandbox copy of the target and kills it, leaving no process behind.

T10 Fix V1 verified (60 min)
fixer/templates.py V1 template, verify.py (re-scan, pytest against the patched URL, diff, score). Cached golden result for V1. POST /findings/{id}/fix wired.
Gate: V1 fix returns verified true with the diff, and the tests pass on the patched copy. The original app folder is unchanged (git status clean).

T11 Fix V3 verified (30 min). Same pattern as T10.

T12 Fix V5 verified (30 min). Needs A5.

T13 notice_drift scanner (45 min)
Per docs/05. Fills the notice_drift block.
Gate: undeclared equals dob, aadhaar, parent_pan on the target.

T14 HTML report (30 min). /report/{scan_id}.

T15 Docs and submission files (45 min)
README final, threat-model.md final, credits table, run_demo.sh that starts everything.
Gate: a fresh clone follows the README to a running demo.

T16 Stretch, one at a time: SARIF output, children_scan, gitleaks, breach report.

---

## ANMOL PHASES (dashboard, tests, demo parts, Antigravity)

A0 Setup (20 min): clone repo, run the setup commands from AGENTS.md section 9, read docs 07, 08, 09. Gate: `npm run dev` shows the Vite starter on :5174.

A1 Dashboard scaffold (45 min)
Tailwind with the tokens from docs/08, load contract/sample-scan.json, top bar, summary row (score gauge, counts), findings list.
Gate: the list shows the 5 sample findings, critical first.

A2 Finding detail (45 min)
Detail panel: explanation, clause chips with tooltips, evidence block (masked only), layer chip, status.
Gate: clicking each finding shows the right detail, keyboard arrows work.

A3 Fix flow in mock mode (45 min)
Fix and verify button, 5 step progress, diff viewer, three badges, score animation from score_before to score_after, cached mode label.
Gate: the whole fix moment works from sample data and looks right on a projector sized window.

A4 Target app tests (30 min)
target-app/tests per docs/06. Needs Tanish's phase T1 pushed (pull first).
Gate: pytest passes against the running backend, base URL from an env var.

A5 V5, V6 and the notice page (45 min)
Signup frontend on :5173, tracker tag (V5), pre ticked bundled consent (V6), static/notice.html listing only name, email, phone.
Gate: the page loads, the markers `PLANTED V5` and `PLANTED V6` exist, and the tracker request is visible in the browser network tab.

A6 V7, V8 and missing contact (30 min)
Backend edits in target-app/backend limited to V7 (soft delete plus students_backup) and V8 (age 14 accepted). Pull first. Add `# PLANTED V7`, `# PLANTED V8`. Make sure no DPO or grievance contact appears anywhere.
Gate: A4 tests still pass. Tell Tanish when pushed.

A7 Connect to the real engine (30 min). Needs T6.
Set USE_MOCK false, test against :8100, fix field mismatches. If the schema needs to change, message Tanish.
Gate: a real scan from the engine renders in the dashboard.

A8 Notice vs Runtime tab (45 min)
Per docs/07 and 09, with the computed summary line.
Gate: undeclared fields are red and the summary says how many.

A9 Data Flow tab (45 min). Simple SVG per docs/09.

A10 Report print page (30 min)

A11 Deck (60 min), per docs/11, 8 to 10 slides, exported to PDF.

A12 Screenshots and demo video (60 min), after the feature freeze, per docs/11.

A13 Polish (30 min): contrast, focus states, empty and error states, footer disclaimer.

---

## ORDER AND DEPENDENCIES (who waits for whom)
- A4, A5, A6 need T1 pushed.
- T7 needs A6 (V7). T8 and T12 need A5 (V5, V6).
- A7 needs T6.
- Anyone blocked: do the next phase that does not need the other person, and note the block in the STATUS file.

Suggested sequence tonight: Tanish T1, T2, T3, T4, T5. Anmol A0, A1, A2, A3. Then Anmol A4 once T1 is pushed.
