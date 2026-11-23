from pathlib import Path

import pytest

from dpdp_lens.scanners import config_scan

CLEAN = Path(__file__).parent / "fixtures" / "clean_app"


def run(tmp_path, files):
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return [(f.check, f.evidence.location.file, f.evidence.location.line) for f in config_scan.scan(tmp_path)]


def test_clean_control_has_no_config_findings():
    assert config_scan.scan(CLEAN) == []


def test_secret_in_env_is_masked_and_example_files_are_skipped(tmp_path):
    (tmp_path / ".env").write_text("# note\nJWT_SECRET=tutornest-demo-secret-123\nSMTP_PASSWORD=${SMTP}\nAPI_KEY=xxx\nTOKEN=abc\n")
    (tmp_path / ".env.example").write_text("JWT_SECRET=real-looking-secret-999\n")
    found = config_scan.scan(tmp_path)
    assert [(f.check, f.evidence.location.file, f.evidence.location.line) for f in found] == [("config_secret_committed", ".env", 2)]
    text = found[0].model_dump_json()
    assert "JWT_SECRET=tu***" in text and "tutornest-demo-secret-123" not in text  # placeholders and short values do not count
    assert found[0].severity_reason.startswith("High:")


@pytest.mark.parametrize("value", ["${X}", "$X", "<set-me>", "your-key-here", "xxxx", "null", "abc", ""])
def test_placeholders_and_short_values_are_not_secrets(tmp_path, value):
    assert run(tmp_path, {".env": f"API_KEY={value}\n"}) == []


def test_url_password_and_python_assignment(tmp_path):
    out = run(tmp_path, {"cfg.toml": 'url = "postgres://app:s3cret-pw@db/x"\n', "app.py": 'SECRET_KEY = "abcd-efgh"\nTOKEN_URL = os.environ["T"]\n'})
    assert out == [("config_secret_committed", "app.py", 1), ("config_secret_committed", "cfg.toml", 1)]


def test_test_folders_are_skipped(tmp_path):
    assert run(tmp_path, {"tests/test_a.py": 'PASSWORD = "StudentPass123!"\n', "conftest.py": 'TOKEN = "abcdefgh"\n'}) == []


def test_dockerfile_env_copy_root_and_reload(tmp_path):
    out = run(tmp_path, {"Dockerfile": 'FROM python:3.12\nCOPY . .\nCOPY .env /app/.env\nENV API_KEY=abcdef123\nCMD ["uvicorn", "a:b", "--reload"]\n'})
    assert out == [("config_env_in_image", "Dockerfile", 3), ("config_container_root", "Dockerfile", 1), ("config_debug_enabled", "Dockerfile", 5)]


def test_dockerfile_env_arg_secret_and_last_user_root(tmp_path):
    out = run(tmp_path, {"Dockerfile": "FROM x\nARG DB_PASSWORD=hunter22\nUSER app\nUSER root\n"})
    assert out == [("config_env_in_image", "Dockerfile", 2), ("config_container_root", "Dockerfile", 4)]


def test_dockerfile_with_non_root_user_is_clean(tmp_path):
    assert run(tmp_path, {"Dockerfile": "FROM x\nUSER 1000:1000\n"}) == []


def test_cors_wildcard_in_python_and_header_text(tmp_path):
    found = {f.evidence.location.file: f for f in config_scan.scan(_files(tmp_path, {
        "main.py": 'app.add_middleware(\n    CORSMiddleware,\n    allow_origins=["*"],\n    allow_credentials=True,\n)\n',
        "nginx.conf": "add_header Access-Control-Allow-Origin *;\n"}))}
    assert found["main.py"].evidence.location.line == 3 and "credentials" in found["main.py"].severity_reason
    assert found["nginx.conf"].check == "config_cors_wildcard" and "credentials" not in found["nginx.conf"].severity_reason


def _files(tmp_path, files):
    for rel, text in files.items():
        (tmp_path / rel).write_text(text)
    return tmp_path


def test_debug_in_env_and_in_code(tmp_path):
    assert run(tmp_path, {".env": "DEBUG=true\n", "a.py": "app = FastAPI(debug=True)\n", "b.py": "DEBUG = True\n", "c.py": "DEBUG = False\n"}) == [
        ("config_debug_enabled", ".env", 1), ("config_debug_enabled", "a.py", 1), ("config_debug_enabled", "b.py", 1)]


def test_compose_db_port_published_and_default_password(tmp_path):
    compose = "services:\n  db:\n    image: postgres:16\n    ports:\n      - \"5432:5432\"\n    environment:\n      POSTGRES_PASSWORD: admin\n"
    found = config_scan.scan(_files(tmp_path, {"docker-compose.yml": compose}))
    assert [f.check for f in found] == ["config_secret_committed", "config_db_exposed"]  # one per file and check
    assert found[1].evidence.location.line == 5 and "default" in found[1].severity_reason


@pytest.mark.parametrize("port", ['"127.0.0.1:5432:5432"', '"localhost:5432:5432"'])
def test_compose_bound_db_port_is_clean(tmp_path, port):
    compose = f"services:\n  db:\n    image: postgres:16\n    ports:\n      - {port}\n"
    assert run(tmp_path, {"docker-compose.yml": compose}) == []


def test_compose_not_yaml_falls_back_to_line_scan(tmp_path):
    out = run(tmp_path, {"docker-compose.yml": "services:\n  db: [\n    ports:\n      - \"3306:3306\"\n"})
    assert out == [("config_db_exposed", "docker-compose.yml", 4)]


def test_unreadable_or_huge_files_do_not_raise(tmp_path):
    (tmp_path / ".env").write_bytes(b"\xff\xfe\x00bad")
    assert config_scan.scan(tmp_path) == []


# ---- block 06 item 1: vendor token shapes and more placeholders (tokens are joined here, so no whole token is in the source)
AWS = "AK" + "IA" + "IOSFODNN7EXAMPLE"
GHP = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
SLACK = "xo" + "xb-" + "123456789012-1234567890123-aBcDeFgHiJkLmNoPqRsTuVwX"
STRIPE = "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc"


def scan_root(tmp_path, files):
    run(tmp_path, files)
    return config_scan.scan(tmp_path)


@pytest.mark.parametrize("value", ["changeme", "change-me", "replace_me", "example", "sample", "dummy", "placeholder", "TODO", "redacted"])
def test_more_placeholders_are_not_secrets(tmp_path, value):
    assert run(tmp_path, {".env": f"DB_PASSWORD={value}\n", "s.yml": f"password: {value}\n"}) == []


def test_a_weak_real_password_is_still_a_secret(tmp_path):  # "admin123" is a hard-coded credential, not a placeholder
    assert run(tmp_path, {".env": "DB_PASSWORD=admin123\n"}) == [("config_secret_committed", ".env", 1)]


@pytest.mark.parametrize("name, text", [
    ("ci.py", f'auth = "{GHP}"\n'), ("notify.yml", f'hook: "{SLACK}"\n'), (".env.production", f"STORAGE_ID={AWS}\n"),
    ("frontend/pay.js", f'const s = Stripe("{STRIPE}");\n'), ("deploy.sh", f"curl -H 'Authorization: token {GHP}' x\n"),
    ("src/a.ts", f"const x = '{AWS}'\n")])
def test_vendor_token_shapes_are_found_under_any_key_name(tmp_path, name, text):
    assert run(tmp_path, {name: text}) == [("config_secret_committed", name, 1)]


def test_a_token_is_never_shown_in_full(tmp_path):
    found = scan_root(tmp_path, {"ci.py": f'auth = "{GHP}"\n', "p.js": f'Stripe("{STRIPE}")\n'})
    blob = " ".join(f.model_dump_json() for f in found)
    assert found and GHP not in blob and STRIPE not in blob and GHP[:8] not in blob and "gh***" in blob


def test_js_is_read_for_token_shapes_only_not_by_key_name(tmp_path):
    assert run(tmp_path, {"frontend/a.js": 'const apiKey = "abcd1234efgh";\nconst password = "hunter2hunter2";\n'}) == []


def test_publishable_stripe_keys_and_node_modules_are_not_flagged(tmp_path):
    pk = "pk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc"
    assert run(tmp_path, {"pay.js": f'Stripe("{pk}")\n', "node_modules/x/i.js": f'a("{STRIPE}")\n'}) == []


# ---- block 06 job 2, item C: a constant that names a field or a label is not a secret
@pytest.mark.parametrize("line", ['PASSWORD_FIELD = "password"', 'TOKEN_LABEL = "API token"', 'loginPasswordPlaceholder = "Enter your password"',
                                  'SECRET_HEADER_NAME = "x-secret"'])
def test_names_of_fields_and_labels_are_not_secrets(tmp_path, line):
    assert run(tmp_path, {"app/forms.py": line + "\n"}) == []
    assert run(tmp_path, {"app.yml": line.replace(" = ", ": ").replace('"', "") + "\n"}) == []


@pytest.mark.parametrize("line", ['SECRET_KEY = "dev-secret"', 'DB_PASSWORD_FIELD = "hunter2hunter2"', 'API_TOKEN = "abcdefgh"', 'PASSWORD = "changeit-not"'])
def test_real_looking_secrets_with_similar_names_are_still_found(tmp_path, line):
    assert run(tmp_path, {"app/forms.py": line + "\n"}) == [("config_secret_committed", "app/forms.py", 1)]


# ---- block 06 job 2, item D: key/value pairs in a one-line JSON file
def test_a_one_line_json_file_is_read(tmp_path):
    found = scan_root(tmp_path, {"config.json": '{"name": "app", "api_token": "abcd1234efgh5678", "nested": {"db_password": "hunter2hunter2"}}\n'})
    (f,) = found
    assert f.evidence.location.line == 1 and "2 secret value(s)" in f.evidence.summary and "abcd1234" not in f.model_dump_json() and "hunter2" not in f.model_dump_json()
    assert "ab***" in f.evidence.masked_sample


def test_multi_line_json_still_gives_one_hit_per_secret_and_the_right_line(tmp_path):
    (f,) = scan_root(tmp_path, {"config.json": '{\n  "x": 1,\n  "api_token": "abcd1234efgh5678"\n}\n'})
    assert f.evidence.location.line == 3 and "1 secret value(s)" in f.evidence.summary


def test_json_placeholders_labels_and_non_secret_keys_are_not_flagged(tmp_path):
    assert run(tmp_path, {"config.json": '{"api_token": "${API_TOKEN}", "password_field": "password", "token_url": "", "author": "someone", "api_key": "changeme"}\n'}) == []
