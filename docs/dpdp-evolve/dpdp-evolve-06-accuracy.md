# Block 06: scanner accuracy (only if time is left after 01 to 05, any session)

Read dpdp-evolve-00-master.md first. Rule: measure first, change second, no accuracy claim without numbers. Detection stays deterministic.

## Step 1: measure (about 30 min, worth doing even if nothing else is)
Create engine/tests/accuracy/ with a labelled corpus: small files per check, each marked positive or negative with the expected finding, plus hard negatives (placeholder secrets like changeme, your-key-here, ${VAR}; numbers that look like Aadhaar or phone but are timestamps or ids; test fixtures; comments and docstrings). Add `python -m dpdp_lens eval` that runs the scanners on the corpus and prints precision and recall per check and overall. Commit the baseline numbers to docs/ACCURACY.md. Include a TutorNest ground truth row: all planted violations found, nothing extra beyond the documented real one (app/auth.py SECRET_KEY).

## Step 2: improve, in this order, each change shown by a number moving
1. Secrets in config_scan: add known token prefixes (AWS access key id AKIA, GitHub ghp_ and github_pat_, Slack xox, Stripe sk_live) and a placeholder suppression list. Never print the full value (masking rule stays).
2. JS and TS: log_pii for console.log and logger calls that include personal data names (README says JS and TS are not scanned for secrets or logs). Use a tolerant tokenizer like frontend_scan's, not a regex over whole files.
3. locator.find_route: add router `prefix` handling (documented limit in locator.py).
4. recognizers.py: check PAN structure beyond the pattern (fourth character is an entity type letter), Aadhaar first digit and Verhoeff stays, phone numbers not inside longer digit runs. Read recognizers.py before changing, keep tests green, add negatives.
5. notice_drift: the `age` field is skipped on purpose (STATUS-tanish decision). Leave it unless Tanish approves a change, because it alters the planted drift definition.
6. Static notice drift for connected repos: declared fields from a notice HTML file in the repo, observed fields from frontend_scan.observe. Must be labelled static and partial.

## Gates
Every change must: not lower recall on the corpus, not add findings to the TutorNest full scan (21, ids unchanged, score 13) unless Tanish approves and gate numbers are updated in the same change, keep run_gates.sh 6 of 6. Update docs/CHECKS.md via the generator.

STOP after step 1 if time is short and report the numbers. Hand over per docs/14.
