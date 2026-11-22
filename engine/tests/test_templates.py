import pytest

from conftest import BACKEND
from dpdp_lens.fixer.templates import TEMPLATES, V1, PatchError, apply_template


def copy_backend(tmp_path):
    import shutil
    dst = tmp_path / "backend"
    shutil.copytree(BACKEND, dst, ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.log"))
    return dst


def test_v1_template_patches_the_planted_snippet(tmp_path):
    repo = copy_backend(tmp_path)
    original, patched = apply_template(V1, repo)
    assert "# PLANTED V1" in patched and original != patched
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


def test_template_registry():
    assert TEMPLATES["api_pii_exposure"] is V1 and V1.golden_id == "V1"
