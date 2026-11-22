# 10 Implementation plan (IST)

Now: Sun 22 Nov, about 23:00. Hacking ends about Tue 24 Nov 08:40 (34h20m were left at 22:21). Mid evaluation: Mon 23 Nov 10:00. Confirm exact times with the organisers.

AGENTS.md used Tue 02:00 for freeze and 06:30 for submit. This plan is stricter on purpose: submit early, because the final presentation time is unknown. Update AGENTS.md if you agree.

## Owners
- Tanish: contract, engine, target backend V1 to V4, README, threat model, final refinement.
- Anmol: dashboard, target tests, V5 to V8, signup frontend, notice page, deck, demo video.

## Hour by hour

### Sun 23:00 to 00:00 (Tanish alone, Anmol arrives about 23:55)
- Push contract (done). Build target backend V1 to V4 and seed. STOP at a running app on :8000.
- Anmol: installs, clone, read docs 07, 08, 09.

### Mon 00:00 to 03:30 (build the minimal slice)
Tanish: recognizers, api_scan, idor_probe, db_scan, log_scan, runner, CLI scan to JSON.
Anmol: dashboard steps 1 and 2 on sample-scan.json (summary, list, detail, fix flow in mock mode), then target tests.
Gate at 03:30: CLI scan writes valid JSON with at least 4 findings. Dashboard shows the sample data.

### Mon 03:30 to 07:30 sleep
Both sleep. Minimum 3.5 hours. Skipping this costs more than it saves, you will write bugs at 05:00 that take two hours to find.

### Mon 07:30 to 10:00 (connect and rehearse)
Tanish: engine API on :8100, connect dashboard to real engine (change USE_MOCK).
Anmol: dashboard against the real engine, fix any field mismatch, V5 start.
09:15 rehearsal: run the 2 minute path once. If the engine is flaky, use mock mode plus a cached scan for the evaluation.
Mid eval 10:00: show target app, a real scan, the findings with clauses, the dashboard. Fix 1 verified if ready.

### Mon 10:00 to 13:00
Tanish: erasure_scan, contact_scan, browser_scan. Fix loop sandbox for V1.
Anmol: V5 to V8, notice page, signup frontend. Dashboard notice drift tab.

### Mon 13:00 to 17:00
Tanish: fix loop V1 end to end (verified true), golden cached mode, then V3.
Anmol: finish the target frontend, dashboard Data Flow tab, report print page.

### Mon 17:00 to 22:00
Tanish: V5 fix, notice_drift scanner, HTML report endpoint, README.
Anmol: deck draft (see doc 11), threat model help, screenshots.
22:00 CUT LINE: anything not working is cut. Write down what was cut and remove it from the pitch.

### Mon 22:00 to Tue 00:30 (integration)
Full run of the demo script three times. Fix bugs only. No new features.

### Tue 00:30 FEATURE FREEZE
Only bug fixes, copy and recording.

### Tue 00:30 to 03:00
Record the 2 to 3 minute demo video, export the PDF deck, finalise README, threat model, credits. Push everything.

### Tue 03:00 to 04:00 SUBMIT (target). Hard limit 06:30.
Submit: public repo, README, PDF deck, demo video, threat model, live link if applicable. Check the repo opens while logged out.

### Tue 04:00 to 08:40
Sleep a little. Prepare for the live demo and the Q and A. Keep the cached mode ready.

## Cut order
SARIF, children check, drift detector, browser scan. Never cut the fix and verify loop. If V3 and V5 fixes are not ready by 22:00, ship with V1 verified only and say so honestly.

## Risks and answers
| Risk | Answer |
|------|--------|
| Engine and dashboard disagree on fields | contract first, Anmol builds against sample-scan.json, Tanish changes the contract only after telling Anmol |
| Anmol starts late or stalls | Tanish keeps the backend and engine, dashboard falls back to the engine's HTML report |
| Fix loop is flaky live | cached golden patch mode, clearly labelled |
| Venue Wi-Fi is bad | no cloud dependency, packages and Chromium pre downloaded |
| Chrome updates before demo | do not update, bundled Chromium preferred |
| Sleep skipped | follow the sleep blocks above |
| Scope creep | anything not in docs 01 MUST or SHOULD needs a yes from Tanish |

## Rules for coding agents (work in phases)
1. Agents never run one long task. All work is split into small phases (30 to 60 minutes each) listed in docs/13-work-split.md. One phase per session.
2. Each phase has a clear deliverable and a gate (a command or a test that must pass). A phase is done only when the gate passes.
3. At the start of a phase the agent states its plan in 3 lines, names the files it will touch, and asks "go?". At the end it runs the gate, commits, pushes (after asking), updates its STATUS file, reports in at most 6 lines, and STOPS.
4. The agent never starts the next phase on its own. The human says "next".
5. If a phase runs past 90 minutes, the agent stops and reports the blocker. A stuck phase is split or cut, never left running.
6. If an agent finds work that belongs to another phase, it writes a note in its STATUS file and does not build it.
7. Each person's agent edits only its own folders and its own STATUS file (docs/STATUS-tanish.md, docs/STATUS-anmol.md).
8. The first message of every new agent session is the question "Who are you: Tanish or Anmol?".
9. Phase gates map to the timeline: T5 is the 03:30 slice, T6 plus A7 is the 09:30 connection, T10 is the 17:00 V1 fix, T11 to T13 are done by the 22:00 cut line.

## Rules to remember
All code written after hacking started. Commit small and often. Declare AI tools in README. Both must be able to explain every file. Live demo is mandatory. Localhost and synthetic data only.
