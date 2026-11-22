# 07 UI and UX (dashboard)

Owner: Anmol. This doc is about how it should feel and flow. 09 has the build spec. 08 has the visual rules.

## Who looks at it
- Judges, on a projector, for about 2 minutes, standing or sitting at a distance.
- A startup CTO who needs to find the worst problem fast.
So: big text, few colours, the most important thing first.

## The one story the UI must tell
1. A score that looks bad (45 out of 100).
2. A list of problems, worst first, each with a clause.
3. One click turns a problem into a verified fix and the score goes up.
4. A panel that shows the gap between what the notice says and what the app does.

## Screens

### Screen A: Overview (default)
    +--------------------------------------------------------------+
    | DPDP Lens   target: localhost:8000   [Run scan] [Export]     |
    +--------------------------------------------------------------+
    |  (score gauge 45)   Critical 2  High 4  Medium 2  Low 1       |
    |  Readiness report, not a compliance certificate               |
    +--------------------------------------------------------------+
    | [Findings] [Notice vs Runtime] [Data Flow]                    |
    +-----------------------------+--------------------------------+
    | CRITICAL  Open API exposes  | Detail panel for the selected  |
    | HIGH      PII in logs       | finding (see Screen B)         |
    | ...                         |                                |
    +-----------------------------+--------------------------------+

### Screen B: Finding detail (right panel)
Order: title with severity, plain explanation, clause chips, evidence (masked), fix button or fix result.
Wording: short sentences. No legal jargon without the plain version next to it.

### Screen C: Fix and verify
Button "Fix and verify". After click: five step progress (copy to sandbox, apply patch, restart, re-scan, run tests). Then a diff viewer, three badges (Re-scan passed, Tests passed, Verified), and the score moving from before to after. If anything fails, show it in red honestly.

### Screen D: Notice vs Runtime
Two columns. Left "What the notice says we collect". Right "What the app really handles", each field with where it was seen. Fields that are not in the notice are red with "Not in the notice". Summary line on top, computed from the data.

### Screen E: Data Flow
Simple boxes and arrows: Database, API, Frontend, Third parties. Arrows labelled with field names. Red arrows carry fields that are not in the notice.

### Screen F: Report
Printable clean version of A to D. Opened by Export.

## States
| State | What the user sees |
|-------|--------------------|
| Loading scan | skeleton rows and "Scanning database, API, code, browser..." with a small stepper |
| Empty (no findings) | green "No findings from the checks we ran" plus a line saying the checks are limited |
| Engine not reachable | banner "Engine not reachable" and a "Use sample data" button |
| Fix running | progress steps, button disabled |
| Fix failed | red result, the reason, no score change |
| Cached golden patch | amber label "Cached golden patch mode" next to the result |

## Copy (use as is, adjust slightly if needed)
- Page subtitle: "Does your app do what your privacy notice says?"
- Score caption: "Readiness score. Higher is better."
- Clause chip tooltip: the note text from the clause.
- Fix button: "Fix and verify"
- Success: "Verified. Re-scan passed and the app's tests still pass."
- Footer: "DPDP Lens is a readiness report, not a compliance certificate. Main duties apply from 13 May 2027."

## Interaction rules
- Click a finding row to open the detail. Keyboard: arrow keys move through the list, Enter opens.
- The selected finding stays highlighted.
- Never reload the page when a fix finishes. Update the row, the score and the counts in place.
- Do not auto scroll. Do not use pop up modals except for the report preview.

## Accessibility basics
Colour is never the only signal (always a label). Text contrast must be readable on a projector. Buttons at least 40px tall. Focus outlines visible.

## Demo path (click order)
Load page, point at the score, click the critical finding, read the clause chip, click Fix and verify, show diff and badges, show the score change, switch to Notice vs Runtime, point at the red fields. Total under 2 minutes.
