from pathlib import Path

from dpdp_lens import hints
from dpdp_lens.scanners import frontend_scan
from dpdp_lens.scanners.frontend_scan import classify, observe, scan

CLEAN = Path(__file__).parent / "fixtures" / "clean_app"
TARGET_APP = Path(__file__).resolve().parents[2] / "target-app"


def write(tmp_path, files):
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return tmp_path


def test_classify_known_names_only():
    assert [classify(n) for n in ("name", "user_name", "email", "phoneNumber", "dob", "dateOfBirth", "aadhaar", "parent_pan", "parentPAN", "pan")] == [
        "name", "name", "email", "phone", "dob", "dob", "aadhaar", "parent_pan", "parent_pan", "pan"]
    assert [classify(n) for n in ("age", "password", "company", "span", "username2", "")] == [""] * 6


def test_observe_reads_name_or_id_of_each_control_and_skips_node_modules(tmp_path):
    root = write(tmp_path, {
        "frontend/index.html": '<form>\n<input name="dob" type="date">\n<textarea id="email"></textarea>\n</form>\n',
        "frontend/src/App.jsx": '<select\n  id="phone"\n  onChange={(e) => go(e)}\n>\n<input type="text" id="age" name="age" />\n<input id="aadhaar" onChange={() => 1} />\n',
        "frontend/node_modules/x/i.html": '<input name="aadhaar">'})
    assert observe(root) == [("dob", "frontend:frontend/index.html:2"), ("email", "frontend:frontend/index.html:3"),
                             ("phone", "frontend:frontend/src/App.jsx:2"), ("aadhaar", "frontend:frontend/src/App.jsx:6")]


def test_unclassified_names_go_to_the_ml_hook_and_an_empty_answer_changes_nothing(tmp_path, monkeypatch):
    root = write(tmp_path, {"frontend/index.html": '<input name="guardian_id"><input name="nickname">'})
    assert observe(root) == []
    monkeypatch.setattr(hints, "semantic_hints", lambda names: {"guardian_id": "parent_pan"})
    assert observe(root) == [("parent_pan", "frontend:frontend/index.html:1")]


def test_storage_with_personal_data_is_one_finding_per_file_with_the_setitem_line(tmp_path):
    root = write(tmp_path, {
        "frontend/src/a.jsx": "const x = 1\nfunction f({ name, dob }) {\n  localStorage.setItem('k', JSON.stringify({ name,\n    dob }))\n  sessionStorage.setItem('user_email', email)\n}\n",
        "frontend/src/b.jsx": "localStorage.setItem('theme', 'dark')\nsessionStorage.setItem('token', t)\n"})
    found = scan(root)
    assert [(f.check, f.layer, f.severity, f.evidence.location.file, f.evidence.location.line) for f in found] == [
        ("fe_pii_in_storage", "frontend", "medium", "frontend/src/a.jsx", 3)]
    assert "name, dob" in found[0].severity_reason and found[0].severity_reason.startswith("Medium:")
    assert "localStorage.setItem('k', JSON.stringify({ name, dob }))" in found[0].evidence.masked_sample


def test_clean_control_has_no_frontend_findings_and_still_lists_its_field():
    assert scan(CLEAN) == []
    assert observe(CLEAN) == [("email", "frontend:frontend/src/App.jsx:8")]


def test_target_app_signup_form_and_planted_v13():
    fields = observe(TARGET_APP)
    assert [f for f, _ in fields] == ["name", "email", "phone", "dob", "aadhaar", "parent_pan"]  # age, password, consent are not drift fields
    found = scan(TARGET_APP)
    assert len(found) == 1 and found[0].evidence.location.file == "frontend/src/App.jsx"
    src = (TARGET_APP / "frontend/src/App.jsx").read_text().splitlines()
    assert "localStorage.setItem" in src[found[0].evidence.location.line - 1]
    assert "tu***" not in found[0].model_dump_json()  # code only, no stored value


# ---- block 06 job 2, item A: a storage call in a comment is not a call
def test_storage_calls_in_comments_are_not_findings(tmp_path):
    root = write(tmp_path, {"frontend/src/a.js": '// localStorage.setItem("email", e);\n/* sessionStorage.setItem("aadhaar", a) */\nconst a = 1;\n'})
    assert scan(root) == []


def test_a_real_call_after_a_comment_is_still_found_with_the_right_line(tmp_path):
    root = write(tmp_path, {"frontend/src/a.jsx": '// note\nconst x = "// not a comment";\nlocalStorage.setItem("dob", d); // saved\n'})
    (f,) = scan(root)
    assert f.evidence.location.line == 3 and "dob" in f.evidence.masked_sample and "saved" not in f.evidence.masked_sample
