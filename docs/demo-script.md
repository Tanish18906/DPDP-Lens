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
| 0:25 | Findings appear | "Score 0 out of 100. 10 findings: 2 critical, 5 high, 2 medium, 1 low." |
| 0:35 | Click the first critical finding, "Public API endpoint" | "A public endpoint returns Aadhaar and PAN with no login. Act section 8(5), Rule 6(1)(b). This is the evidence, masked." |
| 0:55 | Click **Fix and verify** (the 5 step list runs, about 3 seconds) | "We patch a copy, restart it, re-run the check and run the app's own tests." |
| 1:15 | Diff and three green badges appear | "Re-scan passed, tests passed, verified. The original code is untouched." |
| 1:30 | Point at the score line "0 → 18 (+18)" | "18 points, proven, not claimed. The score is floored at 0, so the real swing is 20." |
| 1:35 | Click **Notice vs Runtime** | "The notice lists name, email and phone. The app also handles date of birth, Aadhaar and parent PAN. 3 of 6 fields are collected but not disclosed. That gap is what a regulator cares about." |
| 1:50 | Click **Data Flow** (optional, 5 seconds) | "Red arrows are the undeclared fields moving from the database through the API." |
| 1:55 | | "Readiness report, not a certificate. Thank you." |

If there is time, or a judge asks: fix "Personal data written to logs" (score 18 to 28) and "Tracking script loads before any consent" (28 to 38). Both are live and verified, about 3 seconds each.

## Facts to say correctly
- The tracker is shown as its own finding ("Tracking script loads before any consent"), not as a field in the Notice vs Runtime tab. Do not say the drift tab shows the tracker. In live mode the Data Flow arrow to third parties is grey on purpose.
- The sample data mode has its own numbers (score 45, a `facebook.com` request in the drift tab) and is labelled "Sample Data Mode". Do not mix them up with live numbers.
- 3 findings have a verified fix (V1, V3, V5). The others show "No automated fix yet". Say so if asked.
- Under-18 signup without parental consent (V8) is detected (high, Act s9(1), Rule 10) but has no verified fix yet.

## Fallbacks (all tested)
| Problem | What you see | Do |
|---------|--------------|----|
| Live fix cannot finish (sandbox error, timeout of 60 s) | Amber "Cached golden patch mode" label with the reason, the diff and badges from a saved verified run | Keep going and say: "This is the saved result of a run that was verified earlier. It is labelled." Never present it as live |
| Engine dies | Header pill "Engine offline", amber banner "Engine not reachable at http://localhost:8100" with **Use sample data** | Either restart the engine (below) and reload the page, or click Use sample data. Sample mode is labelled and its fix says "Simulated (sample data)". The other servers keep running |
| Frontend :5173 is down | A scan has 8 findings and score 13 (no browser findings, so no tracker finding to fix) | Restart it: `cd target-app/frontend && npm run dev` |
| Patch does not apply | Red "Fix failed" banner with the engine's text, finding stays open | Say so honestly, move on to another finding |
| Everything is broken | Sample mode, or the screenshots in `/tmp/claude-1000/a7-shots/` (40 to 45) and the video | Say it is a recording |

Restart the engine alone: `cd engine && ../.venv/bin/python -m uvicorn dpdp_lens.api:app --host 127.0.0.1 --port 8100`. The dashboard reconnects after a page reload, no other restart needed. Scans and fix results are in engine memory only, so run Run scan again after a restart.

## Gotchas
- Do not click Run scan again after a fix. Fixes go to a sandbox copy and the original app is never patched, so a new scan reads 0 again. Say "the patch is a download you apply yourself" if asked.
- A live scan writes to `demo.db` (the erasure check signs up and deletes a synthetic user). Re-seed with `cd target-app/backend && ../../.venv/bin/python seed.py`, or just restart `./run_demo.sh`.
- Restarting the engine loses the stored scans. Scan again before fixing.
- The Export report button opens the engine's HTML report in a new tab (about 4 printed pages). In cached mode the report carries the same "Cached golden patch mode" label.
- Chrome or Chromium must be installed for the browser findings. Not tested without it; expect the browser findings to be missing, like with the frontend down.

## Not rehearsed yet
Timing with a human speaking and clicking (do 3 timed runs), the video recording, the deck.
