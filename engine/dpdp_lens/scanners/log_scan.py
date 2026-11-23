"""log_pii: logger or print calls that log a PII-named variable. Python ast, JavaScript and TypeScript through a small tokenizer. Reads source only."""
import ast
import re
from pathlib import Path

from ..checks import reason
from ..locator import MAX_FILES, _files, read_capped
from ..models import Evidence, Finding, Fix, Location
from ..recognizers import find_pii

PII_TOKENS = {"email", "phone", "aadhaar", "pan", "dob", "password", "token"}
LEVELS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}
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


# ---- JavaScript and TypeScript (block 06 item 2). Not a parser: comments and string text are blanked first, then log calls
# are found in what is left. shortcut: regex literals are not recognised (a quote inside one can confuse the blanking), upgrade to a real parser if that bites.
JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
JS_CALL = re.compile(r"([A-Za-z_$][\w$]*)\s*\.\s*(debug|info|warn|warning|error|critical|exception|log|trace)\s*\(")
JS_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
JS_WORDS = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
JS_NOT_PII_LAST = {"count", "total", "sent", "length", "size", "id", "ids", "type", "status"}  # emailCount is a counter, userEmail is an address


def _blank(c: str) -> str:
    return c if c == "\n" else " "


def _js_code(src: str, i: int, out: list, in_expr: bool) -> int:
    """Copy code into out, blanking comments and string text. In a template ${...} expression, stop after its closing brace."""
    depth, n = 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i) or src.startswith("/*", i):
            end = src.find("\n", i) if c == "/" and src[i + 1] == "/" else src.find("*/", i + 2)
            end = n if end < 0 else (end if src[i + 1] == "/" else end + 2)
            out[i:end] = [_blank(x) for x in src[i:end]]
            i = end
        elif c in "'\"":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            end = min(j + 1, n)
            out[i + 1:end - 1] = [_blank(x) for x in src[i + 1:end - 1]]
            i = end
        elif c == "`":
            i = _js_template(src, i + 1, out)
        elif c == "{":
            depth, i = depth + 1, i + 1
        elif c == "}" and in_expr and depth == 0:
            return i + 1
        else:
            depth, i = depth - (c == "}"), i + 1
    return i


def _js_template(src: str, i: int, out: list) -> int:
    n = len(src)
    while i < n:
        if src[i] == "\\":
            out[i:i + 2] = [_blank(x) for x in src[i:i + 2]]
            i += 2
        elif src[i] == "`":
            return i + 1
        elif src.startswith("${", i):
            i = _js_code(src, i + 2, out, True)
        else:
            out[i] = _blank(src[i])
            i += 1
    return i


def js_code_view(src: str) -> str:
    """The source with comments and the text of strings blanked (same length and line breaks). Template ${...} code is kept."""
    out = list(src)
    _js_code(src, 0, out, False)
    return "".join(out)


def _js_pii_names(args: str) -> list[str]:
    names = []
    for ident in JS_IDENT.findall(args):
        words = [w.lower() for w in JS_WORDS.findall(ident.replace("_", " ").replace("$", " "))]
        if words and PII_TOKENS & set(words) and words[-1] not in JS_NOT_PII_LAST and ident not in names:
            names.append(ident)
    return names


def _masked(text: str) -> str:
    """Code text for the evidence, with any personal data in a string made safe."""
    text = " ".join(text.split())[:200]
    for _, a, b, masked in reversed(find_pii(text)):
        text = text[:a] + masked + text[b:]
    return text


def _scan_js(repo: Path, rel: str) -> list[Finding]:
    p = Path(rel)
    if {"__tests__", "tests", "test"} & set(p.parts) or re.search(r"\.(test|spec)\.", p.name):
        return []  # test files log fixtures, not user data
    try:
        src = read_capped(repo, rel)
    except (UnicodeDecodeError, OSError):
        return []
    code, out = js_code_view(src), []
    for m in JS_CALL.finditer(code):
        base = m.group(1)
        if base != "console" and not _LOGGER_NAME.search(base):
            continue
        depth, j = 1, m.end()
        while j < len(code) and depth:
            depth += (code[j] == "(") - (code[j] == ")")
            j += 1
        names = _js_pii_names(code[m.end():j - 1])
        if not names:
            continue
        line = code.count("\n", 0, m.start()) + 1
        out.append(Finding(
            id="", check="log_pii", layer="code", severity="high", title="Personal data written to logs",
            severity_reason=reason("log_pii", fields=", ".join(names)),
            explanation="A log call writes personal data in plain text, so anyone who can read the logs can read it. "
                        "This likely does not meet the safeguard expected for masking personal data.",
            clauses=[],
            evidence=Evidence(kind="code", summary=f"Log call includes {', '.join(names)}", masked_sample=_masked(src[m.start():j]),
                              location=Location(file=rel, line=line)),
            fix=Fix(available=False)))  # the verified fix template is for the Python demo app only
    return out


def scan(repo_path: str) -> list[Finding]:
    repo = Path(repo_path)
    findings = []
    for rel in _files(repo, MAX_FILES):  # skips .git, node_modules, .venv, dist, build, __pycache__ and outside symlinks
        if rel.endswith(JS_SUFFIXES):
            findings += _scan_js(repo, rel)
            continue
        if not rel.endswith(".py"):
            continue
        try:
            src = read_capped(repo, rel)
            tree = ast.parse(src)
        except (SyntaxError, UnicodeDecodeError, ValueError, OSError):
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
                severity_reason=reason("log_pii", fields=", ".join(names)),
                explanation="A log call writes personal data in plain text, so anyone who can read the logs can read it. "
                            "This likely does not meet the safeguard expected for masking personal data.",
                clauses=[],
                evidence=Evidence(
                    kind="code", summary=f"Log call includes {', '.join(names)}",
                    masked_sample=code,
                    location=Location(file=rel, line=call.lineno)),
                fix=Fix(available=True)))
    return findings
