# 01 Product overview

## Problem statement
Track: Cybersecurity. CS-01 "Full-Stack Data Protection (DPDP) Compliance Auditor". We only have the title, no description, so scope is our interpretation. Mention that openly in the pitch: "The statement gave a title. We read 'full-stack' as database, backend code, running API and browser."

## One line pitch
DPDP Lens audits an app across every layer, proves each finding with evidence mapped to the DPDP Act and Rules, then fixes it on a sandbox copy and verifies the fix by re-scanning and running the app's tests.

## Why this shape
- Audit is the product. The verified fix is the proof that the audit is right. This answers "the title says Auditor, why a fixer?".
- Cross-layer is the differentiator. Existing tools mostly do one layer: website cookie scanners, repo PII scanners, or consent workflow SaaS. We connect the layers.
- Headline extension: Notice vs Runtime Truth. We compare the personal data fields the public privacy notice lists against what the database, the API responses and the browser actually handle. The gap is the finding.

## Market reality (be honest in the pitch)
Not empty. dcomply has a website scanner and repo PII scan. Privado (open source) does CI checks for PII in logs and endpoints. Indian GRC tools (Privy by IDfy, GoTrust, Consentin, Redacto, Sprinto and others) are mostly consent and workflow SaaS. Never say "nobody scans code". Say: "Others check one layer. We prove it across layers and verify the fix."

## What it is NOT
- Not a compliance certificate. It is a readiness report. Main DPDP duties apply from 13 May 2027.
- Not a pentest tool. It only reads our own demo app on localhost with non destructive requests.

## Scope and priority
MUST (nothing else matters if these are missing)
- Target app TutorNest with planted violations
- DB PII scan, API exposure and IDOR probe, PII in logs, pre consent tracker, erasure check
- Finding JSON with evidence and clause for every finding
- 3 verified fixes: V1 (API exposure), V3 (PII in logs), V5 (tracker before consent)
- Dashboard: score, finding detail, before and after, HTML report

SHOULD
- Notice vs Runtime drift detector and its dashboard tab
- Data flow map
- Threat model document
- README declaring AI tools and crediting libraries

STRETCH (only if everything above works)
- SARIF output and CI gate
- Children signup check
- Secrets scan with gitleaks
- 72 hour breach report generator (Rule 7)

Cut order if behind: SARIF, children check, drift detector, browser scan. Never cut the fix and verify loop.

## Judging map
| Criterion | Weight | How we score |
|-----------|--------|--------------|
| Innovation | 25 | Cross layer proof, notice vs runtime drift, verified fixes |
| Technical execution | 25 | Real scanners, sandbox fix loop, tests that pass after the fix |
| Impact | 20 | DPDP penalties up to Rs 250 crore, every Indian startup needs this by May 2027 |
| Track fit | 15 | Cyber track, threat model, safe localhost only scope |
| Presentation | 15 | 90 second live story, clean dashboard, honest limits |

## Users (for the pitch)
- A startup CTO who has no privacy team and needs a first readiness check before 2027.
- A student or small team shipping an app that collects data from minors.
- A consultant who needs evidence mapped to clauses, not a questionnaire.

## Success on demo day
In under 2 minutes the judges see: scan runs, 8 findings appear with clause chips, drift panel shows undeclared fields, we click Fix on V1, the diff appears, re-scan passes, tests pass, the score jumps.
