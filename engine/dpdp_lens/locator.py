"""Finds the source file and line behind a finding (docs/15 S2). Pure read-only helpers: they never raise
and return (file, line), or ("", 0) when nothing matches. File paths are relative to app_root, POSIX style."""
import ast
import fnmatch
import os
import re
from pathlib import Path

SKIP_DIRS = {"node_modules", ".venv", "venv", "dist", "build", ".git", "__pycache__", ".dpdp-state", "golden"}
SKIP_SUFFIXES = (".db", ".log")
SKIP_FILES = {"package-lock.json"}
NONE = ("", 0)
METHODS = {"get", "post", "put", "delete", "patch"}


def _files(root):
    """Relative POSIX paths under root, sorted, with the skip rules of docs/15 D6 applied while walking."""
    root = Path(root)
    for here, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for n in sorted(names):
            if n not in SKIP_FILES and not n.endswith(SKIP_SUFFIXES):
                yield (Path(here) / n).relative_to(root).as_posix()


def _lines(root, rel):
    return (Path(root) / rel).read_text(errors="replace").splitlines()


def _norm(path):
    return re.sub(r"\{[^}]*\}", "{}", path)


def find_route(app_root, method, path) -> tuple[str, int]:
    """Line of the `@x.get("/path")` decorator that serves method + path. `{param}` names do not have to match."""
    try:
        want = (method.lower(), _norm(path))
        for rel in _files(app_root):
            if not rel.endswith(".py"):
                continue
            try:
                tree = ast.parse((Path(app_root) / rel).read_text())
            except (SyntaxError, UnicodeDecodeError, ValueError):
                continue
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for d in fn.decorator_list:
                    if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in METHODS
                            and d.args and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str)
                            and (d.func.attr, _norm(d.args[0].value)) == want):
                        return rel, d.lineno  # shortcut: a router prefix is not added, upgrade if an app uses include_router(prefix=)
    except Exception:
        pass
    return NONE


def find_column(app_root, table, column) -> tuple[str, int]:
    """Line of the column inside `CREATE TABLE table (...)` in a .py or .sql file, or of a model field `column = ...`."""
    try:
        create = re.compile(rf"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?[\"`\[]?{re.escape(table)}[\"`\]]?\s*\(", re.I)
        col = re.compile(rf"^\s*[\"`\[]?{re.escape(column)}[\"`\]]?\s+[A-Za-z]", re.I)
        field = re.compile(rf"^\s*{re.escape(column)}\s*[:=]")
        for rel in _files(app_root):
            if not rel.endswith((".py", ".sql")):
                continue
            lines = _lines(app_root, rel)
            for i, line in enumerate(lines):
                if create.search(line):
                    for j in range(i, min(i + 80, len(lines))):
                        if j > i and lines[j].lstrip().startswith(")"):
                            break
                        if j > i and col.match(lines[j]):
                            return rel, j + 1
            if rel.endswith(".py"):  # SQLAlchemy or pydantic style model: class Table: column = Column(...)
                for i, line in enumerate(lines):
                    if re.match(rf"\s*class\s+{re.escape(table)}\b", line, re.I):
                        for j in range(i + 1, min(i + 80, len(lines))):
                            if field.match(lines[j]):
                                return rel, j + 1
    except Exception:
        pass
    return NONE


def find_text(app_root, needle, globs) -> tuple[str, int]:
    """First line containing needle in files whose relative path matches one of the glob patterns."""
    try:
        for rel in _files(app_root):
            if any(fnmatch.fnmatch(rel, g) for g in globs):
                for i, line in enumerate(_lines(app_root, rel), 1):
                    if needle in line:
                        return rel, i
    except Exception:
        pass
    return NONE
