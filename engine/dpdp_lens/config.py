"""Scan config. Demo logins for the synthetic TutorNest app only. Scanners read them from here."""

DEMO_USERS = {
    "user_a": {"email": "aarav.sharma@example.test", "password": "StudentPass123!"},
    "user_b": {"email": "diya.patel@example.test", "password": "StudentPass123!"},
    "admin": {"email": "admin@tutornest.test", "password": "AdminPass123!"},
}

HTTP_TIMEOUT = 10  # seconds per request
MAX_REQUESTS = 50  # per scanner
