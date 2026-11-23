# Video Script: DPDP Lens EVOLVE

Target video length: 2 minutes 45 seconds (under the 3-minute hard ceiling).
Recording setup: Full-screen 1080p, 60fps. Crisp voiceover, no background music.
Visuals: Real application captures showing Slack, Dashboard Feed, Terminal CI, and Browser.

Rules:
- Say "scheduled monitoring", never "real-time" or "continuous".
- Never say "verified" unless the engine returned `verified: true`.
- State clearly that connected-repo scans run static checks only (16 of 26 checks).
- State clearly that fix verification shows a cached label if fallback is used.
- No em dashes in the text.

---

## Shot-by-Shot Timeline

### 0:00 - 0:20 (20 seconds): The Problem and Mission

| Visual | Slide or title graphic showing "DPDP Lens: Cross-Layer DPDP Compliance Auditor". Transition to India's DPDP Act 2023 summary graphic highlighting Section 8(5) and the 13 May 2027 enforcement deadline. |
| Voiceover | "Under India's Digital Personal Data Protection Act 2023, organizations face statutory penalties of up to 250 crore rupees for failing to maintain reasonable security safeguards. Most startups lack specialized privacy teams, while existing security tools work in silos. DPDP Lens bridges that gap by embedding automated, cross-layer compliance auditing directly into Slack and developer workflows." |

---

### 0:20 - 0:45 (25 seconds): Slack Bot and Connected Repository Scan

| Visual | Screen recording of a desktop Slack workspace in `#dpdp-compliance`. Cursor types `/dpdp connect Tanish18906/acme-tutornest` into the message bar and hits Enter. |
| Voiceover | "Engineers do not want another standalone compliance portal. With DPDP Lens, developers connect their repository directly from Slack using `/dpdp connect`. For security, only allowlisted repositories can be scanned. Because we never execute untrusted remote code, connected repository scans are strictly static, executing 11 of our 19 deterministic checks." |

---

### 0:45 - 1:10 (25 seconds): Finding Cards and Evidence Masking

| Visual | Slack updates with the scan summary card, followed by interactive finding cards sorted by severity. Cursor hovers over finding `DPDP-014` (`log_pii`), showing the High severity badge and file location `backend/app/main.py:87`. Cursor clicks **View Details**, expanding a thread reply. |
| Voiceover | "The scan posts structured finding cards mapped directly to statutory clauses. Finding DPDP-014 flags personal data logged in plaintext under Act Section 8(5) and Rule 6(1)(a). In the thread details, all observed evidence is strictly masked at the source. No raw Aadhaar or PAN values ever touch Slack or application logs." |

---

### 1:10 - 1:35 (25 seconds): Human Triage and Reason Validation

| Visual | Cursor moves to another finding card (`config_debug_enabled`). In the **Change Status** dropdown, the user selects `False Positive`. A Slack modal dialog pops up requiring a reason. User types: "Debug setting enabled only in staging environment." and clicks Submit. The card updates in place to show `False Positive`. |
| Voiceover | "Compliance requires human accountability. Approvers can update finding states directly in Slack. Marking an item as a false positive or won't fix requires a mandatory justification between 1 and 300 characters, protected against PII leakage. Unauthorized users are blocked from changing status." |

---

### 1:35 - 2:05 (30 seconds): Fix and Verify in Sandbox

| Visual | Back on finding `DPDP-014` (`log_pii`), the user clicks **Fix and verify**. A thread reply appears: "Fixing DPDP-014 in a sandbox copy. The repo itself is not changed." Split screen showing terminal logs of the engine creating a temp checkout, seeding an isolated database, patching code, and running pytest. The Slack card updates to `Fixed`, displaying unified diff and verification checkmarks. |
| Voiceover | "Unlike scanners that only report problems, DPDP Lens proves the remediation. We click Fix and verify. The engine clones a temporary copy into an isolated sandbox, seeds a fresh database, applies a deterministic fix template, re-runs the scanner, and executes the test suite. We only declare an issue verified when the re-scan passes AND tests pass. If sandbox execution meets infrastructure limits, the engine transparently falls back to a pre-verified patch labelled 'Cached verified patch (replay)'." |

---

### 2:05 - 2:25 (20 seconds): Dashboard Feed and Tamper-Evident Audit Chain

| Visual | Browser window showing the Dashboard Feed at `http://localhost:5174`. The Feed displays all findings and status counts matching Slack. The user opens the detail drawer for `DPDP-014` showing the complete event timeline. A small terminal overlay executes `curl -s http://localhost:8100/audit/verify` returning `{"ok": true, "checked": 15, "first_bad": null}`. |
| Voiceover | "All triage actions and fix records synchronize to our dashboard Feed via the engine outbox. Every event is recorded in an append-only SQLite log with a SHA-256 hash chain. This provides a tamper-evident audit trail: running `/audit/verify` mathematically confirms that compliance history has not been altered." |

---

### 2:25 - 2:45 (20 seconds): CI/CD Policy Gate and SARIF

| Visual | Visual Studio Code / Terminal showing GitHub Actions workflow execution. The command `python -m dpdp_lens ci --repo-dir target-app --new-only --baseline .github/dpdp-baseline.json` executes, failing with exit code 1. Terminal displays Markdown table of new blocking findings and generation of `dpdp-lens.sarif`. |
| Voiceover | "In CI/CD, the same deterministic engine acts as a pull-request gate. Using policy-as-code and a baseline file, existing issues do not block builds. But if a PR introduces an unmasked personal data leak, the gate exits with code 1, posts a step summary, and uploads SARIF annotations directly to code review." |

---

### 2:45 - 3:00 (15 seconds): Scheduled Monitoring and Closing

| Visual | Back to Slack. User types `/dpdp watch 60`. Bot acknowledges scheduled monitoring active. Final slide displays project summary: "DPDP Lens: Cross-Layer Detection, Tamper-Evident Audit, Verified Remediation. Team: Tanish & Anmol." |
| Voiceover | "Teams configure scheduled monitoring to track compliance posture over time. DPDP Lens delivers cross-layer detection, tamper-evident audit trails, and verified remediation without slowing down engineering teams. Readiness report, not a compliance certificate. Thank you." |
