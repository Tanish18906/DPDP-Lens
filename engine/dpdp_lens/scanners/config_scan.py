"""config_scan: secrets and risky settings in config files and source (docs/15 S3). Static and read only.
One finding per (check, file). Secret values are never shown in full: first 2 characters plus ***.
Paths are relative to app_root. Test folders are skipped (they are not deployed). Not scanned: JS and TS source."""
import ast
import re
import subprocess
from pathlib import Path

import yaml

from ..checks import reason
from ..locator import _files
from ..models import Evidence, Finding, Fix, Location

KEY = r"(?:secret|passw(?:or)?d|token|api[_-]?key|private[_-]?key|access[_-]?key|jwt)"
KV = re.compile(rf"""^\s*(?:-\s*)?(?:export\s+)?["']?([\w.\-]*{KEY}[\w.\-]*)["']?\s*[:=]\s*(.*?)\s*$""", re.I)
KEY_ONLY = re.compile(KEY, re.I)
PLACEHOLDER = re.compile(r"^(\$\{.*\}|\$\w+|<.*>|your[-_].*|x{3,}|null|none)$", re.I)
URL_CRED = re.compile(r"://[^/\s:@\"']+:([^@\s/\"']+)@")
DEBUG_LINE = re.compile(r"^\s*(?:-\s*)?(?:export\s+)?DEBUG\s*[:=]\s*[\"']?(true|1|yes|on)\b", re.I)
CORS_HEADER = re.compile(r"Access-Control-Allow-Origin[\"']?[\s:,=]+[\"']?\*", re.I)
CONFIG_SUFFIXES = (".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".conf", ".properties")
ENV_SKIP = (".example", ".sample", ".template")
DB_IMAGES = {"postgres", "mysql", "mariadb", "mongo", "mongodb", "redis", "mssql", "mcr.microsoft.com/mssql/server"}
DB_PORTS = {"5432", "3306", "27017", "6379", "1433"}
DEFAULT_PASSWORDS = {"", "admin", "password", "root", "postgres", "123456", "secret", "changeme", "test", "mysql"}
SAFE_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
MAX_BYTES = 1_000_000


def _literal(raw: str) -> str:
    """The value if it is a real literal secret (4 or more characters, not a placeholder), else ''."""
    v = raw.split(" #")[0].strip().rstrip(",").strip().strip("\"'")
    return v if len(v) >= 4 and not PLACEHOLDER.match(v) and v[0] not in "{[" else ""


def _mask(v: str) -> str:
    return v[:2] + "***"


def _is_env(name: str) -> bool:
    return (name == ".env" or name.startswith(".env.")) and not name.endswith(ENV_SKIP)


def _tracked(root: Path, rel: str) -> bool:
    try:  # read only and fail soft: no git, no repo or a timeout simply means "not known"
        return subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", rel],
                              capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def _finding(check: str, severity: str, title: str, rel: str, line: int, summary: str, sample: str,
             explanation: str, **facts) -> Finding:
    return Finding(
        id="", check=check, layer="config", severity=severity, title=title,
        severity_reason=reason(check, **facts), explanation=explanation, clauses=[],
        evidence=Evidence(kind="code", summary=summary, masked_sample=sample, location=Location(file=rel, line=line)),
        fix=Fix(available=False))


def _secrets(text: str, rel: str, is_py: bool) -> list[tuple[int, str, str]]:
    """(line, key, masked) for each literal secret. Python goes through ast, other files line by line."""
    hits = []
    if is_py:
        try:
            for n in ast.walk(ast.parse(text)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
                value = getattr(n, "value", None)
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and (v := _literal(value.value)):
                    hits += [(n.lineno, t.id, _mask(v)) for t in targets if isinstance(t, ast.Name) and KEY_ONLY.search(t.id)]
        except (SyntaxError, ValueError):
            pass
    else:
        for i, line in enumerate(text.splitlines(), 1):
            if (m := KV.match(line)) and (v := _literal(m.group(2))):
                hits.append((i, m.group(1), _mask(v)))
    for i, line in enumerate(text.splitlines(), 1):  # user:password@host in a URL
        if (m := URL_CRED.search(line)) and (v := _literal(m.group(1))) and not any(h[0] == i for h in hits):
            hits.append((i, "url password", _mask(v)))
    return sorted(hits)


def _secret_finding(root: Path, rel: str, hits: list[tuple[int, str, str]]) -> Finding:
    line, key, masked = hits[0]
    keys = ", ".join(dict.fromkeys(h[1] for h in hits))
    tracked = " The file is tracked by git." if _tracked(root, rel) else ""
    return _finding(
        "config_secret_committed", "high", "Secret value written in a file in the repository", rel, line,
        f"{len(hits)} secret value(s) in plain text in {rel}: {keys}", f"{key}={masked}",
        f"{rel} holds secret values as literal text.{tracked} This likely does not meet the reasonable security "
        "safeguards expected for access control, because anyone with the repository can read them.", n=len(hits), file=rel)


def _dockerfile(rel: str, text: str) -> list[Finding]:
    lines = text.splitlines()
    out, users, froms = [], [], []
    env_hit = None
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if re.match(r"FROM\s", s, re.I):
            froms.append(i)
        elif m := re.match(r"USER\s+(\S+)", s, re.I):
            users.append((i, m.group(1).split(":")[0].lower()))
        elif env_hit is None:
            if (m := re.match(r"(?:COPY|ADD)\s+(?:--\S+\s+)*(\S*\.env(?:\.\S+)?)\s", s, re.I)) and not m.group(1).endswith(ENV_SKIP):
                env_hit = (i, s, f"copies {m.group(1)} into the image")
            elif (m := re.match(r"(?:ENV|ARG)\s+(\w+)[=\s]\s*(.*)", s, re.I)) and KEY_ONLY.search(m.group(1)) and (v := _literal(m.group(2))):
                env_hit = (i, f"{s.split()[0].upper()} {m.group(1)}={_mask(v)}", f"sets secret {m.group(1)} in the image")
    if env_hit:
        i, sample, what = env_hit
        out.append(_finding(
            "config_env_in_image", "high", "Secrets are baked into the container image", rel, i,
            f"The Dockerfile {what}", sample,
            f"The image built from {rel} {what}, so anyone who can pull the image can read it. "
            "This likely does not meet the reasonable security safeguards expected for protecting secrets.", what=what))
    if froms and (not users or users[-1][1] in ("root", "0")):
        out.append(_finding(
            "config_container_root", "medium", "Container runs as root", rel, users[-1][0] if users else froms[-1],
            "The Dockerfile has no non root USER" if not users else f"The last USER is {users[-1][1]}",
            "no USER instruction" if not users else f"USER {users[-1][1]}",
            f"{rel} never switches to a non root user, so the app runs with root rights inside the container. "
            "This likely does not meet the technical measures expected to limit damage from a break-in."))
    reload_line = next((i for i, line in enumerate(lines, 1) if re.match(r"(?:CMD|ENTRYPOINT)\b", line.strip(), re.I)
                        and re.search(r"--reload|--debug", line)), 0)
    if reload_line:
        out.append(_debug_finding(rel, reload_line, lines[reload_line - 1].strip(), "the container command"))
    return out


def _debug_finding(rel: str, line: int, sample: str, where: str) -> Finding:
    return _finding(
        "config_debug_enabled", "medium", "Debug mode is on", rel, line, f"Debug or reload is enabled in {where}", sample,
        f"{rel} turns on debug or reload mode. This likely does not meet the technical measures expected in production, "
        "because debug mode can show internals and stack traces to users.", file=rel)


def _cors_finding(rel: str, line: int, creds: bool, sample: str) -> Finding:
    return _finding(
        "config_cors_wildcard", "medium", "CORS allows every origin", rel, line,
        "Any website may call this API from a browser" + (", with credentials" if creds else ""), sample,
        f"{rel} allows requests from any origin" + (" together with credentials" if creds else "") + ". "
        "This likely does not meet the access control expected for reasonable security safeguards.",
        creds=" and credentials are allowed" if creds else "")


def _python_rules(rel: str, text: str) -> list[Finding]:
    out = []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return out
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        kw = {k.arg: k.value for k in n.keywords if k.arg}
        origins = kw.get("allow_origins")
        if isinstance(origins, (ast.List, ast.Tuple)) and any(isinstance(e, ast.Constant) and e.value == "*" for e in origins.elts):
            creds = isinstance(kw.get("allow_credentials"), ast.Constant) and kw["allow_credentials"].value is True
            out.append(_cors_finding(rel, origins.lineno, creds,
                                     'allow_origins=["*"]' + (", allow_credentials=True" if creds else "")))
        if isinstance(kw.get("debug"), ast.Constant) and kw["debug"].value is True and not any(f.check == "config_debug_enabled" for f in out):
            out.append(_debug_finding(rel, kw["debug"].lineno, "debug=True", "the application code"))
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and n.value.value is True
                and any(isinstance(t, ast.Name) and t.id == "DEBUG" for t in n.targets)
                and not any(f.check == "config_debug_enabled" for f in out)):
            out.append(_debug_finding(rel, n.lineno, "DEBUG = True", "the application code"))
    return out


def _compose(rel: str, text: str) -> list[Finding]:
    ports = []  # (service, image, port as written, env dict)
    try:
        for name, svc in (yaml.safe_load(text) or {}).get("services", {}).items():
            env = svc.get("environment") or {}
            if isinstance(env, list):
                env = dict(e.split("=", 1) if "=" in e else (e, "") for e in map(str, env))
            ports += [(name, str(svc.get("image", "")), str(p), {str(k): str(v) for k, v in env.items()})
                      for p in svc.get("ports") or []]
    except Exception:  # not valid YAML: fall back to a line scan for well known database ports
        for line in text.splitlines():
            if m := re.match(r"\s*-\s*[\"']?([\d.:\[\]a-z]*?\d+:\d+)", line):
                ports.append(("db", "", m.group(1), {}))
        pw = re.findall(r"(\w*PASSWORD\w*)\s*[:=]\s*[\"']?(\S*?)[\"']?\s*$", text, re.M)
        ports = [(s, i, p, dict(pw)) for s, i, p, _ in ports]
    out = []
    for service, image, port, env in ports:
        parts = port.split("/")[0].split(":")
        host = parts[0] if len(parts) == 3 else ""
        container = parts[-1].split("-")[0]
        if not (image.split(":")[0] in DB_IMAGES or container in DB_PORTS) or host in SAFE_HOSTS:
            continue
        weak = any(k.upper().endswith("PASSWORD") and v.lower() in DEFAULT_PASSWORDS for k, v in env.items())
        line = next((i for i, l in enumerate(text.splitlines(), 1) if port.split("/")[0] in l), 0)
        out.append(_finding(
            "config_db_exposed", "high", "Database port is published to every network interface", rel, line,
            f"Service {service} publishes database port {container} on all interfaces" + (" with a default password" if weak else ""),
            port,
            f"{rel} publishes the {service} database port to the host without limiting it to 127.0.0.1"
            + (", and the password is a common default" if weak else "") + ". "
            "This likely does not meet the access control expected for reasonable security safeguards.",
            service=service, port=container, creds=" and its password is a common default" if weak else ""))
        break  # one finding per file
    return out


def scan(app_root) -> list[Finding]:
    root, findings = Path(app_root), []
    for rel in _files(root):
        p = Path(rel)
        name = p.name.lower()
        if "tests" in p.parts or "test" in p.parts or name.startswith("test_") or name == "conftest.py":
            continue
        is_docker = name.startswith("dockerfile") or name.endswith(".dockerfile")
        is_compose = name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
        is_py = name.endswith(".py")
        if not (is_docker or is_py or _is_env(name) or name.endswith(CONFIG_SUFFIXES)):
            continue
        try:
            if (root / rel).stat().st_size > MAX_BYTES:
                continue
            text = (root / rel).read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if is_docker:
            findings += _dockerfile(rel, text)
            continue
        if hits := _secrets(text, rel, is_py):
            findings.append(_secret_finding(root, rel, hits))
        if is_py:
            findings += _python_rules(rel, text)
            continue
        if is_compose:
            findings += _compose(rel, text)
        if m := CORS_HEADER.search(text):
            findings.append(_cors_finding(rel, text[:m.start()].count("\n") + 1, False, m.group(0)))
        if (i := next((i for i, l in enumerate(text.splitlines(), 1) if DEBUG_LINE.match(l)), 0)):
            findings.append(_debug_finding(rel, i, text.splitlines()[i - 1].strip(), rel))
    return findings
