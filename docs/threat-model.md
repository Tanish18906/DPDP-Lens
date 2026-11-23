# Threat model: DPDP Lens

Scope: the auditor engine (FastAPI, port 8100), the Slack bot (Socket Mode), the dashboard (Vite React, port 5174), the CI runner (`dpdp_lens ci`), the SQLite finding store with its audit hash chain, the GitHub repo checkout worker, and the fix verification sandbox.

Written by Tanish and Anmol. Updated 2026-11-24 for the EVOLVE release.

## 1. What we protect
- Personal data seen during a scan (demo data is synthetic, but treated as real).
- Source code, credentials, and databases of scanned and fixed repositories.
- Integrity of findings and the "verified" status (a false "verified" is worse than no fix).
- Machine running the auditor engine, Slack bot, and CI runners.
- Authenticity and chronological sequence of triage and remediation actions.

## 2. System and trust boundaries
- Boundary 1: Slack user to Slack platform to Slack bot process (Socket Mode, outbound WebSocket over TLS).
- Boundary 2: Slack bot and Dashboard (:5174) to Engine API (127.0.0.1:8100) via HTTP with `X-DPDP-Token`.
- Boundary 3: Engine to GitHub.com over HTTPS (`git clone` via `GIT_ASKPASS`, read-only token).
- Boundary 4: Engine to target applications on localhost (:8000, frontend :5173).
- Boundary 5: Engine to local fix sandbox processes (subprocess running `seed.py`, `pytest`, `uvicorn` on ephemeral ports).
- Boundary 6: Engine to local SQLite database file (`dpdp.db`).

## 3. Assumptions
- Engine runs on a developer workstation or dedicated internal runner on localhost (`127.0.0.1`).
- Scans target only repositories and apps the operator owns or is authorized to audit.
- Demo data is strictly synthetic.
- Repository code in static scans is untrusted; repository code in fix sandboxes is trusted only if listed in `DPDP_FIX_REPOS`.

## 4. Threats and mitigations (STRIDE style)

| # | Threat | Type | Mitigation (as built) | What we do NOT cover (honest limits) |
|---|--------|------|-----------------------|---------------------------------------|
| T1 | Auditor stores or leaks raw PII in evidence, logs, reports, or Slack | Information disclosure | Masking at the source (Aadhaar `XXXX XXXX 1234`, PAN `ABCDE****F`, email `a***@x.com`, phone `98XXXXXX10`). Evidence holds masked samples only. Tests grep JSON, SQLite database files, and Slack payloads for raw PII regex patterns. HTML report escapes all user values and uses strict CSP | Free-form text entered by humans in manual triage reason fields: length is capped at 300 chars and basic PII keywords are rejected, but unstructured natural language is not parsed by deep NER |
| T2 | Slack app tokens (`SLACK_APP_TOKEN`, `SLACK_BOT_TOKEN`) leaked | Information disclosure, Spoofing | Socket Mode connects out over TLS to Slack; no inbound ports or public webhook URLs are exposed. Tokens are read strictly from environment variables, never written to disk, git, or command-line arguments. Logging handlers use `RedactFilter` to redact `xoxb-` and `xapp-` strings | If the host machine is compromised, any local process running as the same user can read `/proc/$PID/environ` |
| T3 | GitHub token (`GITHUB_TOKEN`) exposed via process tables or git errors | Information disclosure, Spoofing | Read-only fine-grained personal access token scoped to `Contents: read` on allowlisted repos. Token is passed to git via a `GIT_ASKPASS` executable script in a temporary directory (mode 0700), username `x-access-token`, password from temporary subshell environment variable `DPDP_GIT_TOKEN`. Token is NEVER passed in command-line arguments (`argv`) or remote URLs. Stripped from git subshell environments (`env.update(GIT_TERMINAL_PROMPT="0")`) and redacted from git stderr | Local users who can read the temporary `askpass.sh` script during the clone window (mitigated by `mode 0700` directory). Tokens with excessive privileges granted by the operator outside the engine |
| T4 | Hostile or oversized cloned repository attacks the engine host | Denial of service, Tampering, Elevation of privilege | Strict repo allowlist in `DPDP_ALLOWED_REPOS`. Name regex validation `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`. Shallow clone (`--depth 1 --no-recurse-submodules --single-branch`). Hardened git flags: `-c core.hooksPath=/dev/null -c protocol.file.allow=never -c core.fsmonitor=false`. Timeout of 120 seconds. Size cap of 200 MB (`MAX_BYTES`): if clone exceeds 200 MB, directory is immediately deleted and scan aborted. Static scanner runs AST inspection and file walkers only; NEVER executes repository code during scan. Temp directory cleaned up in `finally` block | Parsing vulnerabilities in Python standard library AST or file parser when reading malformed syntax. High file count up to walker cap (5000 files / 1 MB cap per file) consuming local CPU |
| T5 | Fix sandbox runs untrusted target repository code | Elevation of privilege, Tampering | Fix verification runs target repository code (`seed.py` and `pytest`). This execution is strictly restricted to repositories explicitly listed in `DPDP_FIX_REPOS` (`repo_scan.check_name(..., "DPDP_FIX_REPOS")`, otherwise HTTP 403). For all other connected repositories, fix execution is refused. Runs in a temporary copy with `TUTORNEST_DB` pointing to a temporary SQLite file, with a 60s timeout | No container or cgroup boundary in this version. The sandbox runs with the same OS privileges as the engine user. An operator adding an untrusted repo to `DPDP_FIX_REPOS` risks arbitrary local code execution |
| T6 | Unauthorized local process calls mutating engine API routes | Tampering, Elevation of privilege | Engine binds to `127.0.0.1`. All mutating routes (`POST /repos`, `POST /repos/{id}/scan`, `PATCH /findings/{id}/status`, `POST /findings/{id}/fix`, `POST /repos/{id}/baseline`, `POST /repos/{id}/watch`) require `X-DPDP-Token` header, validated with constant-time comparison (`hmac.compare_digest`). If `DPDP_API_TOKEN` is unset on the engine, all mutating calls return HTTP 403 | For the dashboard demo, `VITE_DPDP_TOKEN` is compiled into the client-side JavaScript bundle. In browser environments, client bundles are not secret storage. Any local user inspecting browser memory or network traffic on localhost can obtain `VITE_DPDP_TOKEN`. Intended for local demo only |
| T7 | Unauthorized Slack user changes finding status, approves fixes, or triggers scans | Tampering, Repudiation | Only users whose Slack member IDs are in `SLACK_APPROVERS` can change finding statuses, trigger Fix and verify, set baselines, or configure watch intervals. Non-approvers receive an ephemeral rejection ("Not allowed: only approvers can do this.") and UI components reset. Commands are accepted only in channels listed in `SLACK_CHANNEL` or `SLACK_ALLOWED_CHANNELS` | Compromise of an authorized Slack user account or Slack workspace administrators who can impersonate or reassign IDs |
| T8 | Secrets and tokens leak into application logs or terminal output | Information disclosure | `RedactFilter` is attached to all logging handlers. Automatically strips token patterns (`xoxb-`, `xapp-`, `ghp_`, `github_pat_`) and exact string values of `DPDP_API_TOKEN`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, and `GITHUB_TOKEN`. Error strings and git stderr pass through `redact()` before being returned to clients or Slack | Tokens under 4 characters (not applicable to real tokens). Unusual encodings (e.g. hex or base64) created by external libraries before logging |
| T9 | Audit log manipulation, backdating, or deletion of compliance events | Repudiation, Tampering | Append-only `events` table in SQLite. Every event computes `hash = sha256(prev_hash + canonical_json(event))`. Genesis block is 64 zeros. `GET /audit/verify` re-computes every link in the chain and reports any modified, inserted, deleted, or reordered event | Tamper-evident, NOT tamper-proof. Anyone with direct write access to the SQLite file (`dpdp.db`) can recalculate and rewrite the entire hash chain from any point, or truncate events off the tail. External append-only log replication is required for full non-repudiation |
| T10 | A false "verified" fix status | Repudiation, Integrity | `verified` is computed algorithmically: the original finding fingerprint must not appear in the post-fix re-scan, AND the application's test suite must pass. If the scanner fails during re-scan, verification fails. A patch that does not apply returns 422 with no fallback. Manual status transition to "fixed" via API or Slack is rejected with 422 ("Fixed is set by a scan or a verified fix") | Fix templates are designed for specific known patterns. If a test suite has zero test coverage for a regression, an imperfect fix could pass tests |
| T11 | Cached golden fix presented as a live verification | Repudiation | Cached golden patches fall back only on infrastructure errors or timeouts. When cached results are used, the finding and Slack notification explicitly display "Cached verified patch (replay)" or "Cached golden patch mode" with the fallback reason. The engine never presents cached data as live execution | None; the engine explicitly distinguishes live vs cached modes in data contracts and UI |
| T12 | Scanning targets outside the authorized scope | Misuse | `POST /scan` accepts only localhost or private-IP targets. `repo_path` and `db_path` must exist inside repo root (`DPDP_REPO_ROOT`). GitHub repos must be in `DPDP_ALLOWED_REPOS`. Non-destructive HTTP GET requests only (except controlled deletion probe on synthetic test accounts) | If an authorized user intentionally adds an external IP or unauthorized repo to the allowlists |
| T13 | Supply chain attacks via dependencies or tracking datasets | Tampering | Minimal dependency set. Python packages and licenses audited and credited in README. Disconnect `services.json` committed with provenance. No arbitrary install scripts run at demo time | Upstream vulnerabilities in direct dependencies (FastAPI, uvicorn, slack-bolt, playwright) |
| T14 | Personal data or secrets committed in target demo repository | Information disclosure | Target demo app TutorNest uses synthetic fake identities only. Planted secrets in `.env`, Dockerfile, and docker-compose are synthetic dummy values. Scanners mask secrets (first 2 characters + `***`) | Real secrets mistakenly committed to target repositories by developers outside our demo environment |

### Planted secrets in demo target
The demo app TutorNest contains deliberately planted dummy secrets: `target-app/backend/.env` (V9), Dockerfile and compose file (V10, V12), and `SECRET_KEY` in `app/auth.py`. All values are synthetic and function nowhere. `backend/.env` is tracked via `.gitignore` exception specifically to test static scanners. The engine scanner masks all detected secrets (showing 2 characters plus `***`).

## 5. Out of scope and known limits
- Connected repository scans are static only (16 of 26 checks). Dynamic runtime checks (IDOR, unauthenticated API PII exposure, live DB plaintext checks, browser tracking, deletion verification, child consent verification) require a running instance and are not executed against connected GitHub repos.
- Fix sandbox execution requires local Python environment and runs target code with engine privileges (gated by `DPDP_FIX_REPOS`). It does not run inside an isolated Docker container or VM sandbox.
- The audit hash chain is tamper-evident, not tamper-proof. Local database file modification can forge the chain.
- `VITE_DPDP_TOKEN` in the browser bundle is visible to anyone with browser devtools access on localhost.
- Single-worker concurrency: repo cloning and scanning uses a global lock (one clone and scan at a time).
- Checks cover a specific technical subset of DPDP Act 2023 and DPDP Rules 2025. A clean scan does not constitute a legal compliance certificate.

## 6. What we would do next
- Containerized sandbox (Docker or gVisor) for fix verification runs.
- Asymmetric cryptographic signatures on audit events and PDF export reports with a hardware security module (HSM) or cloud KMS.
- Ephemeral backend token exchange for browser dashboard sessions rather than shared static token.
- Multi-tenant cloud execution with dedicated worker pools and isolated VPC networks.
- Ingestion of live OpenTelemetry spans and runtime API gateway traffic to complement static repo scanning.

## 7. Safe use rules
- Run only against applications and repositories you own or are authorized to test.
- Use synthetic data exclusively for testing and demonstration.
- Keep `DPDP_ALLOWED_REPOS` and `DPDP_FIX_REPOS` restricted to verified repositories.
- Never deploy the vulnerable TutorNest target application to any public network.
