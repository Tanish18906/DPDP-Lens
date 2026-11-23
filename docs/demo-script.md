# Demo script (rehearsed 2026-11-23 against the live stack)

This replaces the numbers in the script in docs/11. Everything below was run end to end with a Playwright script on the real stack: 12 of 12 checks passed for the live path (re-run after children_scan was added). Machine time from "Run scan" to the Notice vs Runtime tab, including one verified fix, is about 6 seconds. The talking is what takes the time, so the 2 minute target is about speech, not waiting.

## Before you go on stage
1. Stop any old servers on ports 8000, 5173, 8100 and 5174.
2. Run `./run_demo.sh` from the repo root. It re-seeds the synthetic `demo.db` and prints "Demo ready".
3. Open http://localhost:5174. The header pill must read "Live Engine (:8100)" in green.
4. Do not click Run scan yet. Do not re-scan after a fix during the demo (see Gotchas).
5. Phone hotspot on, though nothing needs the internet. Laptop charged. Second laptop with the repo cloned and `./run_demo.sh` tested.

## Live script (2 minutes)
| Time | Do | Say |
|------|----|-----|
| 0:00 | Show http://localhost:5173 for 5 seconds | "This is TutorNest, a tutoring app for school students. It looks fine." |
| 0:10 | Click **Run scan** (takes about 2 seconds) | "We scan the database, the code, the running API and the browser." |
| 0:25 | Findings appear | "Score 19 out of 100. 18 findings: 2 critical, 10 high, 5 medium, 1 low." |
| 0:35 | Click the first critical finding, "Public API endpoint" | "A public endpoint returns Aadhaar and PAN with no login. Act section 8(5), Rule 6(1)(b). This is the evidence, masked." |
| 0:55 | Click **Fix and verify** (a real elapsed clock while the engine works, about 2 seconds, then its 5 measured steps appear, 0.6 seconds each) | "We patch a copy, restart it, re-run the check and run the app's own tests." |
| 1:15 | Diff and three ticks appear (Re-scan passed, Tests passed, Verified) | "Re-scan passed, tests passed, verified. The original code is untouched." |
| 1:30 | Point at the score: the big number counts up to 29, next to it "Score change 19 to 29" | "10 points, proven, not claimed. A critical finding costs 10 points, a high one 5, a medium 2, a low 1." |
| 1:35 | Click **Notice vs Runtime** | "The notice lists name, email and phone. The app also handles date of birth, Aadhaar and parent PAN. 3 of 6 fields the app handles are not in its privacy notice. That gap is what a regulator cares about." |
| 1:50 | Click **Data Flow** (optional, 5 seconds) | "One lane per field. Red lanes start at a cross: Aadhaar, date of birth and parent PAN sit in the database and come out of the API without login, and the notice never mentions them." |
| 1:55 | | "Readiness report, not a certificate. Thank you." |

If there is time, or a judge asks: fix the next ones live, about 3 seconds each. In click order after V1 (19 to 29): V2 IDOR 39, V3 logs 44, V5 tracker 49, V6 consent 51, V7 erasure 56, V8 minors 61. The Findings tab then shows 11 left open (plaintext columns, notice drift, missing contact and the 8 config findings).

## Facts to say correctly
- The tracker is shown as its own finding ("Tracking script loads before any consent"), not as a field in the Notice vs Runtime tab. Do not say the drift tab shows the tracker. In live mode the Data Flow Browser column is empty on purpose (the footnote says no third-party request was seen as a drift field and trackers are reported as findings).
- The sample data mode has its own numbers (score 73, a `facebook.com` request in the drift tab) and is labelled "Sample Data Mode". Do not mix them up with live numbers.
- 7 findings have a verified fix (V1, V2, V3, V5, V6, V7, V8). Plaintext columns (V4), the notice drift and the missing contact show a disabled "No fix template yet" button. Fixing all seven moves the score 19 to 61. Two fixes are partial: V8 only requires a well-formed parent PAN (the parent is not verified), V6 fixes the box but not the notice.
- Under-18 signup without parental consent (V8) is detected (high, Act s9(1), Rule 10) but has no verified fix yet.

## Fallbacks (all tested)
| Problem | What you see | Do |
|---------|--------------|----|
| Live fix cannot finish (sandbox error, timeout of 60 s) | Amber CACHED tag and "Cached golden patch mode" label with the reason, the diff and badges from a saved verified run | Keep going and say: "This is the saved result of a run that was verified earlier. It is labelled." Never present it as live. You can also choose it on purpose: the **Use cached result** link sits next to Fix and verify (live mode only) |
| Engine dies | Header status "Engine offline", banner "Engine not reachable at http://localhost:8100" with **Use sample data** | Either restart the engine (below) and reload the page, or click Use sample data. Sample mode is labelled and its fix says "Simulated (sample data)". The other servers keep running |
| Frontend :5173 is down | A scan has 16 findings and score 26 (no browser findings, so no tracker finding to fix) | Restart it: `cd target-app/frontend && npm run dev` |
| Patch does not apply | Red "Fix failed" banner with the engine's text, finding stays open | Say so honestly, move on to another finding |
| Everything is broken | Sample mode, or the screenshots in `docs/fallback-shots/` and the video | Say it is a recording |

Restart the engine alone: `cd engine && ../.venv/bin/python -m uvicorn dpdp_lens.api:app --host 127.0.0.1 --port 8100`. The dashboard reconnects after a page reload, no other restart needed. Finished scans are saved on disk, so after the reload the dashboard still needs a new Run scan to show findings, but the old scan ids and fixes are intact on the engine.

## Gotchas
- Do not click Run scan again after a fix. Fixes go to a sandbox copy and the original app is never patched, so a new scan reads 0 again. Say "the patch is a download you apply yourself" if asked.
- A live scan writes to `demo.db` (the erasure check signs up and deletes a synthetic user). Re-seed with `cd target-app/backend && ../../.venv/bin/python seed.py`, or just restart `./run_demo.sh`.
- Finished scans survive an engine restart (saved in `.dpdp-state/`, git-ignored). A scan that was still running is lost. `rm -rf .dpdp-state` clears them before a fresh demo.
- Export report is a menu: PDF (A4 download, about 8 pages, needs Chromium or Chrome on the engine machine), HTML (new tab), JSON (the scan result) and SARIF. It is hidden in sample mode. In cached mode the report carries the same "Cached golden patch mode" label.
- Chrome or Chromium must be installed for the browser findings. Not tested without it; expect the browser findings to be missing, like with the frontend down.

## How to run the gates
`scripts/run_gates.sh` runs six Playwright gates (88 checks) against the demo stack and prints PASS or FAIL per gate. It exits 1 if any gate fails. Run it before every demo and after every change to the engine or the dashboard (about 70 seconds).

    scripts/run_gates.sh

- All 4 ports (8000, 5173, 8100, 5174) free: it starts `./run_demo.sh` itself and stops it at the end.
- All 4 already up: it reuses them. A mix of up and down ports: it stops and says so.
- It re-seeds `demo.db` at the end. A single gate can be run alone, for example `.venv/bin/python scripts/gates/gate_rehearsal.py` (stack must be up).
- Settings: `DASH_URL` (default http://localhost:5174), `ENGINE_URL` (default http://localhost:8100), `SHOT_DIR` (default `docs/fallback-shots`).
- The gates are: `rehearsal` (the demo path with timings), `all_fixes` (7 live fixes, score 19 to 61), `children`, `data_flow` (the Data Flow field lanes), `offline` (engine unreachable, sample mode), `fix_states` (cached label, fix error, unverified, the Use cached result link).
- The `offline` and `fix_states` gates block or rewrite requests in the browser. They never stop a server.
- The numbers in `scripts/gates/common.py` are the demo facts (18 findings, score 19, the fix order). If the checks or scores change, update them there.
- A run rewrites the screenshots in `docs/fallback-shots/`. `fix-cached-label`, `fix-error-banner` and `fix-unverified` show simulated states (the engine's answer is rewritten in the browser), not a real failure.

## Not rehearsed yet
Timing with a human speaking and clicking (do 3 timed runs), the video recording, the deck.
