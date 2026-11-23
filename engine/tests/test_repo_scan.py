import subprocess
import tempfile
from pathlib import Path

import pytest

from dpdp_lens import repo_scan
from dpdp_lens.repo_scan import RepoError, checkout, scan_checkout
from remote import git, make_remote

TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0"


@pytest.fixture(scope="module")
def remote(tmp_path_factory):
    base = tmp_path_factory.mktemp("remote")
    return base, make_remote(base)


@pytest.fixture
def local(remote, monkeypatch, with_late_scanners):
    """GIT_BASE points at the local bare repo, and acme/tutornest is allowlisted."""
    base, sha = remote
    monkeypatch.setattr(repo_scan, "GIT_BASE", f"file://{base}")
    monkeypatch.setattr(repo_scan, "ALLOW_FILE", True)
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", "acme/tutornest")
    return sha


@pytest.fixture
def made(monkeypatch):
    """The temp folders checkout() creates, so a test can check they are gone."""
    roots, real = [], tempfile.mkdtemp

    def spy(*a, **k):
        roots.append(Path(real(*a, **k)))
        return roots[-1]

    monkeypatch.setattr(tempfile, "mkdtemp", spy)
    return roots


def test_an_empty_allowlist_refuses_everything(monkeypatch):
    monkeypatch.delenv("DPDP_ALLOWED_REPOS", raising=False)
    with pytest.raises(RepoError) as e, checkout("acme/tutornest"):
        pass
    assert e.value.kind == "refused"


def test_repo_not_on_the_allowlist_is_refused_before_any_clone(monkeypatch, made):
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", "acme/other")
    with pytest.raises(RepoError) as e, checkout("acme/tutornest"):
        pass
    assert e.value.kind == "refused" and made == []  # no temp folder was even created


@pytest.mark.parametrize("name", ["tutornest", "a/b/c", "../x", "a/..", "./x", "a b/c", "a/b;rm", "", "a/b\n"])
def test_bad_names_are_invalid(name, monkeypatch):
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", name)
    with pytest.raises(RepoError) as e, checkout(name):
        pass
    assert e.value.kind == "invalid"


@pytest.mark.parametrize("ref", ["--upload-pack=touch /tmp/x", "-x", "a..b", "a b", "main;ls"])
def test_bad_refs_are_invalid(ref, local):
    with pytest.raises(RepoError) as e, checkout("acme/tutornest", ref):
        pass
    assert e.value.kind == "invalid"


def test_file_remotes_are_refused_without_the_test_flag(monkeypatch, remote):
    monkeypatch.setattr(repo_scan, "GIT_BASE", f"file://{remote[0]}")
    monkeypatch.setattr(repo_scan, "ALLOW_FILE", False)
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", "acme/tutornest")
    with pytest.raises(RepoError) as e, checkout("acme/tutornest"):
        pass
    assert e.value.kind == "invalid"


def test_checkout_clones_and_removes_the_temp_folder(local, made):
    with checkout("acme/tutornest") as path:
        assert (path / "backend" / "app" / "main.py").exists() and (path / ".git").is_dir()
        assert (made[0].stat().st_mode & 0o777) == 0o700
    assert len(made) == 1 and not made[0].exists()


def test_checkout_failure_also_removes_the_temp_folder(local, made, monkeypatch):
    monkeypatch.setenv("DPDP_ALLOWED_REPOS", "acme/missing")
    with pytest.raises(RepoError) as e, checkout("acme/missing"):
        pass
    assert e.value.kind == "clone" and len(made) == 1 and not made[0].exists()


def test_checkout_removes_the_folder_when_the_caller_fails(local, made):
    with pytest.raises(ZeroDivisionError), checkout("acme/tutornest"):
        1 / 0
    assert not made[0].exists()


def test_a_commit_sha_can_be_checked_out(local):
    with checkout("acme/tutornest", local) as path:
        assert git(path, "rev-parse", "HEAD") == local


def test_a_branch_name_can_be_checked_out(local):
    with checkout("acme/tutornest", "main") as path:
        assert git(path, "rev-parse", "HEAD") == local


def test_too_big_a_repo_is_refused_and_removed(local, made, monkeypatch):
    monkeypatch.setattr(repo_scan, "MAX_BYTES", 1000)
    with pytest.raises(RepoError) as e, checkout("acme/tutornest"):
        pass
    assert e.value.kind == "size" and not made[0].exists()


def test_token_is_only_in_the_environment_never_in_args_or_the_url(local, monkeypatch):
    calls, real = [], subprocess.run

    def spy(cmd, **kw):
        calls.append((cmd, kw.get("env") or {}))
        return real(cmd, **kw)

    monkeypatch.setattr(repo_scan.subprocess, "run", spy)
    with checkout("acme/tutornest", token=TOKEN):
        pass
    assert calls and all(TOKEN not in " ".join(cmd) for cmd, _ in calls)
    assert all("GIT_ASKPASS" in env and env["DPDP_GIT_TOKEN"] == TOKEN for _, env in calls)
    assert all("hooksPath=/dev/null" in " ".join(cmd) and "protocol.file.allow" in " ".join(cmd) for cmd, _ in calls)


def test_token_is_redacted_from_errors_and_logs(local, monkeypatch, caplog):
    def fail(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 128, "", f"fatal: unable to access 'https://x-access-token:{TOKEN}@github.com/a/b.git/'")

    monkeypatch.setattr(repo_scan.subprocess, "run", fail)
    with caplog.at_level("DEBUG"), pytest.raises(RepoError) as e, checkout("acme/tutornest", token=TOKEN):
        pass
    assert TOKEN not in str(e.value) and TOKEN not in caplog.text and "[redacted]" in str(e.value)


def test_other_secrets_are_not_passed_to_git(local, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret")
    seen = []
    real = subprocess.run
    monkeypatch.setattr(repo_scan.subprocess, "run", lambda cmd, **kw: (seen.append(kw["env"]), real(cmd, **kw))[1])
    with checkout("acme/tutornest"):
        pass
    assert seen and all("SLACK_BOT_TOKEN" not in env for env in seen)


def test_scan_checkout_is_static_and_sets_repo_branch_and_commit(local):
    with checkout("acme/tutornest", "main") as path:
        scan = scan_checkout(path, "S-007", "static", "acme/tutornest", "main")
    assert (scan.scan_id, scan.repo, scan.branch, scan.commit) == ("S-007", "acme/tutornest", "main", local)
    assert scan.coverage.mode == "static" and scan.complete and scan.findings
    assert {f.check for f in scan.findings} <= set(scan.coverage.checks_run)
    assert "log_pii" in {f.check for f in scan.findings}
    assert all(f.fingerprint for f in scan.findings) and scan.target == ""


def test_scan_checkout_refuses_a_live_mode(local):
    with checkout("acme/tutornest") as path, pytest.raises(ValueError):
        scan_checkout(path, "S-001", "full")


def test_fingerprints_of_a_clone_equal_those_of_the_original_folder(local):
    from dpdp_lens.runner import run_scan
    from remote import TARGET_APP
    with checkout("acme/tutornest") as path:
        cloned = scan_checkout(path, "S-001")
    original = run_scan("", str(TARGET_APP / "backend"), "", mode="static")
    assert {f.fingerprint for f in cloned.findings} == {f.fingerprint for f in original.findings}
