# STATUS (Tanish)
- [x] T0 contract and skeleton (commit 391aeb2)
- [x] T1 target backend V1 to V4 (built by Anmol, verified)

## Notes for later
- V3 patch snippet is `logger.info("signup email=%s aadhaar=%s", req.email, req.aadhaar)` in app/main.py. V1 snippet is under `# PLANTED V1` in app/main.py.
- Engine and fix-loop tests must use a temp copy of the DB through TUTORNEST_DB so demo.db stays clean.
- Demo logins: aarav.sharma@example.test and diya.patel@example.test (StudentPass123!), admin@tutornest.test (AdminPass123!). Read them from config, not hard-coded in scanners.
