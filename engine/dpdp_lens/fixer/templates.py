"""Deterministic patch templates, keyed by check id. A template matches exact planted snippets.
If any snippet is not found exactly once, apply_template raises PatchError and writes nothing. It never guesses."""
from dataclasses import dataclass
from pathlib import Path


class PatchError(Exception):
    pass


@dataclass(frozen=True)
class Template:
    check: str
    golden_id: str                      # name of the cached golden result, e.g. data/golden/V1.json
    file: str                           # relative to the app folder
    edits: tuple[tuple[str, str], ...]  # (old, new) pairs. Each old text must appear exactly once.


V1 = Template(
    check="api_pii_exposure",
    golden_id="V1",
    file="app/main.py",
    edits=(('''# PLANTED V1
@app.get("/api/students")
def list_students_public():
    rows = db.all_students()   # returns name, phone, dob, aadhaar, parent_pan
    return rows
''', '''# PLANTED V1
@app.get("/api/students")
def list_students_public(admin_user: dict = Depends(get_admin_user)):
    rows = db.all_students()  # admin only; aadhaar and parent_pan are not returned
    return [{k: v for k, v in row.items() if k not in ("aadhaar", "parent_pan")} for row in rows]
'''),))

# The user id only exists after the insert, so the log call moves there.
V3 = Template(
    check="log_pii",
    golden_id="V3",
    file="app/main.py",
    edits=(('''    # PLANTED V3
    logger.info("signup email=%s aadhaar=%s", req.email, req.aadhaar)

''', '''    # PLANTED V3 (fixed: no personal data in the log, only the user id, see below)

'''), ('''    student_id = db.insert_student(student_data)
''', '''    student_id = db.insert_student(student_data)
    logger.info("signup ok user_id=%s", student_id)
''')))

TEMPLATES = {t.check: t for t in (V1, V3)}


def apply_template(template: Template, repo) -> tuple[str, str]:
    """Patch template.file under repo. Returns (original, patched) text. Writes nothing unless every edit matches once."""
    path = Path(repo) / template.file
    try:
        original = path.read_text()
    except OSError as e:
        raise PatchError(f"cannot read {template.file}: {e}") from e
    patched = original
    for old, new in template.edits:
        found = patched.count(old)
        if found != 1:
            raise PatchError(f"snippet for {template.golden_id} must appear exactly once in {template.file}, found {found}:"
                             f" {old.strip().splitlines()[0][:70]}")
        patched = patched.replace(old, new)
    path.write_text(patched)
    return original, patched
