"""Block 02: policy file, evaluator, project config and the `ci` command."""
import json
import shutil
from pathlib import Path

import jsonschema
import pytest

from dpdp_lens import ci
from dpdp_lens.__main__ import main
from dpdp_lens.checks import CHECKS
from dpdp_lens.models import Clause, Evidence, Finding, Location, ScanError, ScanResult, compute_counts, compute_score
from dpdp_lens.policy import DEFAULT_ACTION, Policy, PolicyError, ProjectConfig, evaluate, load_baseline, load_config, load_policy
from dpdp_lens.sarif import to_sarif
from dpdp_lens.scanners import log_scan

ROOT = Path(__file__).resolve().parents[2]
TARGET_APP = ROOT / "target-app"
CLEAN = Path(__file__).parent / "fixtures" / "clean_app"
SARIF_SCHEMA = json.loads((Path(__file__).parent / "fixtures" / "sarif-schema-2.1.0.json").read_text())
POLICY = load_policy()
pytestmark = pytest.mark.usefixtures("with_late_scanners")  # the static scan needs config_scan and the other late scanners


def finding(n, check="log_pii", severity="high", layer="code", file="app/main.py", line=10):
    return Finding(id=f"F-{n:03d}", check=check, layer=layer, severity=severity, title=f"Title {n}", explanation="Explanation.",
                   clauses=[Clause(ref="Act s8(5)", note="safeguards")], fingerprint=f"{n:016x}",
                   evidence=Evidence(kind="code", summary="Summary", location=Location(file=file, line=line)))


def scan_of(*findings, complete=True):
    return ScanResult(scan_id="S-CI", target="", scanned_at="2026-11-24T00:00:00+00:00", score=compute_score(list(findings)),
                      counts=compute_counts(list(findings)), findings=list(findings), complete=complete)


# ---- policy file

def test_default_policy_has_one_rule_per_check_with_severity_defaults():
    assert set(POLICY.rules) == set(CHECKS)
    for check_id, rule in POLICY.rules.items():
        assert rule.action == DEFAULT_ACTION[CHECKS[check_id].severity], check_id
    assert len(POLICY.sha256) == 64 and POLICY.version == "1.0.0"


def test_policy_schema_file_matches_the_model():
    assert json.loads((ROOT / "contract" / "policy.schema.json").read_text()) == Policy.model_json_schema()


@pytest.mark.parametrize("edit, message", [
    (lambda d: d["rules"].update(not_a_check={"action": "block"}), "unknown check id"),
    (lambda d: d["rules"].update(log_pii={"action": "explode"}), "action"),
    (lambda d: d.update(version="v1"), "version"),
    (lambda d: d.update(surprise=1), "surprise"),
])
def test_invalid_policy_is_an_error(tmp_path, edit, message):
    import yaml
    data = yaml.safe_load(Path(load_policy.__globals__["DEFAULT_POLICY"]).read_text())
    edit(data)
    path = tmp_path / "p.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(PolicyError, match=message):
        load_policy(path)


def test_invalid_config_is_an_error(tmp_path):
    for text in ("block_on: [urgent]", "unknown_key: 1", "suppress: [{fingerprint: abc, reason: r, by: me}]", "- a list"):
        (tmp_path / "c.yml").write_text(text)
        with pytest.raises(PolicyError):
            load_config(tmp_path / "c.yml")
    assert load_config(None) == ProjectConfig() and load_config(None).categories == ["code", "config", "frontend"]


# ---- evaluator

@pytest.mark.parametrize("findings, complete, decision", [
    ([], True, "pass"),
    ([finding(1, "missing_contact", "low", "notice")], True, "pass"),  # info only
    ([finding(1, "config_cors_wildcard", "medium", "config")], True, "warn"),
    ([finding(1), finding(2, "config_cors_wildcard", "medium", "config")], True, "fail"),
    ([], False, "incomplete"),  # nothing found does not make an unfinished scan a pass
    ([finding(1)], False, "incomplete"),  # and a failing one is still reported as incomplete
])
def test_decision_matrix(findings, complete, decision):
    assert evaluate(scan_of(*findings, complete=complete), POLICY).decision == decision


def test_new_only_uses_the_baseline():
    scan = scan_of(finding(1), finding(2, "config_cors_wildcard", "medium", "config"))
    base = {finding(1).fingerprint, finding(2).fingerprint}
    ev = evaluate(scan, POLICY, baseline_fps=base, new_only=True)
    assert ev.decision == "pass" and [i.is_new for i in ev.items] == [False, False]  # known findings do not warn either
    assert evaluate(scan, POLICY, baseline_fps=base, new_only=False).decision == "fail"
    ev = evaluate(scan_of(finding(1), finding(3)), POLICY, baseline_fps={finding(1).fingerprint}, new_only=True)
    assert ev.decision == "fail" and [i.fingerprint for i in ev.blocking()] == [finding(3).fingerprint]


def test_suppression_and_incomplete_scans():
    scan = scan_of(finding(1))
    ev = evaluate(scan, POLICY, suppressed_fps={finding(1).fingerprint})
    assert ev.decision == "pass" and ev.items[0].suppressed
    assert evaluate(scan_of(finding(1), complete=False), POLICY, suppressed_fps={finding(1).fingerprint}).decision == "incomplete"


def test_project_config_overrides_and_categories():
    scan = scan_of(finding(1), finding(2, "config_cors_wildcard", "medium", "config"), finding(3, "api_idor", "critical", "api"))
    assert evaluate(scan, POLICY, ProjectConfig(warn_on=["high"])).decision == "warn"  # the config only names high: critical is outside the scan categories
    assert evaluate(scan, POLICY, ProjectConfig(block_on=["medium"], categories=["config"])).decision == "fail"
    ev = evaluate(scan, POLICY, ProjectConfig())
    assert ev.excluded == 1 and "api_idor" not in [i.check for i in ev.items]


def test_policy_rule_severity_override_and_missing_rule():
    policy = Policy.model_validate({"policy_id": "p", "version": "2.0.0", "effective_date": "2026-01-01",
                                    "rules": {"log_pii": {"action": "warn", "severity_override": "low"}}})
    ev = evaluate(scan_of(finding(1), finding(2, "config_debug_enabled", "medium", "config")), policy)
    assert [(i.severity, i.action) for i in ev.items] == [("low", "warn"), ("medium", "warn")]  # a check without a rule gets its severity default


# ---- summary

def test_summary_markdown_snapshot():
    scan = scan_of(finding(1, file="backend/app/main.py", line=87), finding(2, "config_cors_wildcard", "medium", "config", file="a|b.py"))
    ev = evaluate(scan, POLICY, baseline_fps={finding(2).fingerprint}, new_only=True)
    assert ci.summary_md(scan, ev) == "\n".join([
        "## DPDP Lens: FAIL", "", "1 blocking, 0 warning, 0 info. Policy dpdp-lens-default 1.0.0.", "",
        "### New blocking findings", "", "| Finding | Check | File:line | Clause |", "|---|---|---|---|",
        "| F-001 | log_pii | backend/app/main.py:87 | Act s8(5) |", "", "1 existing findings in baseline.", "",
        "Coverage: static checks only, 0 of 19.", "", "_Readiness report, not a compliance certificate._", ""])
    assert "a\\|b.py" in ci.summary_md(scan_of(finding(2, file="a|b.py")), evaluate(scan_of(finding(2, file="a|b.py")), POLICY))


def test_summary_of_an_incomplete_scan_says_so():
    scan = scan_of(complete=False).model_copy(update={"scan_errors": [ScanError(scanner="log_scan", kind="failed", message="boom")]})
    text = ci.summary_md(scan, evaluate(scan, POLICY))
    assert text.startswith("## DPDP Lens: INCOMPLETE") and "not a pass" in text and "`log_scan` failed: boom" in text


# ---- the ci command

def run_ci(*args):
    return main(["ci", *map(str, args)])


def test_ci_clean_app_passes(tmp_path):
    out = tmp_path / "ci.json"
    assert run_ci("--repo-dir", CLEAN, "--json", out) == 0
    assert json.loads(out.read_text())["evaluation"]["decision"] == "pass"


def test_ci_target_app_fails_with_block_rules_and_writes_outputs(tmp_path, capsys):
    out, sarif, md = tmp_path / "ci.json", tmp_path / "ci.sarif", tmp_path / "ci.md"
    assert run_ci("--repo-dir", TARGET_APP, "--json", out, "--sarif", sarif, "--summary", md) == 1
    data = json.loads(out.read_text())
    blocking = [i for i in data["evaluation"]["items"] if i["action"] == "block"]
    assert data["evaluation"]["decision"] == "fail" and {"log_pii", "config_secret_committed"} <= {i["check"] for i in blocking}
    assert data["coverage"]["mode"] == "static" and data["evaluation"]["policy_sha256"]
    assert md.read_text().startswith("## DPDP Lens: FAIL") and "backend/app/main.py:87" in md.read_text()
    sarif_doc = json.loads(sarif.read_text())
    jsonschema.Draft4Validator(SARIF_SCHEMA).validate(sarif_doc)
    results = sarif_doc["runs"][0]["results"]
    assert results and all("://" not in r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in results)
    assert all(r["partialFingerprints"]["dpdpLens/v1"] for r in results)
    assert "fail:" in capsys.readouterr().out


def test_ci_scanner_failure_exits_2_never_0(monkeypatch, tmp_path, capsys):
    def boom(_):
        raise RuntimeError("boom")
    monkeypatch.setattr(log_scan, "scan", boom)
    out = tmp_path / "ci.json"
    assert run_ci("--repo-dir", CLEAN, "--json", out) == 2
    assert "INCOMPLETE: 1 scanner errors (log_scan)" in capsys.readouterr().err
    assert json.loads(out.read_text())["evaluation"]["decision"] == "incomplete"
    assert main(["scan", "--static", "--repo", str(CLEAN)]) == 2  # same rule for the scan command
    assert "INCOMPLETE" in capsys.readouterr().err
    assert run_ci("--repo-dir", CLEAN, "--write-baseline", "--baseline", tmp_path / "b.json") == 2
    assert not (tmp_path / "b.json").exists()  # a baseline of an unfinished scan would hide findings


def test_ci_baseline_flow(tmp_path):
    base = tmp_path / "base.json"
    assert run_ci("--repo-dir", TARGET_APP, "--write-baseline", "--baseline", base) == 0
    data = json.loads(base.read_text())
    assert data["version"] == 1 and data["fingerprints"] and set(data["fingerprints"][0]) == {"fp", "check", "title", "file"}
    assert len({e["fp"] for e in data["fingerprints"]}) == len(data["fingerprints"])  # the three secrets are told apart
    assert load_baseline(base) == {e["fp"] for e in data["fingerprints"]}
    assert run_ci("--repo-dir", TARGET_APP, "--new-only", "--baseline", base) == 0
    app = tmp_path / "app"
    shutil.copytree(TARGET_APP, app, ignore=shutil.ignore_patterns("node_modules", "__pycache__", "*.db", "*.log"))
    with open(app / "backend" / "app" / "main.py", "a") as f:
        f.write('\nlogger.info("x %s", req.aadhaar)\n')
    out = tmp_path / "new.json"
    assert run_ci("--repo-dir", app, "--new-only", "--baseline", base, "--json", out) == 1
    new = [i for i in json.loads(out.read_text())["evaluation"]["items"] if i["is_new"]]
    assert [i["check"] for i in new] == ["log_pii"]


def test_ci_project_config_suppress_and_paths(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(TARGET_APP, repo, ignore=shutil.ignore_patterns("node_modules", "__pycache__", "*.db", "*.log"))
    out = tmp_path / "scan.json"
    run_ci("--repo-dir", repo, "--json", out)
    fps = [i["fingerprint"] for i in json.loads(out.read_text())["evaluation"]["items"] if i["action"] == "block"]
    suppress = "".join(f"  - {{fingerprint: {fp}, reason: accepted for the demo, by: tanish}}\n" for fp in fps)
    (repo / ".dpdp-lens.yml").write_text(f"suppress:\n{suppress}")  # found by default in --repo-dir
    assert run_ci("--repo-dir", repo) == 0


@pytest.mark.parametrize("args", [["--config", "missing.yml"], ["--new-only", "--baseline", "missing.json"], ["--repo-dir", "no-such-folder"]])
def test_ci_invalid_input_exits_2(tmp_path, args, capsys):
    assert run_ci("--repo-dir", CLEAN, *args) == 2 if "--repo-dir" not in args else run_ci(*args) == 2
    assert capsys.readouterr().err.startswith("ERROR:")


def test_ci_invalid_policy_exits_2(tmp_path, capsys):
    (tmp_path / "bad.yaml").write_text("policy_id: x\nversion: nope\neffective_date: 2026-01-01\nrules: {}\n")
    (tmp_path / ".dpdp-lens.yml").write_text("policy: bad.yaml\n")
    assert run_ci("--repo-dir", CLEAN, "--config", tmp_path / ".dpdp-lens.yml") == 2
    assert "version" in capsys.readouterr().err


def test_ci_paths_are_repo_relative_when_backend_stands_alone(tmp_path):
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)
    (repo / "backend" / "main.py").write_text("import logging\nlogger = logging.getLogger('x')\nlogger.info('%s', user.aadhaar)\n")
    out = tmp_path / "ci.json"
    assert run_ci("--repo-dir", repo, "--json", out) == 1
    assert [f["evidence"]["location"]["file"] for f in json.loads(out.read_text())["findings"] if f["check"] == "log_pii"] == ["backend/main.py"]


def test_scan_static_flag_needs_no_target_or_db(tmp_path):
    out = tmp_path / "s.json"
    assert main(["scan", "--static", "--repo", str(CLEAN), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["coverage"]["mode"] == "static"
    with pytest.raises(SystemExit):
        main(["scan", "--repo", str(CLEAN)])  # without --static it still needs both


def test_sarif_of_sample_scan_validates():
    sample = ScanResult.model_validate_json((ROOT / "contract" / "sample-scan.json").read_text())
    jsonschema.Draft4Validator(SARIF_SCHEMA).validate(to_sarif(sample))
