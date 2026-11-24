# GitHub App setup (block 08)

Connect GitHub through an installed GitHub App instead of one fixed repo. In Slack, `/dpdp connect` with no argument shows a Connect GitHub button. You install the app on your account, choose the repositories to share, and come back to Slack to pick one from a list. It is then connected and scanned exactly like `/dpdp connect owner/repo`.

The old path stays: `DPDP_ALLOWED_REPOS` plus `GITHUB_TOKEN`, and `/dpdp connect owner/repo`. Nothing changes for an engine that has no app settings.

## What the app needs

Create it once at github.com, Settings, Developer settings, GitHub Apps, New GitHub App.

| Setting | Value |
|---|---|
| Repository permissions | Contents: **Read-only** to scan and connect. Add **Read and write** on Contents and **Read and write** on Pull requests only if you want the Open pull request action (see below). Metadata: **Read-only** (GitHub adds it). Nothing else. |
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
- **Static scan only.** A connected repo gets the 9 static checks, as before. Scans and clones always use a read-only installation token and never run repo code.
- **Fix only for `DPDP_FIX_REPOS`.** Installing the app on a repo never makes it fix-eligible: the fix sandbox runs repo code, so it stays restricted to the repos named in `DPDP_FIX_REPOS`, and the engine checks that on every fix.
- **Not built:** webhooks, OAuth user login, multi-tenant accounts, merging a pull request, deleting or force-pushing a branch, scanning a whole organisation automatically.
- **Database.** Schema version 3 adds `installations` and `repos.installation_id`. An existing file migrates on first start. An older engine refuses a version 3 file, so do not point two engine versions at the same `DPDP_DB`.

## Open pull request (block 13)

After a VERIFIED live fix an approver can click **Open pull request** (Slack row, Slack fix result, Slack details, dashboard drawer, or `POST /findings/{human_id}/pr` with the token). The engine pushes a branch with the verified change and opens a pull request. A person merges it. The engine never merges, never pushes to the default branch, never force-pushes and never deletes.

**It is off by default.** It works only when all of these hold. Otherwise the button does not appear and the route answers 403 (or 409 for an unverified fix) with a plain reason:
- `DPDP_ALLOW_PR=1` on the engine.
- The repo is in `DPDP_FIX_REPOS`.
- The repo was connected through the GitHub App installation (not through `GITHUB_TOKEN` and the allowlist).
- The fix is verified, was run live (a cached replay is refused) and has not got a pull request yet.
- In Slack the user is in `SLACK_APPROVERS`. In the dashboard the page needs `VITE_DPDP_TOKEN`, as Fix and verify does.

**The app needs more permission for this only:** Contents **Read and write** and Pull requests **Read and write** (account Settings, Developer settings, your app, Permissions; then accept the change on the installation). Scans and clones keep using the read-only installation token. For the pull request the engine asks GitHub for a separate installation token limited to that one repository and to `contents: write` and `pull_requests: write` (the `repositories` and `permissions` fields of `POST /app/installations/{id}/access_tokens`). It is kept in memory for that one action, never cached, never used for a scan, and never logged (`ghs_` tokens are redacted everywhere).

**What it does:**
- Branch `dpdp-lens/fix-<human_id>-<first 7 characters of the scanned commit>` (checked against a strict pattern), made from the exact commit that was scanned and fixed. If the branch exists, the engine reports it and returns its open pull request when there is one. It never touches the existing branch.
- The files on the branch are the verified result: the stored verified diff is applied to the exact blobs of the scanned commit through the git data API, and the result must reproduce that diff character for character, or nothing is pushed. Only the files in the diff change, with their modes.
- If the default branch has moved on since the scan, the pull request is still made against it and its body says so.
- Title `DPDP Lens: fix <human_id> <title>`. Body: the finding with its clause references ("Likely does not meet ..."), a per-file summary, the two lines "Verified: ..." and "Not verified / you still must: ..." exactly as the engine wrote them, and that it was generated by DPDP Lens, must be reviewed, and is a readiness fix, not a compliance certificate. No raw personal data, no tokens.
- The audit log gets `pr_opened` (with the url, branch and actor) or `pr_failed` (with the reason). The pull request url is stored on the finding and shown in Slack and the dashboard. The finding stays Fixed after the verified fix; only a later scan of the merged code resolves it. Schema version 4 adds `findings.pr_url`.

**Limits:** a file without a newline at its end, or whose content at the scanned commit differs from what was verified, is refused (nothing is pushed). Only repos in `DPDP_FIX_REPOS`. One pull request per finding. No automatic close or rollback: close the pull request and delete the branch on GitHub if you do not want it. `scripts/preflight.py` shows a `pull requests` line (SKIP unless `DPDP_ALLOW_PR=1`); it cannot check the app's write permission, only a real click can.

## Credits

PyJWT (MIT), https://github.com/jpadilla/pyjwt, and `cryptography` (Apache-2.0 or BSD), https://github.com/pyca/cryptography, for the RS256 app JWT.
