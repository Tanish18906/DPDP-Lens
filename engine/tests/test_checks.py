import json

from dpdp_lens.checks import CHECKS, reason
from dpdp_lens.hints import semantic_hints
from test_contract import CONTRACT


def test_registry_ids_equal_clauses_json_ids():
    clauses = json.loads((CONTRACT / "clauses.json").read_text())
    assert set(CHECKS) == {k for k in clauses if not k.startswith("_")}


def test_every_check_has_text_and_reason_starts_with_its_severity():
    for c in CHECKS.values():
        assert c.title and c.detection and c.recommendation, c.id
        assert c.reason.startswith(c.severity.capitalize() + ":"), c.id


def test_reason_fills_facts():
    assert reason("log_pii", fields="email, aadhaar") == "High: email, aadhaar written to a log in plain text."


def test_semantic_hints_is_empty_for_now():
    assert semantic_hints(["foo"]) == {}
