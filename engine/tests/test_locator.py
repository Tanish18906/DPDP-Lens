from dpdp_lens.locator import find_column, find_route, find_text
from dpdp_lens.models import Evidence, Finding, Location
from dpdp_lens.runner import app_root_of, locate

MAIN = '''from fastapi import FastAPI
app = FastAPI()

@app.get("/api/students")
def a(): ...

# PLANTED
@app.get("/api/students/{student_id}")
async def b(student_id: int): ...

@app.delete("/api/students/{sid}")
def c(sid: int): ...
'''
DB = '''def init():
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY,
        aadhaar TEXT NOT NULL,
        parent_pan TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students_backup (
        id INTEGER,
        aadhaar TEXT
    )
    """)
'''


def app(tmp_path):
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "main.py").write_text(MAIN)
    (tmp_path / "backend" / "app" / "db.py").write_text(DB)
    (tmp_path / "backend" / "static").mkdir()
    (tmp_path / "backend" / "static" / "notice.html").write_text("<html>\n<h1>Notice</h1>\n<ul>\n<li>Name</li>\n</ul>\n")
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "index.html").write_text('<head>\n<script src="https://connect.facebook.net/x.js"></script>\n')
    (tmp_path / "frontend" / "src" / "App.jsx").write_text('<label>\n<input\n type="checkbox"\n/>\n')
    (tmp_path / "frontend" / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "frontend" / "node_modules" / "pkg" / "index.html").write_text("connect.facebook.net\n")
    return tmp_path


def test_find_route_matches_method_and_normalised_param(tmp_path):
    root = app(tmp_path)
    assert find_route(root, "GET", "/api/students") == ("backend/app/main.py", 4)
    assert find_route(root, "GET", "/api/students/{id}") == ("backend/app/main.py", 8)  # other param name, async def
    assert find_route(root, "DELETE", "/api/students/{x}") == ("backend/app/main.py", 11)
    assert find_route(root, "POST", "/api/students") == ("", 0)


def test_find_column_picks_the_right_table(tmp_path):
    root = app(tmp_path)
    assert find_column(root, "students", "aadhaar") == ("backend/app/db.py", 5)
    assert find_column(root, "students_backup", "aadhaar") == ("backend/app/db.py", 12)
    assert find_column(root, "students", "nope") == ("", 0)


def test_find_text_skips_node_modules_and_never_raises(tmp_path):
    root = app(tmp_path)
    assert find_text(root, "connect.facebook.net", ["frontend/*.html"]) == ("frontend/index.html", 2)
    assert find_text(root, "connect.facebook.net", ["*/node_modules/*"]) == ("", 0)
    assert find_text(tmp_path / "missing", "x", ["*"]) == ("", 0)
    assert find_route(tmp_path / "missing", "GET", "/") == ("", 0)


def f(check, **loc):
    return Finding(id="", check=check, layer="api", severity="high", title="t", explanation="e", clauses=[],
                   evidence=Evidence(kind="http", summary="s", masked_sample=loc.pop("sample", ""), location=Location(**loc)))


def test_locate_fills_each_check_and_rebases_scanner_files(tmp_path):
    root = app(tmp_path)
    repo = root / "backend"
    assert app_root_of(repo) == root.resolve()
    out = {x.check: x.evidence.location for x in locate([
        f("api_pii_exposure", url="http://x/api/students"),
        f("api_idor", url="http://x/api/students/{student_id}"),
        f("erasure_incomplete", table="students"),
        f("db_plaintext_pii", table="students", column="aadhaar, parent_pan"),
        f("tracker_before_consent", sample="https://connect.facebook.net/x.js"),
        f("consent_bundled"), f("missing_contact"), f("notice_drift"),
        f("log_pii", file="app/main.py", line=4)], repo)}
    got = {k: (v.file, v.line) for k, v in out.items()}
    assert got == {
        "api_pii_exposure": ("backend/app/main.py", 4), "api_idor": ("backend/app/main.py", 8),
        "erasure_incomplete": ("backend/app/main.py", 11), "db_plaintext_pii": ("backend/app/db.py", 5),
        "tracker_before_consent": ("frontend/index.html", 2), "consent_bundled": ("frontend/src/App.jsx", 3),
        "missing_contact": ("backend/static/notice.html", 2), "notice_drift": ("backend/static/notice.html", 4),
        "log_pii": ("backend/app/main.py", 4)}
