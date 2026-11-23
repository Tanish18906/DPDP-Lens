# Block 03: Slack bot (Session B, starts immediately, about 90 min)

Read dpdp-evolve-00-master.md first. The bot is a separate process. It talks to the engine ONLY through the HTTP API in master section 9 with X-DPDP-Token. No scanner or store imports. Until block 01b lands, build against a small fake API server (FastAPI in tests/) that returns the master section 9 shapes, then switch to the real engine and run the same tests against both.

## Tanish does this by hand first (15 min, while the agent codes)
1. api.slack.com/apps, Create New App, From a manifest, pick the workspace, paste:
```
display_information:
  name: DPDP Lens
features:
  bot_user:
    display_name: DPDP Lens
    always_online: true
  slash_commands:
    - command: /dpdp
      description: DPDP readiness scans
      usage_hint: connect | scan | status | diff | baseline | watch | help
      should_escape: false
oauth_config:
  scopes:
    bot:
      - chat:write
      - commands
settings:
  interactivity:
    is_enabled: true
  org_deploy_enabled: false
  socket_mode_enabled: true
  token_rotation_enabled: false
```
2. Install to workspace. Copy the Bot token (xoxb-...). Under Basic Information, App-Level Tokens, create one with scope connections:write (xapp-...). Put both in a local .env file that is NOT committed (use the shell, not the repo): SLACK_BOT_TOKEN, SLACK_APP_TOKEN.
3. In the target channel run /invite @DPDP Lens. Note the channel id (SLACK_CHANNEL) and your own member id (SLACK_APPROVERS).
4. Create GitHub repo Tanish18906/acme-tutornest containing the TutorNest backend, frontend, tests and docker-compose (copy from target-app/, keep the PLANTED markers and fake data). Create a fine-grained token with Contents read on that repo only for GITHUB_TOKEN. Set DPDP_ALLOWED_REPOS=Tanish18906/acme-tutornest.

## Package: engine/dpdp_lens/slackbot/ (run with `python -m dpdp_lens.slackbot`)
Dependencies: slack-bolt, slack-sdk (add to engine/pyproject.toml optional extra "slack"; credit in README). Socket Mode, no public URL.
Files: app.py (Bolt wiring), api.py (thin HTTP client for the engine), cards.py (pure Block Kit builders), commands.py, actions.py, outbox.py (poller), redact.py.

## Behaviour
Commands (all reply ephemeral unless noted; every handler acks within 3 seconds then works in a thread):
- `/dpdp connect owner/repo [branch]`: POST /repos, then POST /repos/{id}/scan. Posts "Scanning owner/repo (static checks only)" then, when done, a summary and one card per finding.
- `/dpdp scan [owner/repo]`, `/dpdp status` (health, last complete scan, counts), `/dpdp diff` (new, resolved, persistent since baseline), `/dpdp baseline` (approvers only), `/dpdp watch <minutes>|off` (approvers only), `/dpdp help`.
Finding card (Block Kit), posted once per finding on first sight, then edited in place with chat.update:
- line 1: `DPDP-014` linked to DASHBOARD_URL/?finding=DPDP-014, severity, status. Use plain text labels plus an emoji circle by severity.
- line 2: title.
- context: `backend/app/main.py:87`, `owner/repo@branch`, proof tag ("Behaviour confirmed by a live request" or "Static check").
- actions: View Details (button), Change Status (static_select: Open, In Progress, False Positive, Won't Fix), Fix and verify (button, only when fix_available and the repo is in DPDP_FIX_REPOS).
- View Details posts a thread reply: explanation, clauses ("Likely does not meet ..."), masked evidence in a code block, recommendation, and the severity reason. Never raw PII.
- False Positive and Won't Fix open a modal asking for a reason (required, max 300 chars) before PATCH.
- Fix and verify: approvers only. Post a thread reply "Fixing in a sandbox copy", call POST /findings/{id}/fix (timeout 90 s), then edit the card to VERIFIED (with diff in a thread reply, test result, re-scan result) or "Not verified" with what failed. If the engine answers cached mode, say "Cached verified patch (replay)". Never say verified unless the engine returned verified true.
Summary message after every scan: counts of new, resolved, persistent, suppressed; health status; a coverage line ("static checks only, 11 of 19"); if the scan is incomplete, the first line is "Scan incomplete: results are partial" and health reads Unknown. Never post a green or clean message for an incomplete scan.
Dedup: never repost a card for an unchanged finding. New findings get new cards. A resolved finding gets its card edited to Fixed.
Dashboard to Slack sync: outbox poller GET /outbox?after=N every 2 s, for each status_changed row fetch the finding and chat.update its card.
Alerts: one message when a scan becomes incomplete or health turns at_risk or unknown, repeated only after a recovery.

## Safety
- Only user ids in SLACK_APPROVERS can: Change Status, Fix and verify, baseline, watch. Others get an ephemeral "not allowed". Only SLACK_CHANNEL accepts commands unless SLACK_ALLOWED_CHANNELS is set.
- Tokens only from environment. redact.py strips xoxb-, xapp-, ghp_, github_pat_ and the DPDP_API_TOKEN from every logged string and every error shown in Slack. Test it.
- Slack rate limit: queue chat.postMessage at about 1 per second per channel, retry on 429 using Retry-After.
- Slack payloads contain masked evidence only. Test: build cards from a TutorNest scan and grep all payload text for Aadhaar, PAN and 10 digit phone patterns.

## Tests (no real Slack needed)
Inject a fake Slack client. Cover: card builder snapshots, status change flow with modal, approver denial, incomplete scan summary text, dedup, outbox update, 429 retry, redaction. One manual checklist in docs/ for the real workspace.

## Acceptance
Manual run in the real workspace: connect, cards appear, Change Status works, status shown in the dashboard Feed (block 04) after refresh, Fix and verify on the log_pii finding ends VERIFIED and the card shows Fixed. Engine suite and run_gates.sh still pass. README has a Slack setup section with the manifest.

STOP. Hand over per docs/14.
