"""Deterministic patch templates, keyed by check id. A template matches exact planted snippets, in one or more files.
If any snippet is not found exactly once, apply_template raises PatchError and writes nothing. It never guesses."""
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple


class PatchError(Exception):
    pass


@dataclass(frozen=True)
class Template:
    check: str
    golden_id: str                                  # name of the cached golden result, e.g. data/golden/V1.json
    scanner: str                                    # the scanner that must have run in the re-scan
    edits: tuple[tuple[str, str, str, str], ...]    # (root, file, old, new). root is "backend" or "frontend".

    @property
    def needs_frontend(self) -> bool:
        return any(root == "frontend" for root, *_ in self.edits)


class Change(NamedTuple):
    label: str      # path shown in the diff: app/main.py, frontend/index.html
    original: str
    patched: str


V1 = Template(
    check="api_pii_exposure", golden_id="V1", scanner="api_scan",
    edits=(("backend", "app/main.py", '''# PLANTED V1
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
    check="log_pii", golden_id="V3", scanner="log_scan",
    edits=(("backend", "app/main.py", '''    # PLANTED V3
    logger.info("signup email=%s aadhaar=%s", req.email, req.aadhaar)

''', '''    # PLANTED V3 (fixed: no personal data in the log, only the user id, see below)

'''), ("backend", "app/main.py", '''    student_id = db.insert_student(student_data)
''', '''    student_id = db.insert_student(student_data)
    logger.info("signup ok user_id=%s", student_id)
''')))

PIXEL_LOADER = '''// Marketing pixel: loaded only after the user ticks the consent box, never when the page opens.
function loadTrackingPixel() {
  if (document.getElementById('fb-pixel')) return
  const script = document.createElement('script')
  script.id = 'fb-pixel'
  script.async = true
  script.src = 'https://connect.facebook.net/en_US/fbevents.js'
  document.head.appendChild(script)
}

'''

V5 = Template(
    check="tracker_before_consent", golden_id="V5", scanner="browser_scan",
    edits=(("frontend", "index.html", '''    <!-- PLANTED V5 -->
    <script async src="https://connect.facebook.net/en_US/fbevents.js"></script>
''', '''    <!-- PLANTED V5 (fixed: the tracker loads only after the consent box is ticked, see src/App.jsx) -->
'''), ("frontend", "src/App.jsx", "export default function App() {\n", PIXEL_LOADER + "export default function App() {\n"),
        ("frontend", "src/App.jsx", "                  onChange={(e) => setAgreed(e.target.checked)}\n",
         '''                  onChange={(e) => {
                    setAgreed(e.target.checked)
                    if (e.target.checked) loadTrackingPixel()
                  }}
''')))

# Same rule as the delete route: the owner or an admin.
V2 = Template(
    check="api_idor", golden_id="V2", scanner="idor_probe",
    edits=(("backend", "app/main.py", '''def get_student(student_id: int, user=Depends(get_current_user)):
    student = db.get_student(student_id)
''', '''def get_student(student_id: int, user=Depends(get_current_user)):
    if user["role"] != "admin" and user["id"] != student_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot read other student")
    student = db.get_student(student_id)
'''),))

# Partial on purpose: a parent PAN in the right format is only a stand-in for verifying an identifiable adult (Rule 10).
V8 = Template(
    check="children_no_parental_consent", golden_id="V8", scanner="children_scan",
    edits=(("backend", "app/main.py", "import os\nimport logging\n", "import os\nimport re\nimport logging\n"),
           ("backend", "app/main.py", '''    # PLANTED V8  (no parental consent check)
    # The application accepts minor signup without verifying identifiable parental consent
''', '''    # PLANTED V8 (fixed: under 18 needs a parent PAN. Format check only, the parent is not verified, see Rule 10)
    if req.age < 18 and not (req.parent_pan and re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", req.parent_pan)):
        raise HTTPException(status_code=422, detail="Under 18: a valid parent PAN is required")
''')))

# Hard delete: the row is removed and nothing is copied to students_backup.
V7 = Template(
    check="erasure_incomplete", golden_id="V7", scanner="erasure_scan",
    edits=(("backend", "app/db.py", "    # PLANTED V7\n", "    # PLANTED V7 (fixed: the row is deleted, nothing is copied to students_backup)\n"),
           ("backend", "app/db.py", '''    row_dict = dict(row)
    cursor.execute("""
        INSERT INTO students_backup (name, email, phone, dob, age, aadhaar, parent_pan, password_hash, role, is_deleted, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (
        row_dict["name"], row_dict["email"], row_dict["phone"], row_dict["dob"],
        row_dict["age"], row_dict["aadhaar"], row_dict["parent_pan"],
        row_dict["password_hash"], row_dict["role"], row_dict["created_at"]
    ))
    cursor.execute("UPDATE students SET is_deleted=1 WHERE id=?", (student_id,))
''', '''    cursor.execute("DELETE FROM students WHERE id=?", (student_id,))
''')))

# Fixes the box only (unticked, terms only). The notice still does not list every field, so notice_drift stays open.
V6 = Template(
    check="consent_bundled", golden_id="V6", scanner="browser_scan",
    edits=(("frontend", "src/App.jsx", "const [agreed, setAgreed] = useState(true)", "const [agreed, setAgreed] = useState(false)"),
           ("frontend", "src/App.jsx", "<span>I agree to the Terms and to marketing messages</span>", "<span>I agree to the Terms</span>")))

TEMPLATES = {t.check: t for t in (V1, V2, V3, V5, V6, V7, V8)}


def apply_template(template: Template, roots) -> list[Change]:
    """Patch the files under roots ({"backend": Path, "frontend": Path}, or one path for a backend-only template).
    Every edit must match exactly once. Nothing is written unless all of them do."""
    if not isinstance(roots, dict):
        roots = {"backend": roots}
    state: dict[tuple[str, str], list[str]] = {}  # (root, file) -> [original, patched so far]
    for root, file, old, new in template.edits:
        if (root, file) not in state:
            if roots.get(root) is None:
                raise PatchError(f"no {root} folder to patch for {template.golden_id}")
            try:
                text = (Path(roots[root]) / file).read_text()
            except OSError as e:
                raise PatchError(f"cannot read {file}: {e}") from e
            state[(root, file)] = [text, text]
        found = state[(root, file)][1].count(old)
        if found != 1:
            raise PatchError(f"snippet for {template.golden_id} must appear exactly once in {file}, found {found}:"
                             f" {old.strip().splitlines()[0][:70]}")
        state[(root, file)][1] = state[(root, file)][1].replace(old, new)
    changes = []
    for (root, file), (original, patched) in state.items():
        (Path(roots[root]) / file).write_text(patched)
        changes.append(Change(file if root == "backend" else f"{root}/{file}", original, patched))
    return changes
