# Submission Checklist: DPDP Lens EVOLVE

Hack-a-Sol 5.0 | IIIT Naya Raipur | Track: Cyber Security (CS-01)
Last updated: 2026-11-24
Status categories: `done`, `not done`, `unknown / check against final build`.

Rule: Plain direct wording, no em dashes.

---

## 1. Core Submission Deliverables

| Deliverable | Rulebook Requirement | Status | Verification & Notes |
|-------------|----------------------|--------|----------------------|
| Public GitHub Repository | Publicly accessible repository containing all source code and documentation | done | Repository `Tanish18906/dpdp-lens` is public. Can be cloned and viewed in a logged-out browser window. |
| Comprehensive README.md | Project description, problem statement, architecture, quick start, checks table, limits, and team | done | `README.md` at repo root covers all required sections. Contains quick start (`./run_demo.sh`), 26 checks table, architecture diagram, and honest limits. (Final freeze pass verifies updated evolve env vars). |
| PDF Presentation Deck | 8 to 12 slides covering problem, solution, architecture, verified fix, governance, and limits | check against final build | Outline prepared in `docs/deck-outline-evolve.md`. Human export to PDF (`dpdp-lens-evolve.pdf`) scheduled before the submission deadline. |
| Demo Video (2 to 3 Minutes) | 2 to 3 minute screen recording demonstrating key workflows, architecture, and remediation proof | check against final build | Script prepared in `docs/video-script-evolve.md` (timed at 2m45s). Recording and upload scheduled immediately after code freeze. |
| Threat Model Documentation | Comprehensive threat model analyzing attack surfaces, mitigations, and known limits | done | Updated in `docs/threat-model.md` covering Slack tokens, GitHub tokens, clone isolation, sandbox execution, API token auth, and audit chain limits. |
| AI Tools Declaration | Explicit disclosure of AI assistance used during development | done | Both Claude Code and Antigravity are explicitly declared in `README.md`, `AGENTS.md`, and presentation documentation. |
| Licensing and Credits | Full attribution of third-party libraries, datasets, and specifications | done | All open-source packages (FastAPI, slack-bolt, Playwright, etc.), Disconnect `services.json` (CC BY-NC-SA 4.0), and SARIF 2.1.0 schema (OASIS Open) are credited with licenses in `README.md`. |

---

## 2. Hackathon Integrity Rules

| Rule / Constraint | Description | Status | Verification & Notes |
|-------------------|-------------|--------|----------------------|
| Code Written After Start | All project code must be authored during the hackathon window (after 20:00 Sunday) | done | Git commit history confirms initial commit and all feature branches were created after hacking began. Commit timestamps reflect hackathon progression. |
| Authorised Targets Only | Strictly forbidden to scan external, third-party, or unauthorized systems | done | Scans run exclusively against our own localhost demo application (`TutorNest`) and our own synthetic GitHub repository (`Tanish18906/acme-tutornest`). External network scanning is prohibited by code allowlists. |
| Synthetic Data Only | No real personal data permitted. All demo PII must be artificially generated | done | All names, emails, phone numbers, PANs, and Aadhaar numbers are synthetic dummy fixtures. Aadhaar numbers are generated using the Verhoeff checksum algorithm to test validators without real identities. |
| Raw PII Masking | Auditor must never store or expose unmasked personal data | done | PII masking is enforced at the source. Evidence objects, SQLite records, Slack Block Kit cards, and application logs hold masked samples only. Tests grep database and Slack payloads for raw PII. |
| Safe Fix Sandbox | Application patches must never directly overwrite user production directories | done | Fixes are verified on temporary isolated copies. Original repository files remain untouched. A fix is marked verified only when post-fix re-scan and test suites pass. |

---

## 3. Product & Technical Execution

| Capability | Requirement | Status | Verification & Notes |
|------------|-------------|--------|----------------------|
| Cross-Layer Audit | Scans multiple technical tiers in a single run | done | Audits database schema, backend source code, configuration files (`.env`, Dockerfile, docker-compose), frontend code, running APIs, browser tracking scripts, and privacy notices. |
| Statutory DPDP Mapping | Every finding mapped to DPDP Act 2023 sections and DPDP Rules 2025 | done | `contract/clauses.json` maps each check to verified Act sections (e.g. s5, s6, s8(5), s8(7), s9) and Rules (Rule 3, Rule 6(1), Rule 10, Rule 14). |
| Deterministic Engine | No hallucinations or non-deterministic models in the core scan/fix loop | done | Detection relies strictly on AST analysis, checksum algorithms, regex, and OpenAPI specs. Evaluator is deterministic policy-as-code. No LLM in the loop. |
| Slack Bot Front Door | Interactive compliance bot in Slack | done | Slack bot (`python -m dpdp_lens.slackbot`) supports `/dpdp connect`, `/dpdp scan`, `/dpdp status`, `/dpdp diff`, `/dpdp baseline`, and `/dpdp watch` via Socket Mode. |
| Finding Cards & Triage | Interactive Slack cards with human-in-the-loop triage | done | Block Kit cards support View Details (thread reply), Change Status (with mandatory reason modal for False Positive / Won't Fix), and Fix and verify. Gated by `SLACK_APPROVERS`. |
| Transparent Coverage | Honest declaration of static vs dynamic coverage | done | Connected GitHub repository scans explicitly report "static checks only (16 of 26)". System never claims dynamic or exploit coverage for static checkouts. |
| Tamper-Evident Audit Trail | Append-only event history with cryptographic hash chain | done | SQLite `events` table links each record with a SHA-256 hash of the previous event. `GET /audit/verify` confirms chain integrity. Tamper-evident limits documented honestly. |
| Scheduled Monitoring | Automated periodic compliance checks | done | Background monitor thread re-scans connected repositories based on configured watch intervals (`/dpdp watch <minutes>`). Never described as "real-time" or "continuous". |
| Policy-as-Code & CI/CD | GitHub Actions integration with SARIF output | done | CLI command `python -m dpdp_lens ci` evaluates policy rules against a baseline, emits SARIF 2.1.0, outputs Markdown step summaries, and exits with code 1 on blocking findings. |
| Dashboard Feed View | Web interface matching Slack triage state | done | Dashboard at `http://localhost:5174` includes Feed view reading `GET /findings`, synchronized via outbox polling. |

---

## 4. Live Demo Readiness & Fallback Plan

| Demo Element | Requirement | Status | Verification & Notes |
|--------------|-------------|--------|----------------------|
| Local Demo Stack | Single command starts all services reliably | done | `./run_demo.sh` re-seeds `demo.db`, binds backend (:8000), frontend (:5173), engine API (:8100), and dashboard (:5174). |
| Offline / Weak Wi-Fi Fallback | Demo survives conference Wi-Fi failures | done | All core engine and dashboard components run locally on `127.0.0.1`. If Slack Socket Mode loses internet connectivity, the entire demo can be presented via the Dashboard Feed and local CLI commands. |
| Cached Fix Replay Mode | Safe fallback if local sandbox encounters timeouts | done | Engine includes pre-verified golden patch replay mode. When triggered, UI and Slack notifications explicitly display "Cached verified patch (replay)" or "Cached golden patch mode". |
| Automated Quality Gates | Comprehensive Playwright test suite validating UI and engine | done | `scripts/run_gates.sh` executes 6 test gates validating scan results, live fixes, children probes, data flow visualization, and error states. |
| Backup Screenshots & Video | Recorded fallback assets in repository | done | High-resolution screenshots of all primary states and error modes stored in `docs/fallback-shots/`. Video recording scheduled before submission. |

---

## 5. Final Pre-Submission Sign-Off

- [x] All 5 required evolve documentation files created in `docs/`:
  - `docs/threat-model.md` (Updated)
  - `docs/demo-script-evolve.md`
  - `docs/video-script-evolve.md`
  - `docs/deck-outline-evolve.md`
  - `docs/submission-checklist-evolve.md`
- [x] Zero em dashes in all newly created and updated documentation files.
- [x] All claims verified against actual codebase implementation.
- [ ] Final video recorded, reviewed for audio clarity, and uploaded.
- [ ] Final slide deck rendered to PDF and inspected on mobile/desktop.
- [ ] Submission links verified in logged-out browser.
