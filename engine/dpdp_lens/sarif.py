"""ScanResult to SARIF 2.1.0, so a scan can gate a CI job or load into a code scanning view.
Only open findings with a repo-relative file are listed (live api, db and browser findings have no file and stay in the JSON).
Text comes from the finding's own masked fields, never raw PII."""
from pathlib import PurePosixPath

from .models import Finding, ScanResult

LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}


def _file(f: Finding) -> str:
    """The repo-relative file, or "" when the finding has none (or the path is absolute or climbs out of the repo)."""
    path = PurePosixPath(f.evidence.location.file)
    return path.as_posix() if f.evidence.location.file and not path.is_absolute() and ".." not in path.parts else ""


def _location(f: Finding) -> dict:
    physical = {"artifactLocation": {"uri": _file(f)}}
    if f.evidence.location.line > 0:
        physical["region"] = {"startLine": f.evidence.location.line}
    return {"physicalLocation": physical}


def _message(f: Finding) -> str:
    text = f"{f.title}. {f.explanation} Evidence: {f.evidence.summary}"
    return f"{text} Sample (masked): {f.evidence.masked_sample}" if f.evidence.masked_sample else text


def to_sarif(scan: ScanResult) -> dict:
    open_findings = [f for f in scan.findings if f.status == "open" and _file(f)]
    rules: dict[str, dict] = {}
    for f in open_findings:
        rules.setdefault(f.check, {
            "id": f.check, "name": f.check, "shortDescription": {"text": f.title},
            "fullDescription": {"text": f.explanation},
            "help": {"text": "; ".join(f"{c.ref}: {c.note}" for c in f.clauses) or "No clause mapped"},
            "properties": {"layer": f.layer, "clauses": [c.ref for c in f.clauses]}})
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "DPDP Lens", "rules": list(rules.values())}},
            "properties": {"scanId": scan.scan_id, "target": scan.target, "readinessScore": scan.score,
                           "note": "Readiness report, not a compliance certificate."},
            "results": [{
                "ruleId": f.check, "level": LEVEL[f.severity], "message": {"text": _message(f)},
                "locations": [_location(f)],
                **({"partialFingerprints": {"dpdpLens/v1": f.fingerprint}} if f.fingerprint else {}),
                "properties": {"findingId": f.id, "severity": f.severity, "clauses": [c.ref for c in f.clauses],
                               "fixAvailable": f.fix.available}} for f in open_findings]}]}
