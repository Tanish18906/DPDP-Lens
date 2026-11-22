"""Scan config. Demo logins for the synthetic TutorNest app only. Scanners read them from here."""

DEMO_USERS = {
    "user_a": {"email": "aarav.sharma@example.test", "password": "StudentPass123!"},
    "user_b": {"email": "diya.patel@example.test", "password": "StudentPass123!"},
    "admin": {"email": "admin@tutornest.test", "password": "AdminPass123!"},
}

FRONTEND_URL = "http://localhost:5173"  # TutorNest signup page, checked by contact_scan when it is running

HTTP_TIMEOUT = 10  # seconds per request
MAX_REQUESTS = 50  # per scanner
