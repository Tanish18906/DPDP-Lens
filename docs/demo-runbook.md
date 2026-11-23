# Demo runbook (the Slack, dashboard and engine demo)

Everything the demo needs is one file of settings and four scripts. Nothing is typed by hand on the day.

## One time, before the day
1. `cp scripts/demo_env.example scripts/demo_env`, then fill in every value. The file is git-ignored; never commit it and never paste it into a chat.
   - `DPDP_API_TOKEN` and `VITE_DPDP_TOKEN`: the same random value. Make one with `python -c "import secrets; print(secrets.token_urlsafe(24))"`.
   - `DPDP_ALLOWED_REPOS` and `DPDP_FIX_REPOS`: `Tanish18906/acme-tutornest` (the repo we own).
   - `GITHUB_TOKEN`: a token that can read that repo.
   - `SLACK_BOT_TOKEN` (`xoxb-`), `SLACK_APP_TOKEN` (`xapp-`, scope `connections:write`), `SLACK_CHANNEL` (the channel ID), `SLACK_APPROVERS` (member IDs): see docs/slack-bot.md.
2. `npm install` in `dashboard/` once, and `.venv` as in the README quick start.
3. Rehearse with no network: `DPDP_PREFLIGHT_ARGS=--offline scripts/demo_up.sh`.

## On the day, in this order
1. `scripts/demo_down.sh` then `scripts/demo_reset.sh` (type `yes`) for a clean start: no repos, no findings, an empty audit log. Skip the reset to keep what you rehearsed.
2. `scripts/demo_up.sh`. It runs the preflight, starts the engine (:8100), the dashboard (:5174) and the Slack bot in the background, runs the preflight again against the running stack, and prints the URLs and the log folder. Do not start the demo until every line is PASS (a WARN is your decision).
3. Open the dashboard Feed. In Slack: `/dpdp connect Tanish18906/acme-tutornest`, then `/dpdp status`.
4. After the demo: `scripts/demo_down.sh`.

Run `python scripts/preflight.py --env-file scripts/demo_env` any time to check again (add `--stage env` or `--stage services` to run half of it, `--offline` to skip GitHub and Slack). The old `./run_demo.sh` starts the target app and the dashboard for the scan-and-fix demo; do not run both on the same ports.

## What each preflight line means, and what to do when it fails
| Line | PASS means | When it fails |
|------|-----------|---------------|
| variables | every required variable is set | the names are listed: add them to `scripts/demo_env`. A WARN means an optional one is missing (no fix repos, no approvers, no GitHub token) |
| token formats | no spaces or quotes, bot token starts `xoxb-`, app token `xapp-`, API token 12 or more characters, none still a placeholder | copy the token again from where it was made. Quotes in `scripts/demo_env` are a common cause |
| slack ids | the channel and approver values look like IDs | a WARN: use the ID (More, Copy ID), not `#name` or a username |
| dashboard token | `VITE_DPDP_TOKEN` equals `DPDP_API_TOKEN` | set both to the same value and restart (Vite reads it only at start) |
| allowlist | the demo repo is in `DPDP_ALLOWED_REPOS` | add `Tanish18906/acme-tutornest`. A WARN says the fix list holds a repo that cannot be connected |
| monitor | the scheduled re-scan is on | a WARN: `DPDP_MONITOR=0` is set, so `/dpdp watch` will not scan. Unset it for that part of the demo |
| database | the findings database file (or its folder) can be written | fix the folder permissions or set `DPDP_DB` to a folder you own |
| github repo | `git ls-remote` reads the demo repo with `GITHUB_TOKEN` | "no network": use a phone hotspot. "cannot read": wrong repo name, or the token cannot read it. The token goes to git through `GIT_ASKPASS` and is never shown |
| slack bot token | Slack `auth.test` accepts the bot token | `invalid_auth` or `token_revoked`: copy the Bot User OAuth Token again or reinstall the app. "no network": hotspot |
| engine | `/health` and `GET /repos` answer | not started: `scripts/demo_up.sh`. Answers with an error: read `engine.log` in the log folder, or `scripts/demo_reset.sh` if the database is broken |
| engine token | our token is accepted and a wrong one gets 401 | "different token" or "no DPDP_API_TOKEN": the engine was started from another environment. `scripts/demo_down.sh`, then `scripts/demo_up.sh` |
| dashboard | the dashboard URL answers | not started or the port is taken: `scripts/demo_up.sh`, read `dashboard.log` |

## If something dies on the day
- `demo_up.sh` prints "<name> is NOT running" for a process that exited at start and exits 1. The usual cause of a dead bot is a bad Slack token (the log says `invalid_auth`).
- No network: the cached fix mode and the dashboard sample data work offline, the Slack and GitHub parts do not. Switch to the hotspot and run `scripts/demo_down.sh && scripts/demo_up.sh`.
- Logs are in the folder printed by `demo_up.sh`. They never hold a token: the engine and the bot redact them.

## What the preflight cannot check
It cannot know that the Slack slash command is set up in the Slack app, that the bot is in the channel, that the app has the scopes it needs, or that the people in `SLACK_APPROVERS` are the ones who will click. Check those once in Slack (docs/slack-bot.md). It checks the app-level token only by its prefix, because only a running Socket Mode connection can test it. It cannot check GitHub rate limits or the repo's content, only that it can be read.
