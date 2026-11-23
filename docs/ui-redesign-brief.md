# UI redesign brief (phase U1), DPDP Lens dashboard

Owner: Anmol (on Tanish's laptop). Written 23 Nov 05:00 IST. Copy this file into the repo as docs/ui-redesign-brief.md and give it to the coding agent as its first read.

## Goal
Make the dashboard stop looking AI generated, and make the 2 minute judge demo read from the back of a hall. Visual and copy changes only.

## Hard rules
- Work on a branch: `git checkout -b ui-redesign`. The mid-eval at 10:00 runs from main (last good commit f862d05).
- No change to the scan JSON contract, the engine, the API calls or the fix logic.
- Keep every data-testid, id, selector and visible text that scripts/run_gates.sh relies on. If a gate must change, change it in the same step.
- Do not touch lines under a PLANTED marker.
- After each screen: run ./scripts/run_gates.sh from a clean shell. All must pass before the next screen.
- Hard stop 09:30. If not finished and passing, leave it on the branch and present from main.
- Fonts: install with @fontsource packages and bundle them. No CDN links. Venue Wi-Fi is shared and slow.
- Re-seed demo.db after any live run. Claude never runs git commands, humans do.

## Diagnosis (from the current screenshots)
1. Everything is the same bordered, rounded dark card. Nothing leads the eye. The score is the point of the page but it is a thin strip with a tiny ring.
2. Each finding row carries 5 chips (severity pill, layer, two clause chips, status) and severity is repeated in 3 places (row pill, left bar, top counts).
3. Neon green accent and green monospace evidence is the "hacker terminal" default.
4. Filler copy: "Needs Attention", "Readiness score. Higher is better.", "Automated verified fix available".
5. Small text: many labels are 11 to 13px. Projector needs more.
6. Header and content do not share a left edge (logo sits about 30px left of the score card).
7. Notice vs Runtime is the best screen but the key rows (aadhaar, parent_pan) fall below the fold. The right column is long, the left is short.
8. Data Flow is a small diagram floating in a big empty box, with 11px stacked field labels. Lowest value screen.

## Concept: "audit working paper"
The product is an auditor. Look like one: a calm, light, paper like page with ink text, one restrained accent, evidence set like a workpaper exhibit, and a VERIFIED mark after a fix. It prints well to the HTML report, reads on a projector, and is not the dark neon dashboard that every generated UI converges on.
Fallback if the team insists on dark: same system, inverted, still one accent and no glow.

## Tokens (starting points, verify contrast)
- Paper background #F6F4EF, surface #FFFFFF, ink #1B1D22, muted text #5B6270, line #DDD8CC.
- One accent, deep teal #0E5A55, for primary buttons, links and the verified state only.
- Severity, always shown with its word, never colour alone: critical #B42318, high #C4510B, medium #A8780A, low #5B6270. Text colours must hit 4.5:1 on the paper background. Darken any that do not.
- Type: headings and the big score in a serif (Newsreader), body in IBM Plex Sans, evidence and numbers in IBM Plex Mono with tabular numbers.
- Scale: score 72px, page title 28px, section title 20px, body 16px, table text 15px, smallest label 13px. Nothing below 13px.
- Radius 6px, 8px grid, no shadows, no gradients, no glow.
- Layout: one max width (1280), one left edge shared by header and content.

## Screens
### Header
Wordmark "DPDP Lens" (plain text, serif). Target and scan time as quiet text. Run scan is the only filled button. Export report is a text button. Engine status is a small dot with text. Move the "not a compliance certificate" disclaimer to the footer (keep it on every page).

### Findings tab
- Score hero: big number "0 / 100" at left. After a verified fix show "0 to 83" with the number counting up. To its right, ONE stacked bar of severity counts with labels, replacing the four pills.
- List: dense rows. One severity marker (small bar plus the word), title, layer as plain small text, status as plain text. Group headers "Critical (2)", "High (5)". Remove clause chips and the Open chip from rows.
- Detail panel: title, explanation, then "Law" as plain lines ("Act s8(5), reasonable security safeguards"). Evidence as a quiet monospace block with the URL or location in a header bar, no green text. Primary button "Fix and verify". Cached option as a text link "Use cached result" that shows a clear CACHED label once used.
- Fix moment: vertical 5 step list ticking from the real progress events, full width diff, one verification row with three ticks (Re-scan passed, Tests passed, Verified), score counting up. Show a failure honestly in red.

### Notice vs Runtime tab
Keep the headline. Turn the two column cards into one table: Field | In the notice? | Where it was seen. Undeclared rows first (aadhaar, parent_pan, dob), highlighted with a left rule and the words "Not in the notice". All 6 rows must fit on one screen at 1080p without scrolling.

### Data Flow tab
Preferred: replace the architecture drawing with a field by layer matrix. Rows = fields, columns = Notice, Database, API, Browser, with a mark where seen, undeclared rows in the danger colour. If short on time, merge this matrix into Notice vs Runtime and drop the third tab. If the diagram stays, make it fill its card and set labels at 14px or more.

### Leave alone
TutorNest signup page (it should look like a plain student app). The report page only gets the new tokens.

## Copy changes
| Now | New |
|---|---|
| Needs Attention | Not ready (below 50), Partly ready (50 to 79), Ready for review (80+) |
| Readiness score. Higher is better. | remove |
| Automated verified fix available | Verified fix available |
| Runs on a sandbox copy: patch, re-scan, then the app's tests | Proposed on a sandbox copy. Counts as verified only if the re-scan and the app's tests pass. |
| Replay saved result | Use cached result |
| 3 of 6 data fields are collected but not disclosed | 3 of 6 data fields the app handles are not in its privacy notice |
Never write "automated fix" or "auto-fix" anywhere.

## Motion (only these)
- Score count up (about 800ms).
- Fix steps tick as the real progress events arrive.
- Row selection and hover, 120 to 160ms ease.
- Respect prefers-reduced-motion. No page load stagger, no bounce, no glow.

## Order of work
1. Tokens and fonts in one place (CSS variables), header, footer. Run gates.
2. Findings tab and the fix moment. Run gates.
3. Notice vs Runtime table. Run gates.
4. Data Flow matrix or merge. Run gates.
5. Report page tokens. Run gates, re-seed, take new fallback screenshots into docs/fallback-shots/.
6. Hand over the changed files and commit message. Stop.

## Done means
- run_gates.sh passes from a clean shell, demo.db re-seeded.
- All text 13px or more, body 16px.
- One severity marker per row, no clause chips in rows.
- All 6 notice fields visible without scrolling.
- Full demo (scan, fix, notice, export, cached fallback, engine down banner) clicked through by a human once.
