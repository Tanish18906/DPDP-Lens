"""log_pii: logger or print calls that log a PII-named variable. Python ast, reads source only."""
import ast
import re
from pathlib import Path

from ..models import Evidence, Finding, Fix, Location

PII_TOKENS = {"email", "phone", "aadhaar", "pan", "dob", "password", "token"}
LEVELS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}
SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules", ".git"}
_LOGGER_NAME = re.compile(r"(^|_)(logger|logging|log)$", re.I)


def _is_log_call(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id == "print"
    if isinstance(f, ast.Attribute) and f.attr in LEVELS:
        base = f.value
        name = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else ""
        return bool(_LOGGER_NAME.search(name))
    return False


def _pii_names(call: ast.Call) -> list[str]:
    """Identifiers in the arguments with a PII token. Words inside plain string text do not count."""
    names = []
    for arg in [*call.args, *(k.value for k in call.keywords)]:
        for node in ast.walk(arg):
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, str):
                name = node.slice.value
            else:
                continue
            if PII_TOKENS & set(re.split(r"[^a-z0-9]+", name.lower())) and name not in names:
                names.append(name)
    return names


def scan(repo_path: str) -> list[Finding]:
    repo = Path(repo_path)
    findings = []
    for path in sorted(repo.rglob("*.py")):
        if SKIP_DIRS & set(path.relative_to(repo).parts):
            continue
        try:
            src = path.read_text()
            tree = ast.parse(src)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        calls = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_log_call(n)),
                       key=lambda n: n.lineno)
        for call in calls:
            names = _pii_names(call)
            if not names:
                continue
            code = " ".join((ast.get_source_segment(src, call) or "").split())[:200]  # code only, no data
            findings.append(Finding(
                id="", check="log_pii", layer="code", severity="high",
                title="Personal data written to logs",
                explanation="A log call writes personal data in plain text, so anyone who can read the logs can read it. "
                            "This likely does not meet the safeguard expected for masking personal data.",
                clauses=[],
                evidence=Evidence(
                    kind="code", summary=f"Log call includes {', '.join(names)}",
                    masked_sample=code,
                    location=Location(file=path.relative_to(repo).as_posix(), line=call.lineno)),
                fix=Fix(available=True)))
    return findings
