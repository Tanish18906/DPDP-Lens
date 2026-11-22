# 09 Dashboard build spec (docs/09-dashboard-build.md)

Owner: Anmol. Folder: dashboard/. Stack: React + Vite + Tailwind. Port 5174.
Read AGENTS.md first. This file only adds detail for the dashboard.

## What it is for
This is the screen the judges look at during the live demo. It has to make three things obvious in 30 seconds:
1. We found real problems, with proof.
2. Each problem maps to a DPDP clause.
3. We fixed one, verified it, and the score went up.

Keep it a single page with three tabs. No login. No router library needed.

## Data
- One constant API_BASE = "http://localhost:8100". One constant USE_MOCK = true or false.
- Mock mode loads contract/sample-scan.json (copy it into dashboard/public/ on build or import it). Real mode calls the engine API from AGENTS.md section 5.
- Never invent fields. Use only what is in contract/finding.schema.json. If you need a new field, ask Tanish.
- If the API is down in real mode, show a clear "Engine not reachable" banner with a "Use sample data" button.

## Page layout

Top bar: product name "DPDP Lens", target URL, scan time, a "Run scan" button, an "Export report" button, and a small badge "Readiness report, not a compliance certificate".

Summary row:
- Score gauge 0 to 100 (colour by band: below 50 red, 50 to 79 amber, 80 and up green).
- Four severity counts (critical, high, medium, low).
- A small line "Score before / after" that appears once any finding is fixed (use fix.score_before and fix.score_after).

Tabs: Findings | Notice vs Runtime | Data Flow.

## Tab 1: Findings
Left: table or card list, sorted critical first. Columns: severity pill, title, layer chip (db, code, api, browser, notice), clause chips (first two, "+n"), status ("Open" or "Verified fixed" with a green check).
Right (or a drawer): finding detail panel with, in this order:
1. title and severity
2. explanation (plain English)
3. clause chips, each with the note on hover or click (example: "Act s8(5)" then "reasonable security safeguards")
4. evidence block: kind, summary, masked_sample in monospace, location (file:line, url, or table.column). Show only the masked value. Never display raw PII anywhere.
5. fix block: if fix.available and status is open, a primary button "Fix and verify". Otherwise nothing.

### Fix and verify flow (the demo moment)
Clicking the button calls POST /findings/{id}/fix (real mode). While waiting, show a 5 step progress list that ticks off:
1. Copy app to a sandbox
2. Apply patch
3. Restart patched app
4. Re-run the failed check
5. Run the app's tests
In mock mode simulate this with about 1 second per step, then set status to verified_fixed, show the diff, and animate the score from score_before to score_after.
After it finishes show:
- unified diff viewer (red and green lines, monospace, scrollable)
- three badges: "Re-scan passed", "Tests passed", "Verified" (green only if the data says true; red or grey otherwise)
- score before to after
If fix.verified is false after the run, show it honestly in red. Never fake a pass.
If the engine reports it ran in cached golden patch mode, show a visible label "Cached golden patch mode".

## Tab 2: Notice vs Runtime (the headline feature, make it look good)
Use notice_drift from the scan.
- Left column: "What the privacy notice says we collect" (declared) as chips.
- Right column: "What the app really handles" (observed). Each observed field is a card with the field name and a list of where it was seen (db:..., api:..., request:...). Format those as small tags.
- Any field in undeclared is highlighted red with the label "Not in the notice".
- A one line summary at the top, generated from the data: "3 of 6 data fields are collected but not disclosed" (compute it, do not hardcode).
- A short caption: "Notice duties: Act s5, Rule 3".

## Tab 3: Data Flow
A simple SVG, no chart library. Four boxes left to right: Database, Backend API, Frontend, Third parties.
Build the arrows from notice_drift.observed[].where by prefix: db: goes to Database, api: to Backend API, request: to Third parties. Label the arrows with field names. Draw arrows that carry an undeclared field in red.
This is a visual aid, so keep it clean. Do it only after the other two tabs work.

## Report page
A button "Export report" opens the engine's /report/{scan_id} in a new tab in real mode. In mock mode, call window.print() on a clean print stylesheet that shows the summary, the findings with clauses and evidence, and the drift summary.

## Look and feel
- Dark, calm, security console feel. Not a template look. One accent colour. Clear spacing.
- Severity colours: critical red, high orange, medium amber, low blue-grey. Do not use colour alone, always add the text label.
- Monospace for evidence and diffs. Readable font size for a projector (body text at least 16px).
- No animation except the score count and the fix progress steps.
- Footer on every page: "DPDP Lens is a readiness report, not a compliance certificate. Main duties apply from 13 May 2027."

## Build order and done criteria
1. (First 45 minutes) Vite + Tailwind scaffold, load sample-scan.json, summary row, findings list, detail panel with evidence and clause chips. Commit and push.
2. Fix and verify flow in mock mode, with the diff viewer and the before and after score. Commit and push.
3. Notice vs Runtime tab.
4. Switch to the real engine API (change USE_MOCK, test against the running engine on port 8100).
5. Report print view, then Data Flow tab, then polish.
Done for the mid evaluation (Mon 10:00): steps 1, 2 and 4 working with the real engine, or step 2 working in mock mode if the engine is late.

## Do not do
- No auth, no database, no state library, no heavy UI kit.
- Do not edit contract/ or engine/.
- Do not display raw personal data. Only what the engine marks as masked_sample.
