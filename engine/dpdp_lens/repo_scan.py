"""Shallow checkout of an allowlisted GitHub repo, and a static scan of it (master rules 4, 5, 6 and 7).
Nothing from the cloned repo is executed here: git hooks are off, submodules are not fetched, and the scan only reads files.
The token is handed to git through a GIT_ASKPASS helper and the environment, never in the URL or in the command line."""
import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .audit import redact
from .models import ScanResult
from .runner import run_scan

NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REF = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")  # no leading "-" (an option), "..", and no spaces
SHA = re.compile(r"^[0-9a-f]{40}$")
GIT_BASE = "https://github.com"
ALLOW_FILE = False  # tests only: lets GIT_BASE be a file:// URL of a local bare repo
CLONE_TIMEOUT = 120  # seconds
MAX_BYTES = 200 * 1024 * 1024
HARDENING = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]


class RepoError(Exception):
    """kind: invalid (bad name or ref), refused (not allowlisted), clone, timeout, size. The message never holds a token."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def allowed(env_name: str = "DPDP_ALLOWED_REPOS") -> list[str]:
    return [x.strip().lower() for x in os.environ.get(env_name, "").split(",") if x.strip()]


def check_name(full_name: str, env_name: str = "DPDP_ALLOWED_REPOS") -> str:
    """Valid owner/repo and on the allowlist. An empty allowlist refuses everything."""
    if not NAME.fullmatch(full_name or "") or any(p in (".", "..") for p in full_name.split("/")):
        raise RepoError("invalid", "repo must look like owner/name (letters, digits, _ . -)")
    if full_name.lower() not in allowed(env_name):
        raise RepoError("refused", f"{full_name} is not in {env_name}")
    return full_name


def _git(args, cwd, env, timeout):
    try:
        proc = subprocess.run(["git", *HARDENING, "-c", f"protocol.file.allow={'always' if ALLOW_FILE else 'never'}", *args],
                              cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RepoError("timeout", f"git took longer than {timeout} seconds") from None
    if proc.returncode:
        raise RepoError("clone", redact(" ".join(proc.stderr.split())[:300]) or "git failed")
    return proc.stdout


def _size(path: Path) -> int:
    return sum(f.lstat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


@contextmanager
def checkout(full_name: str, ref: str | None = None, token: str | None = None, env_name: str = "DPDP_ALLOWED_REPOS"):
    """Yield the path of a shallow clone (a branch, a tag, or a 40 character commit). The temp folder is always removed."""
    check_name(full_name, env_name)
    if ref and not (REF.fullmatch(ref) and ".." not in ref):
        raise RepoError("invalid", "ref is not a valid branch, tag or commit")
    base = GIT_BASE.rstrip("/")
    if base.startswith("file:") and not ALLOW_FILE:
        raise RepoError("invalid", "file:// remotes are only allowed in tests")
    root = Path(tempfile.mkdtemp(prefix="dpdp-repo-"))  # mode 0700
    try:
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "DPDP_API_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN")}
        env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
        if token:
            helper = root / "askpass.sh"
            helper.write_text('#!/bin/sh\ncase "$1" in Username*) echo x-access-token ;; *) echo "$DPDP_GIT_TOKEN" ;; esac\n')
            helper.chmod(stat.S_IRWXU)
            env.update(GIT_ASKPASS=str(helper), DPDP_GIT_TOKEN=token)
        url, dest = f"{base}/{full_name}.git", root / "repo"
        try:
            if ref and SHA.fullmatch(ref):  # a commit cannot be cloned directly: fetch just that commit
                dest.mkdir()
                _git(["init", "-q"], dest, env, 30)
                _git(["fetch", "-q", "--depth", "1", "--no-recurse-submodules", "--", url, ref], dest, env, CLONE_TIMEOUT)
                _git(["checkout", "-q", "--detach", "FETCH_HEAD"], dest, env, 60)
            else:
                _git(["clone", "-q", "--depth", "1", "--no-recurse-submodules", "--single-branch", *(["--branch", ref] if ref else []),
                      "--", url, str(dest)], root, env, CLONE_TIMEOUT)
        except RepoError as e:
            if token:
                raise RepoError(e.kind, e.args[0].replace(token, "[redacted]")) from None
            raise
        if _size(dest) > MAX_BYTES:
            raise RepoError("size", f"{full_name} is larger than {MAX_BYTES // 1024 // 1024} MB")
        yield dest
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scan_checkout(path, scan_id: str, mode: str = "static", repo: str = "", branch: str = "") -> ScanResult:
    """Scan a checkout. repo_path is backend/ when it exists, else the checkout. The live checks need a running app, so a
    connected repo only gets the static checks. Sets repo, branch and commit on the result."""
    path = Path(path)
    if mode != "static":
        raise ValueError("a connected repo is scanned in static mode only")
    repo_path = path / "backend" if (path / "backend").is_dir() else path
    result = run_scan("", str(repo_path), "", mode="static", scan_id=scan_id)
    head = lambda *a: subprocess.run(["git", *a], cwd=path, capture_output=True, text=True, timeout=30).stdout.strip()  # noqa: E731
    name = head("rev-parse", "--abbrev-ref", "HEAD")
    return result.model_copy(update={"repo": repo, "branch": branch or (name if name != "HEAD" else ""), "commit": head("rev-parse", "HEAD")})
