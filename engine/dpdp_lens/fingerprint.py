"""Stable fingerprint of a finding (docs/dpdp-evolve master section 6). Same problem, same fingerprint, across scans,
clones and sandbox copies: no host, no port, no line number, paths relative to the scanned root, POSIX style."""
import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

from .models import Finding


def _path(f: Finding, root) -> str:
    """Repo-relative POSIX path. The runner already makes it relative, an absolute path under root is made relative here."""
    p = Path(f.evidence.location.file)
    if p.is_absolute() and root:
        try:
            p = p.relative_to(Path(root).resolve())
        except ValueError:
            pass
    return p.as_posix().removeprefix("./")


def _url_path(f: Finding, root) -> str:
    return urlparse(f.evidence.location.url).path


def _names(text: str) -> str:
    return ",".join(sorted(x.strip() for x in text.split(",") if x.strip()))


def _log_fields(f: Finding, root) -> list[str]:
    # log_scan writes the summary as "Log call includes a, b"; the test pins this format.
    return [_path(f, root), _names(re.sub(r"^Log call includes\s*", "", f.evidence.summary))]


def _check_only(f: Finding, root) -> list[str]:
    return []


# check id -> the parts after the check id. A test fails when a registered check has no rule here.
RULES = {
    "api_pii_exposure": lambda f, r: [_url_path(f, r)],
    "api_idor": lambda f, r: [_url_path(f, r)],
    "log_pii": _log_fields,
    "db_plaintext_pii": lambda f, r: [f.evidence.location.table, _names(f.evidence.location.column)],
    "erasure_incomplete": lambda f, r: [_names(f.evidence.location.table)],
    "tracker_before_consent": lambda f, r: [urlparse(f.evidence.masked_sample).hostname or ""],
    "consent_bundled": _check_only,
    "children_no_parental_consent": _check_only,
    "missing_contact": _check_only,
    "notice_drift": _check_only,
    "consent_not_recorded": _check_only,
    "consent_no_withdrawal": _check_only,
    "config_secret_committed": lambda f, r: [_path(f, r)],
    "config_env_in_image": lambda f, r: [_path(f, r)],
    "config_container_root": lambda f, r: [_path(f, r)],
    "config_cors_wildcard": lambda f, r: [_path(f, r)],
    "config_debug_enabled": lambda f, r: [_path(f, r)],
    "config_db_exposed": lambda f, r: [_path(f, r)],
    "fe_pii_in_storage": lambda f, r: [_path(f, r)],
}


def fingerprint(f: Finding, root=None) -> str:
    """16 hex characters: sha256 of the check id and its rule's parts joined by "|". Raises KeyError for an unknown check."""
    return hashlib.sha256("|".join([f.check, *RULES[f.check](f, root)]).encode()).hexdigest()[:16]


def fingerprints(findings: list[Finding], root=None) -> list[str]:
    """One per finding, "" for a check without a rule. Two findings of one scan with the same fingerprint (two log calls
    with the same fields in one file) get an occurrence number from the second on, so a scan never holds a duplicate."""
    seen, out = {}, []
    for f in findings:
        fp = fingerprint(f, root) if f.check in RULES else ""
        n = seen[fp] = seen.get(fp, -1) + 1 if fp else 0
        out.append(hashlib.sha256(f"{fp}|{n}".encode()).hexdigest()[:16] if n else fp)
    return out
