"""Finds the source file and line behind a finding (docs/15 S2). Pure read-only helpers: they never raise
and return (file, line), or ("", 0) when nothing matches. File paths are relative to app_root, POSIX style."""
import ast
import fnmatch
import contextvars
import os
import re
from pathlib import Path

SKIP_DIRS = {"node_modules", ".venv", "venv", "dist", "build", ".git", "__pycache__", ".dpdp-state", "golden"}
SKIP_SUFFIXES = (".db", ".log", ".min.js", ".map")  # noise: skipped silently, no scan error
SKIP_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}
NONE = ("", 0)
METHODS = {"get", "post", "put", "delete", "patch"}


MAX_FILES = 5000
MAX_BYTES = 1_000_000


class Capped(Exception):
    """A scan limit was hit. The runner records it as a ScanError of kind "capped": the scan is not complete."""


class TooLarge(OSError):
    """A file over MAX_BYTES. It is an OSError so a scanner that already skips unreadable files skips this one too."""


# The runner sets this list before a scanner runs (and copies the context into the scanner thread). read_capped adds
# the path of every skipped file, so the scanner still returns findings from its other files and the runner can
# record one "capped" ScanError and treat the scanner's checks as not fully run.
SKIPPED: contextvars.ContextVar = contextvars.ContextVar("skipped_files", default=None)


def _files(root, limit=None):
    """Relative POSIX paths under root, sorted, with the skip rules of docs/15 D6 applied while walking.
    Symlinks that resolve outside root are skipped. limit: raise Capped when more files than this are found."""
    root = Path(root)
    real, seen = root.resolve(), 0
    for here, dirs, names in os.walk(root):  # os.walk does not follow symlinked folders
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for n in sorted(names):
            if n in SKIP_FILES or n.endswith(SKIP_SUFFIXES):
                continue
            path = Path(here) / n
            if path.is_symlink() and not path.resolve().is_relative_to(real):
                continue
            seen += 1
            if limit and seen > limit:
                raise Capped(f"more than {limit} files under the scan folder")
            yield path.relative_to(root).as_posix()


def read_capped(root, rel) -> str:
    """Text of a scanned file. A file over MAX_BYTES is skipped and noted in SKIPPED (raises TooLarge)."""
    path = Path(root) / rel
    if path.stat().st_size > MAX_BYTES:
        if (noted := SKIPPED.get()) is not None:
            noted.append(rel)
        raise TooLarge(f"{rel} is larger than {MAX_BYTES} bytes")
    return path.read_text()


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
