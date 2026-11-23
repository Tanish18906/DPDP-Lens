# Block 04: dashboard Feed (Session B, after 03, about 60 to 75 min). Cut to read-only first if behind.

Read dpdp-evolve-00-master.md first. Needs the real API from 01b.

## Inspect first
dashboard/src/App.jsx is one 1607 line file: API_BASE (line 5), `activeTab` state (about line 368), left rail (about line 685), the existing Findings, Notice vs Runtime and Data Flow views, the Tag, StepMarker and Button components, tokens in dashboard/src/index.css, gates in scripts/gates/ (they select by visible text, so do not rename existing labels).

## Tasks
1. New file dashboard/src/Feed.jsx. App.jsx gets only: an import, a "Feed" rail item (with the open count), and a view switch. No refactor of the rest. Use existing tokens and components. Do not copy any other product's look. Own mark, own colours, IDs read DPDP-014.
2. Feed view: repo filter (All repositories or one), status tabs with counts (Open, In Progress, Fixed, False Positive, Won't Fix) from `counts_by_status`, search box, table with columns Finding (severity word + ID + title + one line of explanation), Location (file:line or url, repo@branch), Status. Sorted critical first. Poll GET /findings every 5 s (no websockets). Real skeleton loading rows, a designed empty state ("No findings yet. Connect a repository from Slack with /dpdp connect"), a designed error state with the engine text.
3. Row click opens a detail drawer: severity reason, explanation, clauses with notes, masked evidence block, recommendation, proof tag, status select (same PATCH as Slack, reason required for False Positive and Won't Fix), event timeline from GET /findings/{id}, and a Fix and verify button only when fix_available and allowed. The X-DPDP-Token comes from Vite env VITE_DPDP_TOKEN (README: demo only, not secret in a browser bundle, engine binds to localhost).
4. Incomplete scans: a red banner at the top of Feed and of the existing Findings view when the latest scan has complete false: "Scan incomplete: results are partial" with the scanner names from scan_errors. Health pill per repo (Healthy, Changed, At Risk, Unknown) with the reasons on hover and for screen readers. Static scans show "Static checks only (n of 19)".
5. No mock data in live mode. Sample mode keeps working and is labelled SAMPLE as today.
6. Gate: scripts/gates/gate_feed.py (Playwright, same style as the others, added to scripts/run_gates.sh): seeds the store through the API with a local repo scan, checks tabs and counts, changes a status through the UI and sees the count move, checks incomplete banner using a forced failure, checks no raw PII on the page.

## Acceptance
All existing gates still pass (6 of 6 plus the new one), `vite build` and oxlint pass, Feed matches Slack statuses after a status change in either place.

STOP. Hand over per docs/14.
