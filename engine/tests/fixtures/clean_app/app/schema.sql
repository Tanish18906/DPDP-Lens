CREATE TABLE consents (
    id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL,
    purpose TEXT NOT NULL,
    notice_version TEXT NOT NULL,
    given_at TEXT NOT NULL,
    withdrawn_at TEXT
);
