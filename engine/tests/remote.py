"""A local bare git repo of TutorNest to stand in for GitHub in tests (no network). It lives in a temp folder, never in the project repo."""
import os
import shutil
import subprocess
from pathlib import Path

from conftest import BACKEND

TARGET_APP = BACKEND.parent
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, check=True, capture_output=True, text=True).stdout.strip()


def make_remote(base: Path, full_name: str = "acme/tutornest", source: Path = TARGET_APP) -> str:
    """Create <base>/<full_name>.git from a copy of `source`. Returns the commit sha of its only commit."""
    work = base / "_work" / full_name.replace("/", "_")
    shutil.copytree(source, work, ignore=shutil.ignore_patterns("node_modules", "*.db", "__pycache__", "dist", ".pytest_cache", "*.log"))
    git(work, "init", "-q", "-b", "main")
    git(work, "add", "-A", "-f")  # -f: the planted .env is git-ignored on purpose
    git(work, "commit", "-q", "-m", "tutornest")
    bare = base / f"{full_name}.git"
    bare.parent.mkdir(parents=True, exist_ok=True)
    git(base, "clone", "-q", "--bare", str(work), str(bare))
    return git(work, "rev-parse", "HEAD")
