"""Scan result models. This is the only interface between engine and dashboard (AGENTS.md section 4)."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low"]
Layer = Literal["db", "code", "api", "browser", "notice", "config", "frontend"]
Proof = Literal["probed", "observed", "static"]  # probed: behaviour confirmed by a live request. Never say "exploit proof".

# AGENTS.md section 4: score = 100 minus these weights, floor at 0.
SEVERITY_WEIGHTS: dict[str, int] = {"critical": 10, "high": 5, "medium": 2, "low": 1}


class Clause(BaseModel):
    ref: str
    note: str


class Location(BaseModel):
    file: str = ""
    line: int = 0
    url: str = ""
    table: str = ""
    column: str = ""


class Evidence(BaseModel):
    kind: Literal["http", "db", "code", "network", "dom"]
    summary: str
    masked_sample: str = ""  # masked value only, never raw PII
    location: Location = Field(default_factory=Location)
    detector: Literal["rule", "model"] = "rule"  # "model": found through hints.semantic_hints, never above medium


class Fix(BaseModel):
    available: bool = False
    diff: Optional[str] = None
    verified: bool = False
    rescan_passed: Optional[bool] = None
    tests_passed: Optional[bool] = None
    score_before: Optional[int] = None
    score_after: Optional[int] = None
    kind: Optional[str] = None  # "notice_align": the drift is closed, the purposes are still open
    pending_inputs: Optional[list[str]] = None  # what only the owner can supply, e.g. "purpose for dob"


class Finding(BaseModel):
    id: str
    check: str
    layer: Layer
    severity: Severity
    title: str
    explanation: str
    clauses: list[Clause]
    severity_reason: str = ""  # one sentence, built from scanner facts (checks.reason), never from an LLM
    recommendation: str = ""  # static text per check id, filled by the runner from checks.py
    fingerprint: str = ""  # stable id of the problem across scans (fingerprint.py), filled by the runner
    proof: Proof = "static"  # how the finding was confirmed, filled by the runner from checks.py
    evidence: Evidence
    status: Literal["open", "verified_fixed"] = "open"
    fix: Fix = Field(default_factory=Fix)


class ObservedField(BaseModel):
    field: str
    where: list[str]


class UndeclaredDetail(BaseModel):
    field: str
    where: list[str]
    needs_review: bool
    review_note: str


class NoticeDrift(BaseModel):
    declared: list[str]
    observed: list[ObservedField]
    undeclared: list[str]
    undeclared_detail: Optional[list[UndeclaredDetail]] = None  # optional: older scans and clients do not have it


class Counts(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class ScanError(BaseModel):
    scanner: str
    kind: Literal["failed", "timeout", "capped"]
    message: str  # no raw PII


class Coverage(BaseModel):
    mode: Literal["full", "static"] = "full"
    checks_run: list[str] = []
    checks_skipped: list[str] = []  # not attempted, e.g. the live checks of a static scan
    scanners_failed: list[str] = []  # attempted and failed: their checks are neither run nor skipped


class ScanResult(BaseModel):
    scan_id: str
    target: str
    scanned_at: str
    score: int = Field(ge=0, le=100)
    counts: Counts
    findings: list[Finding]
    notice_drift: Optional[NoticeDrift] = None
    scan_errors: list[ScanError] = []
    coverage: Optional[Coverage] = None
    complete: bool = True  # False when a scanner failed, timed out or hit a cap: the score is then not a clean result
    policy_version: str = ""
    scanner_version: str = ""
    repo: str = ""
    branch: str = ""
    commit: str = ""


def compute_score(findings: list[Finding]) -> int:
    """Open findings only: a verified_fixed finding no longer costs points."""
    penalty = sum(SEVERITY_WEIGHTS[f.severity] for f in findings if f.status == "open")
    return max(0, 100 - penalty)


def compute_counts(findings: list[Finding]) -> Counts:
    counts = Counts()
    for f in findings:
        if f.status == "open":
            setattr(counts, f.severity, getattr(counts, f.severity) + 1)
    return counts
