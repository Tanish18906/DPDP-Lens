# Slide Deck Outline: DPDP Lens EVOLVE

Format: 10 to 12 slide PDF presentation.
Tone: Technical, rigorous, transparent, legally accurate.
Rules: No em dashes. Keep 7 words per line or less where possible.

---

## Slide 1: Title & Vision
- **Header**: DPDP Lens
- **Subheader**: Cross-Layer DPDP Compliance Auditor and Verified Remediation
- **Tagline**: Does your application do what your privacy notice says?
- **Metadata**: Hack-a-Sol 5.0 | IIIT Naya Raipur | Track: Cyber Security (CS-01)
- **Team**: Tanish Mishra and Anmol

---

## Slide 2: The Regulatory Urgency (DPDP Act 2023)
- **Header**: The 2027 Cliff
- **Key Facts**:
  - Main duties under DPDP Act 2023 and Rules 2025 take effect 13 May 2027.
  - Statutory penalties up to Rs 250 crore for failure to maintain reasonable security safeguards (Section 8(5)).
  - Up to Rs 200 crore for failure to report breaches or mishandling children's data (Section 9).
  - Most early-stage teams have zero privacy engineering staff.
- **The Core Problem**: Disconnect between published privacy notices and actual engineering reality in code, databases, and third-party trackers.

---

## Slide 3: The Gap: Siloed Scanners vs Legal Reality
- **Header**: Why Existing Tools Fall Short
- **Comparison**:
  - Generic SAST / Linters: Flag generic vulnerabilities without mapping to statutory DPDP obligations or Indian identity artifacts (Aadhaar, PAN).
  - Standalone Consent SaaS: Manages cookie banners on websites without verifying if backend APIs or databases honor consent withdrawal.
- **Our Solution**:
  - Cross-layer auditing across four tiers: Database, Code & Config, Running APIs, and Browser.
  - Notice vs Runtime Truth: Compares declared notice fields against observed data flows.

---

## Slide 4: Architecture Overview
- **Header**: System Architecture
- **Components**:
  - **Front Doors**:
    - Slack Bot (Bolt Socket Mode, zero inbound firewall exposure).
    - GitHub Actions CI (`dpdp_lens ci` with SARIF 2.1.0 and Step Summaries).
    - Web Dashboard (:5174 Feed with real-time outbox synchronization).
  - **Engine API (:8100)**:
    - Deterministic scanners (26 checks across 7 layers).
    - SQLite finding store with SHA-256 tamper-evident audit hash chain.
    - Fix verification sandbox running isolated checks on temporary copies.

---

## Slide 5: Determinism vs Machine Learning
- **Header**: Zero Hallucinations: 100% Deterministic Engine
- **What is Deterministic**:
  - **Detection**: Python AST parsing, checksum validation (Verhoeff algorithm for Aadhaar, entity structure for PAN), regex patterns, and OpenAPI route analysis.
  - **Policy Engine**: Explicit YAML policy-as-code evaluating pass, warn, or block rules.
  - **Remediation**: Structural patch templates proven against known violation archetypes.
  - **Verification**: Re-scan pass plus test suite pass.
- **What is NOT in the loop**:
  - No LLMs or non-deterministic ML models in the scan, triage, or fix pipeline.
  - Audit decisions and findings are reproducible and explainable.

---

## Slide 6: What Was Built During Hackathon vs Pre-Existing
- **Header**: Built in 34 Hours
- **Hackathon Timeline (Sunday 20:00 to Tuesday 06:00)**:
  - 100% of code written during the event across git branches.
  - **Core Engine**: 19 statutory checks, locator engine, and HTML/PDF report generators.
  - **Synthetic Target (TutorNest)**: Complete FastAPI + SQLite educational demo with 15 planted violation archetypes.
  - **EVOLVE Extensions**:
    - Slack bot front door with interactive Block Kit finding cards.
    - SQLite finding store with stable IDs (`DPDP-001`) and triage state machine.
    - Append-only SHA-256 audit hash chain.
    - Policy-as-code evaluator and GitHub Actions CI runner with SARIF.
    - Dashboard Feed view with outbox synchronization.
    - Scheduled monitoring thread with drift detection.

---

## Slide 7: Live Product Walkthrough (Screenshots Needed)
- **Header**: Developer Front Door: Slack & Triage
- **Screenshots Needed**:
  - 1. **Slack Connect**: `/dpdp connect` output with transparent coverage badge: "static checks only (16 of 26)".
  - 2. **Finding Card**: Interactive Block Kit card showing finding `DPDP-014` (`log_pii`), severity badge, and DPDP clause citation (Act s8(5), Rule 6(1)(a)).
  - 3. **Triage Reason Modal**: Modal requiring justification (1 to 300 chars, PII-checked) when marking False Positive or Won't Fix.
  - 4. **Approver Gate**: Ephemeral rejection ("Not allowed: only approvers can do this.") when non-authorized user clicks actions.

---

## Slide 8: The Core Proof: Verified Remediation
- **Header**: We Do Not Just Flag; We Prove the Fix
- **Screenshots Needed**:
  - 1. **Verification Thread**: Thread reply in Slack showing unified diff and verification results.
  - 2. **Verification Log**: Execution log demonstrating the 5 sandbox steps: temp clone checkout, seed temp database, apply patch, re-scan pass, test suite pass.
  - 3. **Status Update**: Finding status flipping from Open to Fixed.
  - 4. **Cached Fallback Transparency**: Clear amber badge "Cached verified patch (replay)" shown when infrastructure limits trigger cached mode.

---

## Slide 9: Governance: Dashboard Feed & Tamper-Evident Audit
- **Header**: Continuous Compliance Governance
- **Screenshots Needed**:
  - 1. **Dashboard Feed**: Table view at `http://localhost:5174` displaying synchronized findings, status tabs, and health pills.
  - 2. **Audit Verification Output**: Terminal executing `curl /audit/verify` returning `{"ok": true, "checked": N, "first_bad": null}`.
  - 3. **CI Summary**: GitHub PR Step Summary showing policy decision FAIL, blocking finding table, and SARIF annotations.

---

## Slide 10: Honest Limits and Safety Boundaries
- **Header**: Security & Architectural Limits
- **Clear Engineering Boundaries**:
  - **Static Only for Connected Repos**: Connected GitHub repositories run static analysis (16 of 26 checks). Untrusted remote code is never executed during scans.
  - **Fix Sandbox Scope**: Code execution during fix verification is strictly restricted to allowlisted `DPDP_FIX_REPOS`.
  - **Tamper-Evident, Not Tamper-Proof**: Audit hash chain detects modifications, but an attacker with direct SQLite write access can rewrite the local file.
  - **Client Token Scope**: `VITE_DPDP_TOKEN` is compiled into the browser bundle for demo purposes; engine binds strictly to localhost.
  - **Readiness, Not Certification**: Tool evaluates technical readiness against selected DPDP rules; does not replace formal legal counsel.

---

## Slide 11: Attribution & Tool Disclosure
- **Header**: Open Source Credits & AI Disclosure
- **AI Tools Used (per Rulebook)**:
  - Claude Code (Anthropic) and Antigravity (Google DeepMind) used for scaffolding, test generation, and documentation drafting.
- **Open Source Libraries**:
  - FastAPI, Uvicorn, Pydantic, HTTPX, PyJWT, pytest.
  - Slack Bolt and Slack SDK (MIT License).
  - PyYAML, Playwright, Python-Stdnum (Verhoeff checksum).
  - Tracker Domain Classification: Disconnect `services.json` (CC BY-NC-SA 4.0).
  - SARIF Schema 2.1.0 (OASIS Open).

---

## Slide 12: Summary & Next Steps
- **Header**: Summary: DPDP Compliance for Developers
- **Key Takeaways**:
  - 1. Cross-layer visibility across database, code, API, and browser.
  - 2. Deterministic, evidence-backed findings mapped to Act sections and Rules.
  - 3. Verified remediation tested in isolated sandboxes.
  - 4. Native Slack and CI/CD integration with tamper-evident audit logs.
- **Next Steps**:
  - Containerized gVisor / Docker sandboxes for arbitrary repository fixes.
  - Asymmetric cryptographic signing of audit logs and PDF reports.
  - Continuous eBPF / OpenTelemetry runtime tracing.
- **Closing**: "Readiness report, not a compliance certificate. Thank you."
