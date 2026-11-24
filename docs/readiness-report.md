# DPDP readiness report (block 11)

One printable page per connected repo and stored scan, built from the finding store only (the `scans` row, the findings with their clauses and masked evidence, the audit events and the audit chain check). The title is "DPDP readiness report". It is based on automated checks, not legal advice and not a compliance certificate.

## Routes

| Route | Access | Answer |
|---|---|---|
| `GET /repos/{id}/report?scan_id=` | `X-DPDP-Token` header, or a signed link (`&sig=`) | HTML with a print stylesheet and a "Print / Save as PDF" button. Default scan: the latest complete one, else the latest of any status |
| `GET /repos/{id}/report?format=json` | same | the same data as JSON |
| `POST /repos/{id}/report-link` | token | `{url, scan_id, expires_in, summary}`. `url` is relative to the engine: `/repos/1/report?scan_id=S-004&sig=...` |

A browser cannot send the token header, so it opens the signed link. The link is an HMAC (SHA-256) with `DPDP_API_TOKEN`, valid 15 minutes, bound to one repo id and one scan id. A tampered, expired, or wrong-repo or wrong-scan link is 403, and so is any link when the engine has no `DPDP_API_TOKEN`. No header and no link is 401. Creating a link writes the audit event `report_link_created`.

## What is in it

Repo, branch, commit, scan id, date, policy and scanner version. Scope: static or full, how many of the 26 checks ran, which did not and why, scan errors. Health and its reasons. Counts by severity and by status. A findings table, critical first: id, severity, title with the masked evidence, the DPDP clauses, file:line, proof (static or live), status with reason and actor, and the fix result with exactly what was verified (live sandbox run or cached replay, re-scan, app tests passed or not run, score change). The audit chain check (intact, or the first bad event) and the number of events for the repo. Limits.

An incomplete or failed scan, a newer failed scan, or an Unknown health is said in the first lines and the report never reads as clean. Evidence is the masked text the scanners stored and is masked again when the page is made.

## Where to open it

- Slack: `/dpdp report` (approvers).
- Dashboard: the **Report** button in the Feed header, once a repository is chosen.
