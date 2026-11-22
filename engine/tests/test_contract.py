import json
import re
from pathlib import Path

from dpdp_lens.models import Finding, ScanResult, compute_counts, compute_score

CONTRACT = Path(__file__).resolve().parents[2] / "contract"


def load_sample() -> ScanResult:
    return ScanResult.model_validate_json((CONTRACT / "sample-scan.json").read_text())


def test_sample_validates_and_score_matches():
    scan = load_sample()
    assert len(scan.findings) >= 5
    assert scan.score == compute_score(scan.findings)
    assert scan.counts == compute_counts(scan.findings)


def test_score_floor_at_zero():
    base = load_sample().findings[0]
    many = [base.model_copy(update={"id": f"F-{i}"}) for i in range(10)]
    assert compute_score(many) == 0


def test_verified_fixed_does_not_cost_points():
    f = load_sample().findings[0]
    fixed = f.model_copy(update={"status": "verified_fixed"})
    assert compute_score([fixed]) == 100


def test_every_finding_check_has_clauses_in_clauses_json():
    clauses = json.loads((CONTRACT / "clauses.json").read_text())
    for f in load_sample().findings:
        assert f.check in clauses, f.check
        assert [c.ref for c in f.clauses] == [c["ref"] for c in clauses[f.check]]


def test_no_clause_the_rules_say_not_to_flag():
    # AGENTS.md section 6: Rule 8(1)/8(2) apply only to big platforms, never flag them for a small app.
    text = (CONTRACT / "clauses.json").read_text() + (CONTRACT / "sample-scan.json").read_text()
    assert "Rule 8(1)" not in text and "Rule 8(2)" not in text


def test_sample_has_no_raw_pii():
    text = (CONTRACT / "sample-scan.json").read_text()
    assert not re.search(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)", text)  # raw Aadhaar
    assert not re.search(r"\b[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]\b", text)  # raw PAN


def test_schema_file_matches_models():
    schema = json.loads((CONTRACT / "finding.schema.json").read_text())
    assert schema == ScanResult.model_json_schema(), "regenerate: see README, 'Contract schema'"
