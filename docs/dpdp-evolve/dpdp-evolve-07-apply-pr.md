# Block 07: approve to branch and PR, with rollback record (STRETCH, first thing to cut)

Read dpdp-evolve-00-master.md first. Needs 01b and 03. Only for repos in DPDP_FIX_REPOS (the demo repo). Direct deployment is out of scope. Never push to the default branch.

## Flow
Verified fix in Slack, then an "Approve and open PR" button on the card (approvers only, shown only after verified true, not for a cached replay).
1. Re-checkout the exact commit the scan used. Create branch `dpdp-lens/fix-DPDP-014`.
2. `git apply --check` the verified diff, then apply, then commit with message `fix: <title> (DPDP-014)`. Token via GIT_ASKPASS, never argv or URL.
3. Push the branch, open a PR through the GitHub REST API (needs a token with Contents write and Pull requests write on the demo repo only). PR body: what changed, the finding, clauses (likely wording), verification result and its mode (live or cached), "Readiness tool output, review before merging".
4. Record in the store: remediation id, finding, base commit sha, branch, PR url, sha256 of the patch, files changed, test result, who approved (Slack user id), timestamps. Audit events: fix_approved, pr_opened.
5. Rollback: a "Close PR and delete branch" action if the PR is still unmerged (audit event rollback_executed). If merged, say so and give `git revert <merge sha>` instructions with the recorded sha. Do not automate reverting a merged change tonight.

## Tests
Fake GitHub client. Cover: refusal without verified fix, refusal for non-approvers, refusal for repos outside DPDP_FIX_REPOS, patch that does not apply cleanly (no branch pushed), token never in logs, audit events written, patch hash recorded.

## Acceptance
In the demo repo a PR appears from the Slack button, CI runs on it, Feed shows the finding as Fixed after merge and the next scan.

STOP. Hand over per docs/14.
