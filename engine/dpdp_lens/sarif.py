"""ScanResult to SARIF 2.1.0, so a scan can gate a CI job or load into a code scanning view.
Only open findings are listed. Text comes from the finding's own masked fields, never raw PII."""
from .models import Finding, ScanResult

LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}


def _location(f: Finding) -> dict:
    loc = f.evidence.location
    if loc.file or loc.url:
        physical = {"artifactLocation": {"uri": loc.file or loc.url}}
        if loc.file and loc.line > 0:
            physical["region"] = {"startLine": loc.line}
        return {"physicalLocation": physical}
    name = ".".join(p for p in (loc.table, loc.column) if p) or f.layer
    return {"logicalLocations": [{"name": name, "kind": "table" if loc.table else "module"}]}


def _message(f: Finding) -> str:
    text = f"{f.title}. {f.explanation} Evidence: {f.evidence.summary}"
    return f"{text} Sample (masked): {f.evidence.masked_sample}" if f.evidence.masked_sample else text


def to_sarif(scan: ScanResult) -> dict:
    open_findings = [f for f in scan.findings if f.status == "open"]
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
                "properties": {"findingId": f.id, "severity": f.severity, "clauses": [c.ref for c in f.clauses],
                               "fixAvailable": f.fix.available}} for f in open_findings]}]}
