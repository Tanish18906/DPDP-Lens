# Block 05: scheduled monitoring (Session A, after 01b, about 30 to 40 min)

Read dpdp-evolve-00-master.md first. Needs 01b (store, ingest, repo_scan).

We say "scheduled monitoring". Never real-time, never continuous.

## Tasks
1. monitor.py: a `Monitor` with `tick(now)` and a background thread started with the API (env DPDP_MONITOR=1, default on). Inject the clock and the scan function so tests need neither time nor network.
   - For each repo with watch_minutes set and next_run_at <= now and no scan running for it: start one scan with trigger "schedule", then set next_run_at = now + watch_minutes. A missed window (engine was down) runs once, not many times.
   - next_run_at and last error persist in SQLite, so a restart keeps the schedule.
   - One worker at a time per repo, a global cap of 1 concurrent clone and scan. Timeouts reuse repo_scan's.
   - A failed clone or crashed scan is stored as an incomplete or failed scan, an audit event scan_failed or scan_incomplete is recorded, health becomes unknown. It never skips silently and never leaves the previous healthy state in place.
   - Staleness: no complete scan in 2 x watch interval means health unknown with reason "stale".
2. Alert hook: after each scheduled scan call a notifier interface (Slack bot polls via outbox: add outbox kinds `scan_delta` and `health_changed` written by the monitor). Alerts fire on first transition into at_risk or unknown, and on new blocking findings, not on every unchanged scan.
3. API: the watch route from master section 9 already exists in 01b. Add GET /repos/{id}/health reasons for stale and failed streaks if missing.
4. Tests: tick with a fake clock (due, not due, running, missed windows, restart), failure path ends unknown, recovery path, alert dedup, schedule survives reopening the DB.

## Acceptance
`/dpdp watch 1` in Slack makes a re-scan happen about every minute against the real demo repo. Pushing a commit that adds a leak gives a new card on the next tick. Breaking the token gives an Unknown alert once. Engine suite and gates pass.

STOP. Hand over per docs/14.
