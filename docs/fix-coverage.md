# Fix Coverage

Automated and verified fix coverage across all 19 DPDP Lens checks.

Clauses map to the Digital Personal Data Protection Act 2023 and the DPDP Rules 2025.
Fixes are deterministic and idempotent (no LLM, no ML).
Verification runs in an isolated sandbox copy of the application repository.

## Check Fix Coverage Matrix

| Check ID | Layer | Fix Available | What Patch Does | What Is Verified | What Is Not Verified |
|---|---|---|---|---|---|
| `api_pii_exposure` | api | yes | Adds authentication and authorization dependency on unprotected routes; restricts returned fields to authenticated caller. | Live sandbox re-scan confirms endpoint requires auth; pytest suite passes; score increases. | Does not modify underlying database schema or storage layer access control. Frontend not tested with auth. |
| `api_idor` | api | yes | Injects owner verification check comparing path parameter ID with authenticated session user ID. | Live sandbox probe confirms cross-tenant access returns 403; test suite passes. | Does not configure multi-tenant RBAC policies or external IdP roles beyond owner check. |
| `log_pii` | code | yes | Replaces plaintext logging of personal identifiers (email, Aadhaar) with internal user ID and masked token. | Static re-scan clean; tests pass; sandbox log output confirmed free of raw PII; idempotent. | External log shippers and historical log archives not inspected; verify log aggregation pipelines. |
| `db_plaintext_pii` | db | no | None (requires database migration and key management service). | n/a | Column-level database encryption at rest requires manual schema migration and KMS provisioning. |
| `tracker_before_consent` | browser | yes | Defers loading third-party marketing and tracking scripts until affirmative user consent callback fires. | Headless browser re-scan confirms zero third-party network requests prior to consent click. | Does not manage server-side tracking, proxy-based analytics, or third-party script CDN integrity. |
| `consent_bundled` | browser | yes | Unbundles pre-ticked terms and marketing checkboxes into separate, unticked affirmative action inputs. | Headless browser re-scan verifies checkboxes are unticked by default and purpose-specific. | Does not draft or verify legal compliance of privacy notice text and purpose itemization. |
| `erasure_incomplete` | db | yes | Updates delete handler to hard-delete personal records across primary student tables and backup/archive tables. | Live probe confirms deletion removes synthetic data from all tables; test suite passes. | Does not purge offline database backups, disaster-recovery snapshots, or third-party processor erasures. |
| `children_no_parental_consent` | api | yes | Enforces minimum age validation (18) and rejects signups without verifiable parental consent data. | Live probe verifies minor signup fails with 400 when parent verification is absent; tests pass. | Does not integrate third-party adult identity verification or DigiLocker APIs. |
| `missing_contact` | notice | no | None (requires organization-specific DPO appointment and grievance contact info). | n/a | Legal entity contact information, DPO identity, and physical address cannot be synthesized. |
| `notice_drift` | notice | yes* | Reconciles public privacy notice with observed telemetry fields; marks undeclared fields as pending purpose inputs. | Re-scan clean, undeclared fields added to notice, backend tests pass. | *Purposes for collected personal data fields must still be provided by the data owner. |
| `config_secret_committed` | config | yes* | Replaces committed plaintext credentials in `.env` and `docker-compose.yml` with placeholder tokens and `${VAR}` references. Updates `.env.example`. | Static re-scan clean; tests pass; idempotent apply. | *Source code secrets (e.g. `auth.py`) require manual secret rotation and vault injection. The secret was committed and must be treated as leaked: rotate it, even after the patch. Container not built. |
| `config_env_in_image` | config | yes | Comments out `COPY .env` statements in Dockerfiles to prevent baking secrets into container images. | Static re-scan clean; tests pass; idempotent. | Container not built; runtime container secrets mounting (Kubernetes Secrets / Docker Secrets) must be configured in your deployment. |
| `config_container_root` | config | yes | Injects a non-root system user (`appuser`) and switches execution context via `USER appuser` in Dockerfiles. | Static re-scan clean; tests pass; idempotent. | Container not built; host docker daemon capabilities and seccomp profiles not verified. |
| `config_cors_wildcard` | config | yes | Replaces wildcard CORS origins (`*`) with explicit origin whitelist (`http://localhost:5173`, `http://127.0.0.1:5173`). | Static re-scan clean; tests pass; idempotent. | Set your real production frontend origin; reverse-proxy and CDN CORS headers not tested; container not built. |
| `config_debug_enabled` | config | yes | Replaces `DEBUG=true` with `DEBUG=false` in environment configuration files. | Static re-scan clean; tests pass; idempotent. | Container not built; application reload flag in production process manager must be verified manually. |
| `config_db_exposed` | config | yes | Comments out public host database port mappings (`5432:5432`) in container compose manifests. | Static re-scan clean; tests pass; idempotent. | Container not built; compose stack not booted; host firewall and VPC network isolation not verified. |
| `fe_pii_in_storage` | frontend | yes | Removes client-side `localStorage.setItem` calls for sensitive personal identifiers (email, phone, Aadhaar). | Static re-scan clean; tests pass; idempotent. | Frontend not built or tested in browser; client-side state caching must be verified in browser. |
| `consent_not_recorded` | code | no | None (requires explicit consent input on signup form with no default value). | n/a | This check detects a missing consent field, not valid consent. Defaulting consent to True in schema is an empty fix that satisfies the scanner without recording genuine consent; making it required without default breaks existing clients and tests. |
| `consent_no_withdrawal` | api | no | None (requires application-specific withdrawal workflow and data processing cancellation). | n/a | Revoking consent involves multi-service workflow orchestration that cannot be safely synthesized. |

## Two-Line Fix Verification Output

Every fix result carries two plain lines in the fields already displayed by the Slack bot (in diff replies) and the dashboard (in the diff viewer, feed, and verification log):

1. **`Verified: <what exactly ran: re-scan clean, no new findings, backend tests pass>`**
   Reports the concrete verification steps executed in the isolated sandbox.
2. **`Not verified / you still must: <e.g. rotate the leaked secret and set real values in your environment; set your real CORS origin; frontend not built or tested; container not built>`**
   Plainly states what was not verified and what human action is required. If frontend or container was not run, it is explicitly reported (never implied).

### Secret Fix Warning

For every committed secret fix (`config_secret_committed`), the output explicitly states:
> `the secret was committed and must be treated as leaked: rotate it, even after the patch; set real values in your environment; container not built`

## Connected Repo Static Scan Coverage

When a GitHub repository is connected for static analysis (e.g. via Slack `/dpdp connect` or CI mode), DPDP Lens executes the 9 static scanners across code, configuration, and frontend files.

On the reference TutorNest target app:
- Total static findings: 11 findings (baseline score: 60)
- Automated verified fixes: 9 findings
- Unfixed findings: 2 findings (`config_secret_committed` in `backend/app/auth.py` and `consent_not_recorded` in `backend/app/main.py`)

### Rationale for the Two Unfixed Findings

1. **`config_secret_committed` in `backend/app/auth.py` (`fix.available = False`)**:
   Hardcoded secrets in application source code (`SECRET_KEY = "..."`) require deliberate cryptographic secret rotation and environment variable injection (`os.getenv`) in the host deployment platform. Generating a fake placeholder in source code could break runtime token signing without providing a real credential management solution. DPDP Lens flags the vulnerability honestly and requires human remediation.

2. **`consent_not_recorded` in `backend/app/main.py` (`fix.available = False`)**:
   This check detects a missing consent field, not valid consent. Making the field required with no default breaks existing API clients and tests (which do not supply this field), while defaulting the field to `True` in schema would be an empty fix that only satisfies the scanner without recording genuine consent. The finding is kept open with clear guidance that the client form must collect and send an explicit consent value.

## Verification Protocol

Every fix marked as available must pass the `verify_fix` protocol in an isolated sandbox before the dashboard or Slack bot presents the "Verified Fixed" status:

1. **Isolation**: A scratch copy of the repository and database is initialized in a temporary directory. The original repository is never modified.
2. **Template Application**: Deterministic replacement edits are applied. If expected anchors are missing, `PatchError` is raised immediately without partial edits.
3. **Compilation Check**: Patched Python files are verified with `py_compile.compile`.
4. **Idempotency**: Applying the patch a second time must produce zero modifications.
5. **Re-scan**: The scanner runs against the patched sandbox copy. The targeted finding must be eliminated.
6. **No Regressions**: Re-scan confirms no new static findings are introduced.
7. **Test Suite**: The application test suite (`pytest`) runs against the sandbox and must pass completely.
8. **Unified Diff & Notes**: A standard unified diff is generated containing the exact diff and the two plain lines (`Verified: ...` and `Not verified / you still must: ...`).

## Limits and Constraints

- **Known Patterns**: Fix templates operate on verified structural patterns and known idioms, not arbitrary source code generation.
- **Config-Only Boot Policy**: Configuration-only fixes (such as `.env` and `docker-compose.yml` edits) are verified via static re-scan, syntax checks, and test suites; they do not boot full container clusters in the lightweight audit sandbox.
- **Human Approval**: Automated fixes require explicit approval from authorized Slack users (`SLACK_APPROVERS`) before landing in production repositories.
