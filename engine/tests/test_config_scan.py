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
