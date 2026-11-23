# Slack bot (block 03)

The bot is a separate Python process (`python -m dpdp_lens.slackbot`). It talks to the engine only through the HTTP API with the `X-DPDP-Token` header. It does not import the scanner or the store. It uses Socket Mode, so it needs no public URL.

## Setup

1. Install the extra: `pip install -e "engine[slack]"` (slack-bolt and slack-sdk, both MIT).
2. At api.slack.com/apps choose Create New App, From a manifest, and paste:

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
      usage_hint: connect | scan | status | findings | report | diff | baseline | watch | help
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

3. Install the app to the workspace. Copy the bot token (`xoxb-...`). Under Basic Information, App-Level Tokens, create a token with the `connections:write` scope (`xapp-...`).
4. In the target channel run `/invite @DPDP Lens`. Note the channel id and your own member id.
5. Export the settings in the shell. Do not put them in a file in the repo:

| Variable | Meaning |
|---|---|
| `SLACK_BOT_TOKEN` | `xoxb-...` (required) |
| `SLACK_APP_TOKEN` | `xapp-...` (required) |
| `DPDP_API_TOKEN` | the same value the engine uses (required) |
| `SLACK_CHANNEL` | channel id that accepts commands and gets scheduled alerts (required unless `SLACK_ALLOWED_CHANNELS` is set) |
| `SLACK_ALLOWED_CHANNELS` | comma separated channel ids, replaces `SLACK_CHANNEL` as the list of channels that accept commands |
| `SLACK_APPROVERS` | comma separated Slack member ids who may change a status, fix, baseline or watch |
| `DPDP_FIX_REPOS` | comma separated `owner/repo`: only these get a Fix and verify button (the engine checks it too) |
| `ENGINE_URL` | default `http://127.0.0.1:8100` |
| `DASHBOARD_URL` | default `http://localhost:5174` |

6. Start the engine with `DPDP_API_TOKEN`, `DPDP_ALLOWED_REPOS`, `DPDP_FIX_REPOS` and `GITHUB_TOKEN` set, then run `python -m dpdp_lens.slackbot` from `engine/`. If a required variable is missing the bot prints its name (never its value) and exits.

## What it does and does not do

- `/dpdp connect` with no argument (approvers): connect through the GitHub App, see docs/github-app-setup.md. `/dpdp repos` (approvers) lists the shared repos. The bot posts "GitHub connected: <account>, <n> repositories shared" when the install finishes.
- `/dpdp connect owner/repo [branch]`, `scan`, `status`, `diff`, `baseline` (approvers), `watch <minutes>|off` (approvers), `help`. Answers to commands are ephemeral. The scan summary and the finding cards are posted in the channel.
- `/dpdp findings [open|all]` (default open) answers ephemerally with the findings of the channel's repo, critical first, one line each: severity, the id linked to `DASHBOARD_URL/?finding=<id>`, title, `file:line`, status. `open` lists Open and In Progress. `all` groups by status and adds Fixed and the suppressed ones (False Positive, Won't Fix), labelled "suppressed". At most 50 lines, then "and N more, see the dashboard". If the last scan was incomplete or failed, or health is Unknown, the first line says the list is not a clean result. An empty list is stated plainly. The scan summary adds "<n> findings still open: /dpdp findings" while any are open; unchanged findings get no new card.
- `/dpdp report [owner/repo]` (approvers) answers ephemerally with a link to the DPDP readiness report and a one-line summary (open counts by severity, health, coverage). The link is signed, expires after 15 minutes and is bound to one repo and one scan, so anyone who sees the reply can open that one report until it expires: do not use it in a shared channel you do not trust. An incomplete scan or an Unknown health is said first. See docs/readiness-report.md.
- One card per finding, posted once and then edited in place. Cards follow status changes made in Slack, in the dashboard or by a scan, through the engine outbox (polled every 2 seconds).
- Fix and verify says "VERIFIED" only when the engine's answer has `fix.verified` true and the finding status `verified_fixed`. A cached replay is labelled "Cached verified patch (replay)".
- An incomplete scan starts with "Scan incomplete: results are partial" and health reads Unknown. A scan that produced no result says "Scan failed". Neither is ever shown as green.
- `/dpdp diff` shows the latest scan against the baseline (`GET /repos/{id}/diff`): new, resolved and persistent finding ids. Resolved only counts checks the scan actually ran, and an incomplete scan says so first.
- The bot keeps two things in memory only: the outbox position (it starts at the end of the outbox, so changes made while the bot was down are not replayed) and which repos already got a health alert (after a restart a repo that is still bad can get one more alert).

## Manual checklist for the real workspace

- [ ] Bot starts, no "Missing environment" line, no token in the log.
- [ ] `/dpdp help` in the allowed channel shows the help. In another channel it answers "does not take commands in this channel".
- [ ] `/dpdp connect Tanish18906/acme-tutornest` posts "Scanning ... (static checks only)", then a summary with the coverage line "static checks only (n of 19)", then one card per finding, critical first.
- [ ] Every card links to `DASHBOARD_URL/?finding=DPDP-nnn`.
- [ ] `/dpdp scan` again: a summary only, no new cards.
- [ ] View Details answers in the card's thread with clauses and masked evidence only.
- [ ] Change Status to In Progress as an approver: the card edits itself. As a non-approver: "Not allowed" and the select resets.
- [ ] False Positive and Won't Fix open a modal. An empty reason is refused. A reason holding an Aadhaar number with the word "aadhaar" is refused by the engine and shown in the modal.
- [ ] Change a status in the dashboard Feed (block 04): the Slack card follows within a few seconds.
- [ ] Fix and verify on the `log_pii` finding as an approver: thread reply "Fixing ... in a sandbox copy", then the result with the diff, and the card shows Fixed. As a non-approver: "Not allowed".
- [ ] `/dpdp watch 5`, then break a scanner or the clone: an alert appears once, health reads Unknown, and nothing says healthy.
- [ ] `/dpdp status`, `/dpdp diff`, `/dpdp baseline` and `/dpdp watch off` answer.

## Credits for the README

- slack-bolt (MIT), https://github.com/slackapi/bolt-python
- slack-sdk (MIT), https://github.com/slackapi/python-slack-sdk
