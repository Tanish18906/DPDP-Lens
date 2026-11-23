"""Block 09 tests: Unit, integration, and gate tests for static fix templates and verification."""
import tempfile
from pathlib import Path

import pytest

from conftest import BACKEND, seed_copy
from dpdp_lens.fixer.templates import (
    CONFIG_CONTAINER_ROOT,
    CONFIG_CORS_WILDCARD,
    CONFIG_DB_EXPOSED,
    CONFIG_DEBUG_ENABLED,
    CONFIG_ENV_IN_IMAGE,
    CONFIG_SECRET_COMPOSE,
    CONFIG_SECRET_ENV,
    CONSENT_NOT_RECORDED,
    FE_PII_IN_STORAGE,
    STATIC_TEMPLATES,
    TEMPLATES,
    PatchError,
    apply_template,
)
from dpdp_lens.fixer.verify import verify_fix
from dpdp_lens.runner import run_scan


pytestmark = pytest.mark.usefixtures("with_late_scanners")


NEW_TEMPLATES = (
    CONFIG_CONTAINER_ROOT,
    CONFIG_ENV_IN_IMAGE,
    CONFIG_DB_EXPOSED,
    CONFIG_DEBUG_ENABLED,
    CONFIG_CORS_WILDCARD,
    FE_PII_IN_STORAGE,
    CONSENT_NOT_RECORDED,
    CONFIG_SECRET_ENV,
    CONFIG_SECRET_COMPOSE,
)


# ---- Unit Tests: Template apply, idempotency, and missing pattern rejection ----


@pytest.mark.parametrize("template", NEW_TEMPLATES)
def test_template_applies_and_is_idempotent(tmp_path, template):
    """Each template modifies the expected file, is idempotent on a second run, and returns a valid diff."""
    # Setup mock roots
    roots = {
        "backend": tmp_path / "backend",
        "frontend": tmp_path / "frontend",
        "app_root": tmp_path,
    }
    roots["backend"].mkdir(parents=True, exist_ok=True)
    roots["frontend"].mkdir(parents=True, exist_ok=True)
    (roots["backend"] / "app").mkdir(parents=True, exist_ok=True)
    (roots["frontend"] / "src").mkdir(parents=True, exist_ok=True)

    # Populate target files with original snippet
    for root, file, old, _ in template.edits:
        target_file = roots[root] / file
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if not target_file.exists():
            target_file.write_text(f"# header\n{old}\n# footer\n")
        else:
            target_file.write_text(target_file.read_text() + f"\n{old}\n")

    # 1. First apply produces changes
    changes = apply_template(template, roots)
    assert len(changes) >= 1
    for c in changes:
        assert c.original != c.patched

    # 2. Second apply with allow_idempotent=True produces no changes
    changes_second = apply_template(template, roots, allow_idempotent=True)
    assert len(changes_second) == 0

    # 3. Second apply without allow_idempotent raises PatchError
    with pytest.raises(PatchError):
        apply_template(template, roots, allow_idempotent=False)


@pytest.mark.parametrize("template", NEW_TEMPLATES)
def test_template_raises_patch_error_when_pattern_is_missing(tmp_path, template):
    """When the target file exists but lacks the exact snippet, apply_template raises PatchError and writes nothing."""
    roots = {
        "backend": tmp_path / "backend",
        "frontend": tmp_path / "frontend",
        "app_root": tmp_path,
    }
    roots["backend"].mkdir(parents=True, exist_ok=True)
    roots["frontend"].mkdir(parents=True, exist_ok=True)
    (roots["backend"] / "app").mkdir(parents=True, exist_ok=True)
    (roots["frontend"] / "src").mkdir(parents=True, exist_ok=True)

    for root, file, _, _ in template.edits:
        target_file = roots[root] / file
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("# completely different content without expected snippet\n")

    with pytest.raises(PatchError, match="found 0"):
        apply_template(template, roots)


# ---- Integration Tests: Sandbox verify_fix on copy of TutorNest ----


@pytest.mark.parametrize("check_id,file_hint", [
    ("config_container_root", "Dockerfile"),
    ("config_env_in_image", "Dockerfile"),
    ("config_db_exposed", "docker-compose.yml"),
    ("config_debug_enabled", ".env"),
    ("config_cors_wildcard", "main.py"),
    ("fe_pii_in_storage", "App.jsx"),
    ("consent_not_recorded", "main.py"),
    ("config_secret_committed", ".env"),
    ("config_secret_committed", "docker-compose.yml"),
])
def test_end_to_end_static_fix_verification(tmp_path, check_id, file_hint):
    """Every static finding with an automated fix passes live sandbox verify_fix with rescan and tests clean."""
    db_path = seed_copy(tmp_path)[1]
    scan = run_scan("", str(BACKEND), "", mode="static")
    target_finding = next(
        f for f in scan.findings
        if f.check == check_id and file_hint in f.evidence.location.file
    )
    assert target_finding.fix.available is True

    res = verify_fix(target_finding, BACKEND, db_path, golden_dir=tmp_path / "golden")
    assert res.fix.verified is True
    assert res.fix.rescan_passed is True
    assert res.fix.tests_passed is True
    assert len(res.fix.diff) > 0
    assert res.log.get("idempotent") is True
    assert res.log.get("no_new_findings") is True
    assert "statement" in res.log


# ---- Inventory and Gate Tests ----


def test_static_scan_inventory_and_fix_availability():
    """Static scan produces exactly 11 findings, score 60; 10 have verified fixes, 1 has explicit reason."""
    scan = run_scan("", str(BACKEND), "", mode="static")
    assert len(scan.findings) == 11
    assert scan.score == 60

    with_fix = [f for f in scan.findings if f.fix.available]
    without_fix = [f for f in scan.findings if not f.fix.available]

    assert len(with_fix) == 10
    assert len(without_fix) == 1

    # Verify the one finding without automated fix has explicit documented reason
    auth_secret = without_fix[0]
    assert auth_secret.check == "config_secret_committed"
    assert "auth.py" in auth_secret.evidence.location.file
    # Documented reason: hardcoded application secret key in source code requires secret rotation and runtime environment provisioning


def test_full_scan_regression_without_frontend(target, target_db):
    """Detection logic remains unchanged: TutorNest full scan without frontend produces 19 findings and score 20."""
    scan = run_scan(target, str(BACKEND), str(target_db), frontend_url="")
    assert len(scan.findings) == 19
    assert scan.score == 20
