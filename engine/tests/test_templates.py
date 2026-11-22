import shutil

import pytest

from conftest import BACKEND, FRONTEND
from dpdp_lens.fixer.templates import TEMPLATES, V1, V2, V3, V5, V6, V7, V8, PatchError, apply_template

needs_frontend = pytest.mark.skipif(not FRONTEND.is_dir(), reason="no target-app/frontend")


def copy_backend(tmp_path):
    dst = tmp_path / "backend"
    shutil.copytree(BACKEND, dst, ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.log"))
    return dst


def copy_frontend(tmp_path):
    dst = tmp_path / "frontend"
    shutil.copytree(FRONTEND, dst, ignore=shutil.ignore_patterns("node_modules", "dist"))
    return dst


def test_v1_template_patches_the_planted_snippet(tmp_path):
    repo = copy_backend(tmp_path)
    (change,) = apply_template(V1, repo)
    original, patched = change.original, change.patched
    assert change.label == "app/main.py" and "# PLANTED V1" in patched and original != patched
    assert "def list_students_public(admin_user: dict = Depends(get_admin_user)):" in patched
    assert '("aadhaar", "parent_pan")' in patched
    assert (repo / "app/main.py").read_text() == patched
    assert "Depends(get_admin_user)" in patched.split("@app.get(\"/api/admin/students\")")[1]  # same dependency as the admin route


def test_missing_snippet_raises_and_writes_nothing(tmp_path):
    repo = copy_backend(tmp_path)
    main = repo / "app/main.py"
    main.write_text(main.read_text().replace("def list_students_public():", "def renamed():"))
    before = main.read_text()
    with pytest.raises(PatchError, match="found 0"):
        apply_template(V1, repo)
    assert main.read_text() == before


def test_applying_twice_fails_instead_of_guessing(tmp_path):
    repo = copy_backend(tmp_path)
    apply_template(V1, repo)
    with pytest.raises(PatchError):
        apply_template(V1, repo)


def test_v3_template_moves_the_log_call_after_the_insert(tmp_path):
    repo = copy_backend(tmp_path)
    (change,) = apply_template(V3, repo)
    original, patched = change.original, change.patched
    assert 'logger.info("signup email=%s aadhaar=%s"' not in patched and "# PLANTED V3" in patched
    lines = patched.splitlines()
    insert = lines.index("    student_id = db.insert_student(student_data)")
    assert lines[insert + 1] == '    logger.info("signup ok user_id=%s", student_id)'
    assert patched.count("logger.info(") == original.count("logger.info(")  # one call out, one call in


@pytest.mark.parametrize("which", [0, 1])
def test_v3_writes_nothing_if_either_snippet_is_missing(tmp_path, which):
    repo = copy_backend(tmp_path)
    main = repo / "app/main.py"
    old = V3.edits[which][2]
    main.write_text(main.read_text().replace(old, old.replace("logger.info", "logger.debug").replace("insert_student", "add_student")))
    before = main.read_text()
    with pytest.raises(PatchError, match="found 0"):
        apply_template(V3, repo)
    assert main.read_text() == before  # the other edit was not applied either


@needs_frontend
def test_v5_template_patches_both_frontend_files(tmp_path):
    fe = copy_frontend(tmp_path)
    changes = apply_template(V5, {"backend": None, "frontend": fe})
    assert [c.label for c in changes] == ["frontend/index.html", "frontend/src/App.jsx"]
    html, jsx = (c.patched for c in changes)
    assert "fbevents.js" not in html and "# PLANTED V5" not in html and "PLANTED V5 (fixed" in html
    assert jsx.count("function loadTrackingPixel()") == 1 and "if (e.target.checked) loadTrackingPixel()" in jsx
    assert jsx.index("function loadTrackingPixel()") < jsx.index("export default function App()")
    assert (fe / "index.html").read_text() == html


@needs_frontend
@pytest.mark.parametrize("which", [0, 2])  # a snippet missing in the first file, then in the second
def test_v5_writes_nothing_if_any_snippet_is_missing(tmp_path, which):
    fe = copy_frontend(tmp_path)
    _, file, old, _ = V5.edits[which]
    (fe / file).write_text((fe / file).read_text().replace(old, "// changed\n"))
    before = {f: (fe / f).read_text() for f in ("index.html", "src/App.jsx")}
    with pytest.raises(PatchError, match="found 0"):
        apply_template(V5, {"backend": None, "frontend": fe})
    assert {f: (fe / f).read_text() for f in before} == before  # all or nothing, across files


def test_frontend_template_without_a_frontend_folder_is_an_error():
    with pytest.raises(PatchError, match="no frontend folder"):
        apply_template(V5, {"backend": None, "frontend": None})
    with pytest.raises(PatchError, match="no frontend folder"):
        apply_template(V5, "/tmp")  # a bare path means backend only


def test_template_registry():
    assert TEMPLATES["api_pii_exposure"] is V1 and V1.golden_id == "V1" and V1.scanner == "api_scan"
    assert TEMPLATES["log_pii"] is V3 and V3.golden_id == "V3" and V3.scanner == "log_scan"
    assert TEMPLATES["tracker_before_consent"] is V5 and V5.scanner == "browser_scan"
    assert V5.needs_frontend and not V1.needs_frontend and not V3.needs_frontend


def test_v2_template_adds_the_owner_or_admin_check_before_the_lookup(tmp_path):
    repo = copy_backend(tmp_path)
    (change,) = apply_template(V2, repo)
    body = change.patched.split("def get_student(student_id: int, user=Depends(get_current_user)):")[1].split("@app.")[0]
    assert body.index('user["id"] != student_id') < body.index("db.get_student(student_id)") and "HTTP_403_FORBIDDEN" in body


def test_v8_template_requires_a_parent_pan_under_18(tmp_path):
    repo = copy_backend(tmp_path)
    (change,) = apply_template(V8, repo)
    assert change.patched.startswith("import os\nimport re\n") and "if req.age < 18 and not (req.parent_pan and re.fullmatch(" in change.patched
    assert "no parental consent check" not in change.patched and "status_code=422" in change.patched


def test_v7_template_hard_deletes_and_stops_copying_to_the_backup_table(tmp_path):
    repo = copy_backend(tmp_path)
    (change,) = apply_template(V7, repo)
    assert change.label == "app/db.py" and "INSERT INTO students_backup" not in change.patched
    assert 'DELETE FROM students WHERE id=?' in change.patched and "SET is_deleted=1" not in change.patched
    assert "PLANTED V7 (fixed" in change.patched


@needs_frontend
def test_v6_template_unticks_the_box_and_drops_marketing(tmp_path):
    fe = copy_frontend(tmp_path)
    (change,) = apply_template(V6, {"backend": None, "frontend": fe})
    assert change.label == "frontend/src/App.jsx"
    assert "useState(false)" in change.patched and "<span>I agree to the Terms</span>" in change.patched
    assert "marketing messages" not in change.patched


@pytest.mark.parametrize("template", [V2, V7, V8])
def test_new_backend_templates_write_nothing_if_a_snippet_is_missing(tmp_path, template):
    repo = copy_backend(tmp_path)
    for _, file, old, _ in template.edits[-1:]:
        path = repo / file
        path.write_text(path.read_text().replace(old, "# changed\n"))
    before = {f: (repo / f).read_text() for f in ("app/main.py", "app/db.py")}
    with pytest.raises(PatchError, match="found 0"):
        apply_template(template, repo)
    assert {f: (repo / f).read_text() for f in before} == before


def test_registry_has_all_seven_fixes():
    assert set(TEMPLATES) == {"api_pii_exposure", "api_idor", "log_pii", "tracker_before_consent", "consent_bundled",
                              "erasure_incomplete", "children_no_parental_consent"}
    assert (V2.scanner, V6.scanner, V7.scanner, V8.scanner) == ("idor_probe", "browser_scan", "erasure_scan", "children_scan")
    assert V6.needs_frontend and not (V2.needs_frontend or V7.needs_frontend or V8.needs_frontend)
