"""Scanner accuracy on the labelled corpus (block 06). A change that lowers a number fails here; a change that raises one
raises the floor in tests/accuracy/floors.json (python -m dpdp_lens.eval --floors) and the History in docs/ACCURACY.md."""
import json
import re
from pathlib import Path

import pytest

from dpdp_lens import eval as acc

ROOT = Path(__file__).resolve().parents[2]
FLOORS = json.loads((acc.CORPUS / "floors.json").read_text())["checks"]


@pytest.fixture(scope="module")
def report():
    return acc.evaluate()


def test_no_check_is_less_precise_or_finds_less_than_its_floor(report):
    for name, floor in FLOORS.items():
        got = report["checks"][name]
        assert got["recall"] >= floor["recall"] - 1e-9, f"{name} recall {got['recall']} < {floor['recall']}: {got['misses']}"
        assert got["precision"] >= floor["precision"] - 1e-9, f"{name} precision {got['precision']} < {floor['precision']}: {got['misses']}"


def test_every_checked_name_has_a_floor_and_the_floors_are_not_above_the_numbers(report):
    assert set(FLOORS) == set(report["checks"])


def test_tutornest_static_scan_finds_every_planted_violation_and_nothing_extra(report):
    t = report["tutornest"]
    assert (t["fp"], t["fn"]) == (0, 0) and t["tp"] == 11, t["misses"]


def test_the_corpus_has_positives_and_hard_negatives_for_every_scanner_check():
    for check in acc.CHECK_SCANNERS:
        names = [p.name for p in (acc.CORPUS / "cases" / check).iterdir()]
        assert any(n.startswith("pos_") for n in names) and any(n.startswith("neg_") for n in names), check


def test_accuracy_md_part_above_history_is_current(report):
    text = (ROOT / "docs" / "ACCURACY.md").read_text()
    assert text.startswith(acc.to_markdown(report)), "regenerate: cd engine && python -m dpdp_lens.eval --md > ../docs/ACCURACY.md, then re-add the History section"
    assert "\n## History" in text


def test_no_token_shaped_string_is_committed_in_the_corpus():
    """Tokens are built at run time (eval.tokens). A literal one would also trip GitHub push protection."""
    bad = re.compile(r"AKIA[0-9A-Z]{12}|ghp_[A-Za-z0-9]{20}|github_pat_[A-Za-z0-9_]{20}|xox[bp]-[0-9A-Za-z-]{10}|sk_live_[0-9A-Za-z]{10}")
    hits = [str(p.relative_to(acc.CORPUS)) for p in acc.CORPUS.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.name != "floors.json" and bad.search(p.read_text(errors="replace"))]
    assert hits == []


def test_eval_prints_no_value(report):
    out = acc.to_text(report) + acc.to_markdown(report)
    for value in acc.tokens().values():
        assert value not in out


def test_eval_runs_as_a_module(capsys):
    assert acc.main([]) == 0
    assert "OVERALL (corpus)" in capsys.readouterr().out
