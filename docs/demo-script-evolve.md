# Live Demo Script: DPDP Lens EVOLVE

Target duration: 3 minutes (180 seconds).
Audience: Hackathon judges, technical leads, privacy engineers.

Standing vocabulary rules:
- Say "scheduled monitoring", never "real-time" or "continuous".
- Never say "verified" unless the engine returned `verified: true`.
- Say plainly that connected-repo scans are static only (9 of 19 checks).
- Say plainly that fix verification may display a cached label if sandbox execution falls back.
- Always conclude: "Readiness report, not a compliance certificate."
- No em dashes in script or slides.

---

## 1. Pre-Demo Setup Checklist (Do 10 minutes before)

1. Ensure the demo repository exists: `Tanish18906/acme-tutornest`.
2. Environment variables exported in shell:
   ```bash
   export DPDP_API_TOKEN="dpdp-demo-secret-token"
   export DPDP_ALLOWED_REPOS="Tanish18906/acme-tutornest"
   export DPDP_FIX_REPOS="Tanish18906/acme-tutornest"
   export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
   export SLACK_BOT_TOKEN="xoxb-xxxxxxxxxxxx"
   export SLACK_APP_TOKEN="xapp-xxxxxxxxxxxx"
   export SLACK_CHANNEL="C0XXXXXXXXX"
   export SLACK_APPROVERS="U0XXXXXXXXX"
   export ENGINE_URL="http://127.0.0.1:8100"
   export DASHBOARD_URL="http://localhost:5174"
   ```
3. Start background services in separate terminal tabs:
   - Tab 1 (Engine):
     ```bash
     cd engine && source ../.venv/bin/activate
     python -m uvicorn dpdp_lens.api:app --host 127.0.0.1 --port 8100
     ```
   - Tab 2 (Slack Bot Socket Mode):
     ```bash
     cd engine && source ../.venv/bin/activate
     python -m dpdp_lens.slackbot
     ```
   - Tab 3 (Dashboard):
     ```bash
     cd dashboard
     npm run dev -- --port 5174
     ```
4. Browser windows ready:
   - Window 1: Slack channel with the `@DPDP Lens` bot invited.
   - Window 2: Dashboard Feed at `http://localhost:5174`.
   - Window 3 (Optional backup): GitHub Actions tab for `Tanish18906/acme-tutornest`.
5. Local terminal tab ready for CI gate demo.

---

## 2. Timed Script (3 Minutes)

### 0:00 - 0:30 (30s): Connect Repository via Slack Front Door

| Visual | Slack window open in the demo channel. |
| Action | Type slash command: `/dpdp connect Tanish18906/acme-tutornest` |
| What Happens | Ephemeral ack appears: "Scanning Tanish18906/acme-tutornest (static checks only)..." Within 3 to 5 seconds, a summary message posts in the channel followed by finding cards. |
| What to Say | "India's Digital Personal Data Protection Act 2023 and the 2025 Rules require technical safeguards for personal data starting May 2027. Developers do not want another siloed security portal; they live in Slack and GitHub. DPDP Lens brings compliance auditing directly to them. Here, we run `/dpdp connect` with our repository. To protect server integrity, only allowlisted repositories can connect. Connected repository scans are static only, running 11 of our 19 checks without executing untrusted code." |
| Fallback | If venue Wi-Fi slows down or Slack Socket Mode disconnects, switch to terminal: `curl -X POST http://localhost:8100/repos/1/scan -H "X-DPDP-Token: $DPDP_API_TOKEN" -H "Content-Type: application/json" -d '{"mode":"static"}'` or switch directly to Dashboard Feed loaded at `http://localhost:5174`. Fallback screenshots: `docs/fallback-shots/feed-open.png`. |

---

### 0:30 - 1:00 (30s): Finding Cards and Clause Mapping

| Visual | Slack channel displaying finding summary and individual cards sorted by severity. |
| Action | Scroll to finding `DPDP-014` (`log_pii`). Click **View Details**. |
| What Happens | A thread reply opens containing: legal clauses (Act s8(5), Rule 6(1)(a)), file location (`backend/app/main.py:87`), masked sample (`a***@x.com`), and recommendation. |
| What to Say | "The scan finishes with a transparent coverage report: static checks only, 9 of 19 checks run. Here is finding DPDP-014: personal data logged in plaintext. When we click View Details, we see the legal grounding. Section 8(5) for reasonable security safeguards, Rule 6(1)(a) for data masking. Notice the evidence: all samples are masked at the source. No raw PII ever enters Slack or logs." |
| Fallback | If the thread reply delays, show the card text directly or show the same finding in the Dashboard drawer at `http://localhost:5174/?finding=DPDP-014`. Fallback screenshot: `docs/fallback-shots/children-finding.png`. |

---

### 1:00 - 1:30 (30s): Human Triage and Reason Modal

| Visual | Slack card for another finding (e.g. `config_debug_enabled`). |
| Action | On the card, open the **Change Status** dropdown and select `False Positive`. |
| What Happens | Slack opens a modal dialog: "Provide reason for status change". Type: "Debug mode restricted to local test environments." Click Submit. The card updates in place to show status `False Positive`. |
| What to Say | "Compliance audits require accountability. If a developer claims a finding is a false positive or won't fix, they cannot simply click dismiss. The bot requires an explicit reason between 1 and 300 characters, validated to prevent PII entry. Furthermore, this action is restricted to authorized member IDs in `SLACK_APPROVERS`. An unauthorized user gets rejected immediately." |
| Fallback | If the modal fails to open, demonstrate the status update in the Dashboard drawer, where the same reason requirement is enforced. Fallback screenshot: `docs/fallback-shots/feed-open.png`. |

---

### 1:30 - 2:05 (35s): Fix and Verify in Sandbox

| Visual | Return to finding `DPDP-014` (`log_pii`). |
| Action | Click **Fix and verify** on the card. |
| What Happens | Thread reply posts: "Fixing DPDP-014 in a sandbox copy. The repo itself is not changed." The engine clones a temporary checkout, seeds an isolated SQLite database, applies the fix template, re-runs the scanner, and executes pytest. Card updates to status `Fixed`. The thread shows unified diff and verification results. |
| What to Say | "Now for our core differentiator: verified fixes. We click Fix and verify. The engine does not patch production or touch the repository directly. It clones a temporary copy into a sandbox, seeds an isolated database, applies the patch, re-scans, and runs the test suite. Only when the re-scan passes AND the tests pass do we declare it verified. If local sandbox resources time out, the engine falls back to a cached golden patch, clearly labelled 'Cached verified patch (replay)' so we never fake a live result." |
| Fallback | The engine has built-in fallback: if the live sandbox fails or times out, it replays the verified golden patch and outputs the explicit label "Cached verified patch (replay)". If Slack hangs completely, run CLI fix: `python -m dpdp_lens fix F-003 --cached` in terminal. Fallback screenshot: `docs/fallback-shots/fix-cached-label.png`. |

---

### 2:05 - 2:30 (25s): Dashboard Feed and Tamper-Evident Audit Chain

| Visual | Switch to Dashboard browser window at `http://localhost:5174`. |
| Action | Click the **Feed** tab. Point to finding `DPDP-014` showing status `Fixed`, and the false-positive finding showing status `False Positive`. Open terminal and run: `curl -s http://localhost:8100/audit/verify | jq .` |
| What Happens | Feed displays updated statuses, synchronized via outbox polling. Terminal returns: `{"ok": true, "checked": 15, "first_bad": null}`. |
| What to Say | "Over in the dashboard Feed, statuses update within seconds via the engine outbox. Every action, triage note, and fix verification is written to an append-only SQLite log with a SHA-256 hash chain. It is tamper-evident: running `/audit/verify` confirms that no row has been edited, inserted, or deleted. Anyone altering past events breaks the chain." |
| Fallback | If the dashboard web page needs refresh, reload `http://localhost:5174`. If terminal curl is slow, open browser tab `http://localhost:8100/audit/verify`. Fallback screenshot: `docs/fallback-shots/data-flow-live.png`. |

---

### 2:30 - 2:50 (20s): CI/CD Policy Gate

| Visual | Switch to terminal window showing project directory. |
| Action | Run the CI check command against target code with a baseline:
  ```bash
  python -m dpdp_lens ci --repo-dir target-app --new-only --baseline .github/dpdp-baseline.json --summary ci-summary.md
  echo "Exit code: $?"
  head -n 12 ci-summary.md
  ```
| What Happens | The command evaluates static policy rules against baseline. If a new violation exists, it exits 1, outputs Markdown summary with blocking findings, and writes SARIF 2.1.0 report. |
| What to Say | "In our CI/CD pipeline, the same engine runs as a GitHub Action. We use policy-as-code with a baseline file so pre-existing tech debt does not block merges. But if a PR introduces a new unmasked Aadhaar log, the gate fails with exit code 1, posts a GitHub Step Summary, and uploads SARIF annotations directly to code review." |
| Fallback | Display `docs/ci-example/dpdp-lens.md` or the committed test fixture showing the Markdown step summary table. |

---

### 2:50 - 3:00 (10s): Scheduled Monitoring and Conclusion

| Visual | Switch back to Slack. |
| Action | Type: `/dpdp watch 60` (or `/dpdp status`). |
| What Happens | Bot confirms: "Watch interval set to 60 minutes for Tanish18906/acme-tutornest." |
| What to Say | "Finally, we set up scheduled monitoring. Not continuous noise, but scheduled scans comparing code against the baseline to detect drift. DPDP Lens delivers cross-layer visibility, tamper-evident audit logs, and verified remediation where engineers work. Readiness report, not a compliance certificate. Thank you." |
| Fallback | If Slack is unresponsive, show the watch setting in the dashboard repository header. |

---

## 3. Quick Reference for Judge Questions

1. "Why only 9 checks in the Slack demo?"
   - Connected GitHub repositories run static analysis only. We never execute untrusted remote code. The remaining 10 dynamic checks (IDOR probe, unauthenticated API exposure, live DB plaintext checks, browser tracking, deletion verification, children verification) run when auditing a live running application instance.
2. "Is the audit trail blockchain?"
   - No. It is an append-only SQLite table where each record contains the SHA-256 hash of the prior record. It is tamper-evident, not tamper-proof. Anyone with raw file write access could rewrite the file, but silent tampering is detected.
3. "Did you use an LLM for detection or fixes?"
   - No. Detection uses deterministic pattern matching, checksum validators (Verhoeff for Aadhaar, format rules for PAN), and AST parsers. Fixes use verified templates. No non-deterministic LLM is in the evaluation or fix loop.
