# GitHub App setup (block 08)

Connect GitHub through an installed GitHub App instead of one fixed repo. In Slack, `/dpdp connect` with no argument shows a Connect GitHub button. You install the app on your account, choose the repositories to share, and come back to Slack to pick one from a list. It is then connected and scanned exactly like `/dpdp connect owner/repo`.

The old path stays: `DPDP_ALLOWED_REPOS` plus `GITHUB_TOKEN`, and `/dpdp connect owner/repo`. Nothing changes for an engine that has no app settings.

## What the app needs

Create it once at github.com, Settings, Developer settings, GitHub Apps, New GitHub App.

| Setting | Value |
|---|---|
| Repository permissions | Contents: **Read-only**. Metadata: **Read-only** (GitHub adds it). Nothing else. |
| Account permissions | none |
| Webhook | **Off** (Active unchecked). The engine never receives a GitHub event. |
| Setup URL | `http://localhost:8100/github/setup` (the engine's port). Tick "Redirect on update" if you want the page after changing the shared repositories. |
| Where can it be installed | Only on this account is enough (single tenant). |

After creating it, note the **App ID** and the **slug** (the last part of `github.com/apps/<slug>`), then press "Generate a private key". GitHub downloads a `.pem` file. Move it out of every repo and set mode 600:

    mkdir -p ~/secrets && mv ~/Downloads/<app>.private-key.pem ~/secrets/dpdp-lens-app.pem
    chmod 600 ~/secrets/dpdp-lens-app.pem

The engine refuses a key file that group or others can read. Never copy the key into the repo, a chat, a log or Slack.

## Environment (engine, and the preflight)

| Variable | Meaning |
|---|---|
| `GITHUB_APP_ID` | the App ID (a number) |
| `GITHUB_APP_SLUG` | the app's slug, used for the install link |
| `GITHUB_APP_PRIVATE_KEY_PATH` | path of the `.pem` file. The engine reads the file when it needs a JWT. It is never stored or logged. |
| `DPDP_API_TOKEN` | already required. It also signs the install link's state (HMAC, valid 15 minutes). |

All three `GITHUB_APP_*` values must be set, or the app flow is off. They are not secrets (the key file is). The bot needs no new variable: it uses `ENGINE_URL` for the Connect GitHub link, so that URL must open in the browser you use (the default `http://127.0.0.1:8100` does on the same machine).

Run `python scripts/preflight.py --env-file scripts/demo_env`. The app lines read `SKIP` when the app is not set up. When it is: variables present, key file exists with safe permissions and parses, an app JWT can be built, and (network) `GET /app` answers 200 with your slug.

## The install flow

1. An approver types `/dpdp connect`. With no installation yet the bot answers (only to them) with a **Connect GitHub** button. The button opens `ENGINE_URL/github/connect`, which sends the browser to `github.com/apps/<slug>/installations/new` with a fresh signed, expiring state. The state is never posted in Slack.
2. On GitHub choose the account and the repositories to share, then Install.
3. GitHub sends the browser to `/github/setup?installation_id=...&state=...`. The engine checks the state and its expiry, asks GitHub (with the app JWT) that the installation exists, stores it (table `installations`), writes the audit event `github_installed` and one outbox row. The browser shows "GitHub connected, return to Slack".
4. The bot posts one line in the channel: `GitHub connected: <account>, <n> repositories shared`.
5. `/dpdp connect` now shows a dropdown of the shared repositories (up to 100, connected ones marked) and a Connect button. Connect runs the same connect and static scan as `/dpdp connect owner/repo`. `/dpdp repos` lists them without connecting.

A repo is allowed when it is in `DPDP_ALLOWED_REPOS` (as before) or when the named installation shares it **right now** (asked from GitHub, never remembered). Anything else is 403. Scans of a repo connected through the app clone with a short-lived installation token (a new one when the cached one has less than 5 minutes left, so a scheduled scan always has a working token). The token reaches git through `GIT_ASKPASS`, never argv or a URL, and is never stored.

## New engine routes

| Route | Guard | Purpose |
|---|---|---|
| `GET /github/install-url` | token | the GitHub install URL with a signed state (for scripts) |
| `GET /github/connect` | none (a browser opens it) | redirect to the install URL with a fresh state |
| `GET /github/setup` | the signed state | GitHub's redirect after the install |
| `GET /github/installations` | token | installations the engine knows |
| `GET /github/installations/{id}/repos` | token | shared repos, live from GitHub, with `connected` |
| `POST /repos` | token | now also takes `installation_id` |

These two reads are guarded because they reveal who installed the app and private repo names. Every other read stays open.

## Limits

- **Single tenant.** One engine, one app, a shared Slack channel. There is no per-user login and no isolation between installations: any approver can connect any repo an installation shares.
- **No webhooks.** The engine learns about an install only from the browser redirect, and about changes to the shared repos only when it asks (at connect, at `/dpdp repos`, at each scan). Removing a repo from the installation makes its next scan fail (shown as Unknown, never healthy).
- **Static scan only.** A connected repo gets the 9 static checks, as before. The app has read-only access and never runs repo code.
- **Fix only for `DPDP_FIX_REPOS`.** Installing the app on a repo never makes it fix-eligible: the fix sandbox runs repo code, so it stays restricted to the repos named in `DPDP_FIX_REPOS`, and the engine checks that on every fix.
- **Not built:** webhooks, OAuth user login, multi-tenant accounts, write permissions, pull requests, scanning a whole organisation automatically.
- **Database.** Schema version 3 adds `installations` and `repos.installation_id`. An existing file migrates on first start. An older engine refuses a version 3 file, so do not point two engine versions at the same `DPDP_DB`.

## Credits

PyJWT (MIT), https://github.com/jpadilla/pyjwt, and `cryptography` (Apache-2.0 or BSD), https://github.com/pyca/cryptography, for the RS256 app JWT.
