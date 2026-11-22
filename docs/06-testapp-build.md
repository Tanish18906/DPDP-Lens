# 06 Test app build: TutorNest (deliberately vulnerable)

A small tutoring marketplace for school students. It collects data from minors, so DPDP s9 applies. It is ONLY for localhost demos. Never deploy it. All data is synthetic.

Owner: Tanish builds backend V1 to V4 now. Anmol builds the tests, V5 to V8, the signup frontend and the notice page.

## Stack
Backend: FastAPI, stdlib sqlite3, pyjwt, python-stdnum (to generate Verhoeff valid fake Aadhaar), uvicorn on port 8000. Frontend: Vite + React on port 5173 (signup page, simple). Env var TUTORNEST_DB overrides the DB path (the fix loop needs this).

## Layout
    target-app/backend/app/main.py      routes
    target-app/backend/app/db.py        schema and helpers
    target-app/backend/app/auth.py      JWT helpers
    target-app/backend/seed.py          creates demo.db with synthetic data
    target-app/backend/static/notice.html   the public privacy notice
    target-app/frontend/                signup page
    target-app/tests/                   pytest

## Database
students(id, name, email, phone, dob, age, aadhaar, parent_pan, password_hash, role, is_deleted, created_at)
students_backup(same columns, a copy kept on delete)
sessions or none (JWT is stateless)
app_log table is not needed, logs go to a log file.

Seed: 15 students. 4 are under 18. Two normal users with known demo passwords, one admin. Fake data only:
- Aadhaar: random 11 digits starting 2 to 9, then add the Verhoeff check digit with stdnum.verhoeff.calc_check_digit
- PAN: random pattern like ABCPD1234E
- Phone: starts with 6 to 9
- Emails at example.test
- Names are obviously fake.
Passwords stored as bcrypt or sha256 hash (not a planted issue).

## Endpoints (all really work)
- POST /api/signup {name, email, phone, dob, age, aadhaar, parent_pan?, password} creates a student
- POST /api/login {email, password} returns a JWT
- GET /api/me returns the logged in student's own record
- GET /api/admin/students admin only, full list
- DELETE /api/students/{id}
- GET /notice serves static/notice.html
- GET /health

## Planted violations. Keep each in a small obvious place and mark it with a comment `# PLANTED Vn` so the engine's patch templates can find it.

V1 (backend, Tanish now): a public route.

    # PLANTED V1
    @app.get("/api/students")
    def list_students_public():
        rows = db.all_students()   # returns name, phone, dob, aadhaar, parent_pan
        return rows

No auth dependency. Fix template: add the admin dependency and drop aadhaar and parent_pan.

V2 (backend, Tanish now): GET /api/students/{id} requires a login but never checks that the id belongs to the caller.

    # PLANTED V2
    @app.get("/api/students/{student_id}")
    def get_student(student_id: int, user=Depends(current_user)):
        return db.get_student(student_id)

V3 (backend, Tanish now): in signup.

    # PLANTED V3
    logger.info("signup email=%s aadhaar=%s", email, aadhaar)

Fix template: replace with logger.info("signup ok user_id=%s", user_id). The app must configure logging to a file so the leak is real.

V4 (backend, Tanish now): aadhaar and parent_pan stored in plaintext columns (schema above). Nothing to patch in the demo.

V5 (frontend, Anmol): the signup page head loads a tracker before any click.

    <!-- PLANTED V5 -->
    <script async src="https://connect.facebook.net/en_US/fbevents.js"></script>

For the offline safe demo, the engine's browser scan stubs external hosts, but the request is still observed. Fix template: remove the tag and load it only inside the consent handler.

V6 (frontend and notice, Anmol): a consent checkbox that is already checked, with the label "I agree to the Terms and to marketing messages". The notice page lists only name, email and phone and gives no purposes. Mark with `PLANTED V6`.

V7 (backend, Anmol): DELETE sets is_deleted = 1, copies the full row into students_backup, and leaves PII in both tables.

    # PLANTED V7
    db.execute("UPDATE students SET is_deleted=1 WHERE id=?", (student_id,))

V8 (backend, Anmol): signup accepts age 14 with no parent verification step.

    # PLANTED V8  (no parental consent check)

Missing contact: the notice page and the home page have no DPO or grievance contact.

Notice drift: notice.html lists name, email, phone as collected. The app also collects dob, aadhaar, parent_pan and the page sends a request to facebook.com.

## Tests (target-app/tests, pytest, Anmol)
They run against a base URL from an env var (default http://localhost:8000) so the fix loop can point them at the patched copy.
- signup works and returns 201 (after the V1 fix the signup response must still work)
- login works and returns a token
- GET /api/me returns the own record
- GET /api/admin/students with admin token returns the list, without a token returns 401 or 403
- DELETE works for the owner or admin
- These tests must pass BEFORE and AFTER the fixes for V1 and V3. Note: after the V1 fix, the public list must not be required by any test.

## Done criteria
- V1 to V4 and the working endpoints running by Mon 00:30 (Tanish).
- Tests passing by Mon 02:30.
- V5 to V8, notice page and frontend by Mon 05:00 (Anmol, can slide to after the mid eval).
