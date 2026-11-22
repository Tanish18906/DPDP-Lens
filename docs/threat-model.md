# Threat model: DPDP Lens

Draft by Tanish and Anmol. Scope: the auditor itself and its demo setup. The deliverable the Cyber track may ask for. Confirm the exact format with the organisers and reshape this to fit.

## 1. What we protect
- Personal data seen during a scan (even though the demo data is synthetic, the tool must treat it as real).
- The target app's source and database during a fix.
- The integrity of findings and of "verified" status (a false "verified" is worse than no fix).
- The machine running the auditor.

## 2. System and trust boundaries
Dashboard (browser) to Engine API (localhost :8100) to Target app (localhost :8000) and to the sandbox copy. Third party hosts appear only as request targets from the target page and are stubbed in the demo.
Boundary 1: dashboard to engine. Boundary 2: engine to target. Boundary 3: engine to sandbox processes. Boundary 4: the machine to the internet (we avoid crossing it).

## 3. Assumptions
- Runs on a developer laptop, localhost only.
- Scans only apps the operator owns.
- Demo data is synthetic.

## 4. Threats and mitigations (STRIDE style)
| # | Threat | Type | Mitigation |
|---|--------|------|------------|
| T1 | Auditor stores or shows raw PII in evidence, logs or reports | Information disclosure | Masking at the source, evidence stores masked samples only, tests check that no raw Aadhaar or PAN appears in the JSON |
| T2 | Engine API is called by another site or local process and triggers scans | Spoofing, tampering | Bind to 127.0.0.1, CORS limited to the dashboard origin for non demo use, no auth needed for the hackathon but documented as a limit |
| T3 | Scanning a target the operator does not own | Misuse | Targets restricted to localhost and private ranges by an allow check in the engine, README states the scope |
| T4 | Patch breaks the app or damages data | Tampering | Patch only a temp copy with a copied DB, never the original, verification needs re-scan pass and the tests to pass |
| T5 | Sandbox process left running or port conflict | Denial of service | Free port per run, process group kill in a finally block, timeouts |
| T6 | Malicious target code executed by the fix loop (running the target's backend) | Elevation of privilege | Only run the demo target in the demo. Documented limit: run the auditor on code you trust, ideally in a container |
| T7 | Destructive probes in scans | Tampering | GET only for probes except the controlled erasure probe on a synthetic user, no payload fuzzing, request caps |
| T8 | A false "verified" status | Repudiation, integrity | The status is computed from the re-scan result and pytest exit code, never set by hand, cached mode is labelled |
| T9 | Supply chain: malicious dependency or data file | Tampering | Small pinned dependency set, licences credited, services.json committed with source noted, no install scripts run at demo time |
| T10 | LLM prompt or data leakage if an LLM explains a fix | Information disclosure | LLM not required, never send raw data, send only code snippets and masked evidence, off by default |
| T11 | Secrets in the repo (API keys, JWT secrets, real credentials) | Information disclosure | .gitignore, demo only secrets clearly marked as demo, no real keys committed |
| T12 | Third party requests leak data when the browser scan loads the page | Information disclosure | External hosts stubbed with page.route, no real data sent, synthetic data only |

## 5. Out of scope and known limits
- No authentication on the engine API in this version.
- Only SQLite and a FastAPI style target are tested.
- Checks are a subset of DPDP duties. A clean scan does not mean compliance.
- No protection against a hostile target app beyond running on localhost.

## 6. What we would do next
Container sandbox for the fix loop, API token for the engine, signed scan reports, more targets and stacks.

## 7. Safe use rules (also in README)
Use only on your own apps. Use synthetic data. Treat reports as sensitive. Never run on production.
