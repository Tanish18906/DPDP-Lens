"""Deterministic patch templates, keyed by check id. A template matches an exact planted snippet.
If the snippet is not found exactly once, apply_template raises PatchError. It never guesses."""
from dataclasses import dataclass
from pathlib import Path


class PatchError(Exception):
    pass


@dataclass(frozen=True)
class Template:
    check: str
    golden_id: str  # name of the cached golden result, e.g. data/golden/V1.json
    file: str       # relative to the app folder
    old: str        # exact text to replace
    new: str


V1 = Template(
    check="api_pii_exposure",
    golden_id="V1",
    file="app/main.py",
    old='''# PLANTED V1
@app.get("/api/students")
def list_students_public():
    rows = db.all_students()   # returns name, phone, dob, aadhaar, parent_pan
    return rows
''',
    new='''# PLANTED V1
@app.get("/api/students")
def list_students_public(admin_user: dict = Depends(get_admin_user)):
    rows = db.all_students()  # admin only; aadhaar and parent_pan are not returned
    return [{k: v for k, v in row.items() if k not in ("aadhaar", "parent_pan")} for row in rows]
''')

TEMPLATES = {V1.check: V1}


def apply_template(template: Template, repo) -> tuple[str, str]:
    """Patch template.file under repo. Returns (original, patched) text. Writes nothing if the snippet is missing."""
    path = Path(repo) / template.file
    try:
        original = path.read_text()
    except OSError as e:
        raise PatchError(f"cannot read {template.file}: {e}") from e
    found = original.count(template.old)
    if found != 1:
        raise PatchError(f"snippet for {template.golden_id} must appear exactly once in {template.file}, found {found}")
    patched = original.replace(template.old, template.new)
    path.write_text(patched)
    return original, patched
