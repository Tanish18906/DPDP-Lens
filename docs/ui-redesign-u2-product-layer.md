# UI redesign phase U2: product layer (do only after U1 passes the gates)

Read claude/ui-redesign-brief.md (U1) first. U2 uses the same tokens, branch and rules. Start U2 only when U1 is finished and run_gates.sh passes. Same hard stop: 09:30 for anything that goes into the 10:00 mid-eval, otherwise it waits on the branch.

## Goal
The dashboard should look like a shipped startup product, not a hackathon page. That comes from consistency, brand and designed states. It does not come from extra features.

## Do not build
Login, settings, billing, landing page, fake users, fake charts, fake scan history. Anything the engine does not really back is a fake dashboard, and the rulebook wants a real working demo. A scan history list is allowed only if it is read from the scans the engine really saves, with no new API. Do not copy another company's look.

## 1. Brand kit (original, small)
- Wordmark "DPDP Lens" in the serif heading font.
- One simple original logo mark drawn as an SVG by hand (geometric, for example a ring with a notch). No stock icon, no copied logo.
- Favicon from the same mark. Page title "DPDP Lens: readiness report".
- Tagline, used once on the first-run screen and the report: "Does your app do what its privacy notice says?"
- The same mark and tokens go on the HTML report, README header screenshot, the deck and the video.

## 2. App shell
- Fixed left rail, about 220px: logo and name at the top, then nav items Findings (with count), Notice vs Runtime (with drift count), Data flow if it still exists. This replaces the tabs.
- Bottom of the rail: target URL, last scan time, engine status dot with text.
- Main area: page title on the left, Run scan (primary) and Export report (text button) on the right.
- Keep up and down arrow navigation in the findings list.

## 3. Every state designed
| State | What it shows |
|---|---|
| First run, no scan yet | Tagline, the target, one primary button Run scan |
| Scanning | The 5 layers (API, DB, Code, Browser, Notice) ticking from the engine's real progress events, skeleton rows, no spinner |
| Results | Score hero, findings list, detail |
| Fixing | 5 step list ticking from real progress events |
| Verified | VERIFIED mark, diff, one verification row with three ticks, score before and after |
| Fix failed | Honest red result with what failed |
| Cached result | A clear CACHED label next to the result |
| Engine down | Banner, and a "Use sample data" button; sample mode carries a SAMPLE label until the user returns to live |
| All fixable findings verified | Quiet success summary with score before and after and an Export report button |

## 4. Small things that read as product
- Six components only, used everywhere: Button (primary, secondary, text), Tag (one style), Stat, Table row, Panel, Code block.
- Tabular numbers for all counts and scores. Real skeleton loading, never a bare spinner.
- Visible focus rings and hover states on every clickable thing.
- A small toast for "Report exported".
- Empty table copy that says what to do next.
- Same page title style and spacing on every screen.

## Order of work
1. Brand kit and shell (rail, header). Run gates.
2. First run, scanning, engine down and cached states. Run gates.
3. Verified, fix failed and all-verified states. Run gates.
4. Apply the brand to the HTML report. Run gates, re-seed demo.db, new fallback screenshots in docs/fallback-shots/.
5. Hand over changed files and a commit message. Stop.

## Done means
- run_gates.sh passes from a clean shell and demo.db is re-seeded.
- Every state in the table above exists and was seen by a human at least once.
- No page, button or number that the engine does not really produce.
- Logo, favicon, page title and tokens are the same on the dashboard and the report.
