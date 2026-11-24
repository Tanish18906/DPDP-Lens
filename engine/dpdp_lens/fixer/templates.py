"""Deterministic patch templates, keyed by check id. A template matches exact planted snippets, in one or more files.
If any snippet is not found exactly once, apply_template raises PatchError and writes nothing. It never guesses."""
import sys
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
    edits: tuple[tuple[str, str, str, str], ...]    # (root, file, old, new). root is "backend", "frontend", or "app_root".
    description: str = ""                           # plain description of the fix
    file_pattern: str = ""                          # optional file pattern to match finding location
    verified_msg: str = ""                          # what exactly ran
    not_verified_msg: str = ""                      # what the human must still do

    @property
    def needs_frontend(self) -> bool:
        return self.scanner == "browser_scan" and any(root == "frontend" for root, *_ in self.edits)


class Change(NamedTuple):
    label: str      # path shown in the diff: app/main.py, frontend/index.html
    original: str
    patched: str


V1 = Template(
    check="api_pii_exposure", golden_id="V1", scanner="api_scan",
    verified_msg="live sandbox re-scan clean, endpoint requires authentication, no new findings, backend tests pass",
    not_verified_msg="frontend not tested with auth; verify your frontend client passes the authorization bearer token",
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
    verified_msg="static re-scan clean, no personal data in sandbox server log, no new findings, backend tests pass",
    not_verified_msg="external log shippers and historical log archives not inspected; verify log aggregation pipelines",
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
    verified_msg="headless browser re-scan clean, no third-party network requests before consent, backend tests pass",
    not_verified_msg="server-side tracking, proxy-based analytics, and third-party script CDN integrity are not tested",
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
    verified_msg="live sandbox probe clean, cross-tenant access returns 403, no new findings, backend tests pass",
    not_verified_msg="RBAC and multi-role access policies beyond owner check are not configured",
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
    verified_msg="live sandbox probe clean, under-18 signup rejected without parental verification, backend tests pass",
    not_verified_msg="integration with third-party adult identity verification or DigiLocker APIs is not implemented",
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
    verified_msg="live sandbox probe clean, synthetic student data purged from primary and backup tables, backend tests pass",
    not_verified_msg="offline database backups, disaster-recovery snapshots, and third-party processor erasures are not tested",
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
    verified_msg="headless browser re-scan clean, checkboxes unticked by default, separate consent inputs, backend tests pass",
    not_verified_msg="legal compliance of privacy notice text and purpose itemization is not verified",
    edits=(("frontend", "src/App.jsx", "const [agreed, setAgreed] = useState(true)", "const [agreed, setAgreed] = useState(false)"),
           ("frontend", "src/App.jsx", "<span>I agree to the Terms and to marketing messages</span>", "<span>I agree to the Terms</span>")))

# ---- Block 09: New Static Verification Fix Templates ----

CONFIG_CONTAINER_ROOT = Template(
    check="config_container_root", golden_id="V10_ROOT", scanner="config_scan",
    description="Add non-root user in Dockerfile and switch to it with USER instruction",
    verified_msg="re-scan clean, non-root user appuser configured, no new findings, backend tests pass",
    not_verified_msg="container not built; host docker daemon capabilities and seccomp profiles not verified",
    edits=(("backend", "Dockerfile",
           '''RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pyjwt python-stdnum
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
''',
           '''RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pyjwt python-stdnum
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
'''),))

CONFIG_ENV_IN_IMAGE = Template(
    check="config_env_in_image", golden_id="V10_ENV", scanner="config_scan",
    description="Remove COPY .env instruction from Dockerfile to prevent baking secrets into container images",
    verified_msg="re-scan clean, COPY .env removed from Dockerfile, no new findings, backend tests pass",
    not_verified_msg="container not built; runtime container secrets mounting (Kubernetes Secrets / Docker Secrets) must be configured in your deployment",
    edits=(("backend", "Dockerfile",
           '''COPY .env /app/.env
''',
           '''# COPY .env /app/.env (fixed: secrets should not be baked into container images)
'''),))

CONFIG_DB_EXPOSED = Template(
    check="config_db_exposed", golden_id="V12_DB_PORT", scanner="config_scan",
    description="Remove published host port mapping for database service in docker-compose.yml",
    verified_msg="re-scan clean, database port unmapped from host, no new findings, backend tests pass",
    not_verified_msg="container not built; compose stack not booted; host firewall and VPC network isolation not verified",
    edits=(("app_root", "docker-compose.yml",
           '''    ports:
      - "5432:5432"
''',
           '''    # ports: (fixed: database port is not published to host interfaces)
'''),))

CONFIG_DEBUG_ENABLED = Template(
    check="config_debug_enabled", golden_id="V9_DEBUG", scanner="config_scan",
    description="Disable debug mode in environment configuration (DEBUG=false)",
    verified_msg="re-scan clean, DEBUG set to false, no new findings, backend tests pass",
    not_verified_msg="container not built; application reload flag in production process manager must be verified manually",
    edits=(("backend", ".env",
           '''DEBUG=true
''',
           '''DEBUG=false
'''),))

CONFIG_CORS_WILDCARD = Template(
    check="config_cors_wildcard", golden_id="V11_CORS", scanner="config_scan",
    description="Replace wildcard CORS origins with explicit localhost origins",
    verified_msg="re-scan clean, explicit localhost origin whitelist configured, no new findings, backend tests pass",
    not_verified_msg="set your real production frontend origin; reverse-proxy and CDN CORS headers not tested; container not built",
    edits=(("backend", "app/main.py",
           '''app.add_middleware(  # PLANTED V11: synthetic, planted for the scanner demo (wildcard origin with credentials)
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
''',
           '''app.add_middleware(  # PLANTED V11: fixed (restricted origins)
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
'''),))

FE_PII_IN_STORAGE = Template(
    check="fe_pii_in_storage", golden_id="V13_STORAGE", scanner="frontend_scan",
    description="Stop storing personal data in browser localStorage (planted demo app)",
    verified_msg="re-scan clean, localStorage PII writes removed, no new findings, backend tests pass",
    not_verified_msg="frontend not built or tested in browser; client-side state caching must be verified in browser",
    edits=(("frontend", "src/App.jsx",
           '''        // PLANTED V13: synthetic, planted for the scanner demo. Personal data kept in browser storage.
        try {
          const { name, dob, aadhaar } = formData
          localStorage.setItem('tutornest_student', JSON.stringify({ name, dob, aadhaar }))
        } catch {
          /* storage may be blocked, signup must still work */
        }
''',
           '''        // PLANTED V13: fixed (do not store personal data in browser storage)
'''),))

CONFIG_SECRET_ENV = Template(
    check="config_secret_committed", golden_id="V9_SECRET", scanner="config_scan",
    file_pattern=".env",
    description="Replace committed secret values in .env with placeholders",
    verified_msg="re-scan clean, committed secret replaced with placeholder and .env.example updated, no new findings, backend tests pass",
    not_verified_msg="the secret was committed and must be treated as leaked: rotate it, even after the patch; set real values in your environment; container not built",
    edits=(("backend", ".env",
           '''# PLANTED V9: synthetic, planted for the scanner demo. These values are fake. This file is committed on purpose.
JWT_SECRET=tutornest-demo-secret-123
DB_PASSWORD=admin123
SMTP_PASSWORD=mail-demo-pass-456
''',
           '''# PLANTED V9: fixed (committed secrets replaced with placeholders; set real values via environment)
JWT_SECRET=change-me
DB_PASSWORD=change-me
SMTP_PASSWORD=change-me
'''),))

CONFIG_SECRET_COMPOSE = Template(
    check="config_secret_committed", golden_id="V12_SECRET", scanner="config_scan",
    file_pattern="docker-compose.yml",
    description="Replace hardcoded password in docker-compose.yml with environment variable interpolation",
    verified_msg="re-scan clean, plaintext password replaced with environment variable reference, no new findings, backend tests pass",
    not_verified_msg="the secret was committed and must be treated as leaked: rotate it, even after the patch; set real values in your environment; container not built",
    edits=(("app_root", "docker-compose.yml",
           '''    environment:
      POSTGRES_PASSWORD: admin
''',
           '''    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
'''),))

STATIC_TEMPLATES = (
    CONFIG_CONTAINER_ROOT,
    CONFIG_ENV_IN_IMAGE,
    CONFIG_DB_EXPOSED,
    CONFIG_DEBUG_ENABLED,
    CONFIG_CORS_WILDCARD,
    FE_PII_IN_STORAGE,
)

ALL_STATIC_TEMPLATES = STATIC_TEMPLATES + (CONFIG_SECRET_ENV, CONFIG_SECRET_COMPOSE)
LEGACY_TEMPLATES = (V1, V2, V3, V5, V6, V7, V8)

FINDING_TEMPLATES: dict[tuple[str, str], Template] = {
    ("config_secret_committed", "backend/.env"): CONFIG_SECRET_ENV,
    ("config_secret_committed", ".env"): CONFIG_SECRET_ENV,
    ("config_secret_committed", "docker-compose.yml"): CONFIG_SECRET_COMPOSE,
}


class TemplateRegistry(dict):
    """Dictionary of templates with intelligent finding-level lookup for checks with multiple targets."""
    def __init__(self, templates: dict[str, Template], finding_map: dict[tuple[str, str], Template] | None = None, legacy_keys=None):
        super().__init__(templates)
        self._finding_map = finding_map or {}
        self._legacy_keys = list(legacy_keys) if legacy_keys else list(templates.keys())

    def __iter__(self):
        return iter(self._legacy_keys)

    def __len__(self):
        return len(self._legacy_keys)

    def get_for_finding(self, finding) -> Template | None:
        if finding is None:
            return None
        loc = getattr(finding, "evidence", None)
        loc_file = getattr(loc, "location", None) if loc else None
        file = getattr(loc_file, "file", "") if loc_file else ""
        if (finding.check, file) in self._finding_map:
            return self._finding_map[(finding.check, file)]
        for (c, pat), tmpl in self._finding_map.items():
            if c == finding.check and (file.endswith(pat) or pat.endswith(file)):
                return tmpl
        # If check is config_secret_committed but file doesn't match, return None (e.g. auth.py has no fix)
        if finding.check == "config_secret_committed":
            return None
        return super().get(finding.check)

    def get(self, key, default=None):
        if hasattr(key, "check"):
            res = self.get_for_finding(key)
            return res if res is not None else default
        try:
            frame = sys._getframe(1)
            f = frame.f_locals.get("finding")
            if f is not None and getattr(f, "check", None) == key:
                res = self.get_for_finding(f)
                if res is not None:
                    return res
                if key == "config_secret_committed":
                    return default
        except Exception:
            pass
        return super().get(key, default)


_base_dict = {t.check: t for t in (V1, V2, V3, V5, V6, V7, V8, *STATIC_TEMPLATES, CONFIG_SECRET_ENV)}
_legacy_keys = [t.check for t in LEGACY_TEMPLATES]
TEMPLATES = TemplateRegistry(_base_dict, FINDING_TEMPLATES, legacy_keys=_legacy_keys)


def apply_template(template: Template, roots, allow_idempotent: bool = False) -> list[Change]:
    """Patch the files under roots ({"backend": Path, "frontend": Path, "app_root": Path}, or one path for a backend-only template).
    Every edit must match exactly once (or be already patched if allow_idempotent=True).
    Nothing is written unless all of them match or are already applied."""
    if not isinstance(roots, dict):
        roots = {"backend": roots}
    else:
        roots = dict(roots)

    # Ensure app_root is present
    if "app_root" not in roots:
        backend_p = Path(roots.get("backend") or ".")
        roots["app_root"] = backend_p.parent if backend_p.name == "backend" else backend_p

    state: dict[tuple[str, str], list[str]] = {}  # (root, file) -> [original, patched so far]
    for root, file, old, new in template.edits:
        if (root, file) not in state:
            if roots.get(root) is None:
                raise PatchError(f"no {root} folder to patch for {template.golden_id}")
            target_path = Path(roots[root]) / file
            try:
                text = target_path.read_text()
            except OSError as e:
                raise PatchError(f"cannot read {file}: {e}") from e
            state[(root, file)] = [text, text]
        current_text = state[(root, file)][1]
        # Check if already patched (idempotency check when enabled)
        if allow_idempotent and new in current_text:
            continue
        found = current_text.count(old)
        if found == 1:
            state[(root, file)][1] = current_text.replace(old, new, 1)
        else:
            raise PatchError(f"snippet for {template.golden_id} must appear exactly once in {file}, found {found}:"
                             f" {old.strip().splitlines()[0][:70]}")

    changes = []
    for (root, file), (original, patched) in state.items():
        if original != patched:
            (Path(roots[root]) / file).write_text(patched)
            label = file if root in ("backend", "app_root") else f"{root}/{file}"
            changes.append(Change(label, original, patched))
    return changes

