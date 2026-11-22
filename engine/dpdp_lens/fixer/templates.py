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

TEMPLATES = {t.check: t for t in (V1, V3, V5)}


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
