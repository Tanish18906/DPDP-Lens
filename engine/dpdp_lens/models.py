"""Scan result models. This is the only interface between engine and dashboard (AGENTS.md section 4)."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low"]
Layer = Literal["db", "code", "api", "browser", "notice", "config", "frontend"]

# AGENTS.md section 4: score = 100 minus these weights, floor at 0.
SEVERITY_WEIGHTS: dict[str, int] = {"critical": 20, "high": 10, "medium": 5, "low": 2}


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


class ScanResult(BaseModel):
    scan_id: str
    target: str
    scanned_at: str
    score: int = Field(ge=0, le=100)
    counts: Counts
    findings: list[Finding]
    notice_drift: Optional[NoticeDrift] = None


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
