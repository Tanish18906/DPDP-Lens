"""The shell (phase C1). No live stack: the sample scan is loaded into the shell and scan or fix functions are stubs."""
import io
import re
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console

from dpdp_lens import __main__ as cli
from dpdp_lens.checks import CHECKS
from dpdp_lens.fixer.verify import Verification
from dpdp_lens.models import Fix, ScanResult, compute_counts, compute_score
from dpdp_lens.shell import COMMANDS, Shell, clean

SAMPLE = Path(__file__).resolve().parents[2] / "contract" / "sample-scan.json"
ENGINE = Path(__file__).resolve().parents[1]
NO_SCAN = "No scan yet. Run /scan first."
EVIL = "[red]boom[/red] \x1b[31m \x1b]0;pwned\x07 end"


def sample() -> ScanResult:
    return ScanResult.model_validate_json(SAMPLE.read_text())


def make(width=80, tty=False, **kw):
    out = io.StringIO()
    console = Console(file=out, width=width, force_terminal=tty, color_system="standard" if tty else None, highlight=False)
    return Shell(console, **kw), out


def run(shell, out, line):
    out.truncate(0), out.seek(0)
    assert shell.handle(line) is True
    return out.getvalue()


@pytest.mark.parametrize("width", [80, 140])
def test_findings_are_grouped_critical_first_with_summary(width):
    sh, out = make(width)
    sh.load(sample())
    text = run(sh, out, "/findings")
    assert text.index("● F-001  critical") < text.index("  high  ") < text.index("  medium  ")
    assert "  ⎿ api · http://localhost:8000/api/students · Act s8(5), Rule 6(1)(b)" in text
    assert "Score 73/100 · 1 critical · 3 high · 1 medium · 0 low" in text
    assert "Readiness report, not a compliance certificate." in text
    assert all(len(line) <= width for line in text.splitlines())


@pytest.mark.parametrize("width", [80, 140])
def test_show_has_labelled_lines(width):
    sh, out = make(width)
    sh.load(sample())
    text = run(sh, out, "/show f-001")
    assert text.startswith("● F-001  critical  ")
    for label in ("Why", "What", "Where", "Clauses", "Evidence", "Fix"):
        assert f"  ⎿ {label} " in text
    assert "Verified fix available: yes" in text
    assert "Act s8(5) (" in text
    assert all(len(line) <= width for line in text.splitlines())


def test_long_path_wraps_under_the_text_not_the_marker():
    s = sample()
    f = s.findings[1].model_copy(update={"evidence": s.findings[1].evidence.model_copy(
        update={"location": s.findings[1].evidence.location.model_copy(update={"file": "a/" * 60 + "main.py"})})})
    sh, out = make(80)
    sh.load(s.model_copy(update={"findings": [f]}))
    lines = run(sh, out, "/findings").splitlines()
    cont = [ln for ln in lines if ln.startswith("    ") and "main.py" in ln]
    assert cont and all(len(ln) <= 80 for ln in lines)


def test_checks_help_status_and_unknown():
    sh, out = make()
    assert all(cid in run(sh, out, "/checks") for cid in CHECKS)
    assert all(name in run(sh, out, "/help") for name in COMMANDS)
    assert "no scan yet" in run(sh, out, "/status")
    text = run(sh, out, "/nope")
    assert "Unknown command: /nope" in text and "try /help" in text
    assert "Commands start with /" in run(sh, out, "hello")
    assert sh.handle("/quit") is False and sh.handle("/exit") is False


def test_commands_before_a_scan_say_so():
    sh, out = make()
    for line in ("/findings", "/show F-001", "/fix F-001", "/report"):
        assert NO_SCAN in run(sh, out, line)


def test_show_and_fix_with_a_bad_id():
    sh, out = make()
    sh.load(sample())
    assert "No finding F-999" in run(sh, out, "/show F-999")
    assert "No finding F-999" in run(sh, out, "/fix F-999")
    assert "give a finding id" in run(sh, out, "/show")


def test_report_writes_a_file(tmp_path):
    sh, out = make(root=tmp_path)
    sh.load(sample())
    assert "Report" in run(sh, out, "/report")
    assert (tmp_path / "reports" / "last-scan.html").read_text().startswith("<!doctype html>")
    run(sh, out, f"/report {tmp_path / 'x' / 'r.html'}")
    assert (tmp_path / "x" / "r.html").is_file()


def test_injection_is_plain_text_and_has_no_escape_bytes():
    s = sample()
    f = s.findings[0]
    evil = f.model_copy(update={
        "title": EVIL, "explanation": EVIL, "severity_reason": EVIL, "recommendation": EVIL,
        "evidence": f.evidence.model_copy(update={
            "summary": EVIL, "masked_sample": EVIL,
            "location": f.evidence.location.model_copy(update={"column": EVIL, "table": EVIL, "file": EVIL})})})
    for tty in (False, True):
        sh, out = make(100, tty=tty)
        sh.load(s.model_copy(update={"findings": [evil]}))
        text = "".join(run(sh, out, line) for line in ("/findings", "/show F-001", "/fix F-001"))
        assert "[red]boom[/red]" in text, tty
        assert "\x07" not in text and "pwned" not in text
        assert "\x1b]" not in text  # rich itself never writes an OSC here, so any would come from the data
        if not tty:
            assert "\x1b" not in text


def test_clean_strips_escapes_and_controls():
    assert clean("a\x1b[31mb\x1b]0;t\x07c\x00d‮e\r") == "abcde"
    assert clean("x\ny", nl=False) == "x y" and clean("x\ny", nl=True) == "x\ny"


def test_piped_shell_runs_end_to_end():
    r = subprocess.run([sys.executable, "-m", "dpdp_lens"], cwd=ENGINE, input="/help\n/findings\n/exit\n",
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "◈ DPDP Lens" in r.stdout and "/scan" in r.stdout and NO_SCAN in r.stdout
    assert "\x1b" not in r.stdout and not r.stderr


def test_piped_shell_ends_on_eof():
    r = subprocess.run([sys.executable, "-m", "dpdp_lens"], cwd=ENGINE, input="/help\n", capture_output=True, text=True, timeout=60)
    assert r.returncode == 0


def fake_scan(tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "x.db").write_bytes(b"")

    def scan_fn(target, repo, db, scan_id, progress, found):
        progress("db_scan", 0, 2), found("db_scan", 3)
        progress("log_scan", 1, 2), found("log_scan", None)
        return sample().model_copy(update={"scan_id": scan_id, "target": target})
    return scan_fn


@pytest.mark.parametrize("tty", [False, True])
def test_scan_streams_found_lines(tmp_path, tty):
    sh, out = make(tty=tty, root=tmp_path, scan_fn=fake_scan(tmp_path))
    text = re.sub(r"\x1b\[[0-9;]*m", "", run(sh, out, "/scan --repo repo --db x.db"))  # rich's own colours
    assert "Using target http://localhost:8000 · repo repo · db x.db" in text
    assert "DATABASE   found 3" in text and "CODE       did not finish" in text
    assert "Score 73/100" in text
    assert sh.scan.scan_id == "S-001" and "S-001 · score 73" in sh.toolbar()
    if not tty:
        assert "✻" not in text


def test_scan_errors_are_one_line(tmp_path):
    sh, out = make(root=tmp_path, scan_fn=fake_scan(tmp_path))
    assert "target must be http(s) on localhost" in run(sh, out, "/scan --target http://example.com")
    assert "repo is not a folder" in run(sh, out, "/scan --repo nope --db x.db")
    assert "db is not a file" in run(sh, out, "/scan --repo repo --db nope.db")
    assert "unrecognized arguments" in run(sh, out, "/scan --bogus")

    def boom(*a, **k):
        raise ConnectionError("target down\nsecond line")
    sh.scan_fn = boom
    text = run(sh, out, "/scan --repo repo --db x.db")
    assert "ConnectionError: target down" in text and "Traceback" not in text and "second line" not in text


def verified(diff="--- a/app/main.py\n+++ b/app/main.py\n@@ -10,2 +10,2 @@\n ctx\n-old line\n+new line\n"):
    return lambda finding, repo, db, **kw: Verification(
        fix=Fix(available=True, diff=diff, verified=True, rescan_passed=True, tests_passed=True, score_before=kw["score_before"]),
        rescan=None, tests_output="", log={"total_ms": 2900})


def test_fix_shows_steps_diff_and_score():
    sh, out = make(fix_fn=verified())
    sh.load(sample(), ("repo", "db"))
    text = run(sh, out, "/fix F-001")
    for part in ("● Fix F-001", "(runs on a copy, your code is not touched)", "⎿ Patched   app/main.py", "⎿ Re-scan   passed",
                 "⎿ Tests     passed", "⎿ Verified  ✓", "  10 ", "- old line", "+ new line", "@@ -10,2 +10,2 @@",
                 "Score 73 → 83 (+10)"):
        assert part in text, part
    assert sh.scan.score == 83 and sh.scan.findings[0].status == "verified_fixed"
    assert "already fixed" in run(sh, out, "/fix F-001")
    assert sh.fix_modes["F-001"]["mode"] == "live"


def test_fix_falls_back_to_cached_and_says_so():
    def broken(*a, **k):
        raise RuntimeError("sandbox failed")
    sh, out = make(fix_fn=broken)
    sh.load(sample(), ("repo", "db"))
    text = run(sh, out, "/fix F-001")
    assert "Cached golden patch mode: RuntimeError: sandbox failed" in text and "⎿ Verified  ✓" in text
    assert sh.fix_modes["F-001"]["mode"] == "cached_golden"


def test_fix_cached_flag_is_labelled():
    sh, out = make()
    sh.load(sample(), ("repo", "db"))
    assert "Cached golden patch mode: saved result replayed on request" in run(sh, out, "/fix F-001 --cached")


def test_fix_without_a_template_prints_the_recommendation():
    sh, out = make()
    s = sample()
    sh.load(s, ("repo", "db"))
    text = run(sh, out, "/fix F-003")
    assert "No automated fix" in text and s.findings[2].recommendation[:30] in text and "Error" not in text


def test_fix_not_verified_makes_no_score_claim():
    bad = lambda finding, repo, db, **kw: Verification(  # noqa: E731
        fix=Fix(available=True, diff="", verified=False, rescan_passed=False, tests_passed=True), rescan=None, tests_output="")
    sh, out = make(fix_fn=bad)
    sh.load(sample(), ("repo", "db"))
    text = run(sh, out, "/fix F-001")
    assert "✗ not verified" in text and "Not verified. Score stays 73." in text and "→" not in text
    assert sh.scan.score == 73


def test_interrupt_returns_to_the_prompt(tmp_path):
    def stop(*a, **k):
        raise KeyboardInterrupt
    sh, out = make(root=tmp_path, scan_fn=stop)
    (tmp_path / "repo").mkdir(), (tmp_path / "x.db").write_bytes(b"")
    assert "Interrupted" in run(sh, out, "/scan --repo repo --db x.db")
    sh.load(sample(), ("repo", "db"))
    sh.fix_fn = stop
    assert "Interrupted" in run(sh, out, "/fix F-001")


# -- scan --pretty and --fail-on

def stub_scan(monkeypatch, findings=None):
    s = sample()
    if findings is not None:
        s = s.model_copy(update={"findings": findings, "score": compute_score(findings), "counts": compute_counts(findings)})
    monkeypatch.setattr(cli, "run_scan", lambda *a, **k: s)
    return s


def scan_cmd(*extra):
    return ["scan", "--target", "http://localhost:8000", "--repo", "r", "--db", "d", *extra]


@pytest.mark.parametrize("level,code", [("none", 0), ("critical", 1), ("high", 1), ("medium", 1), ("low", 1)])
def test_fail_on_with_an_open_critical(monkeypatch, capsys, level, code):
    stub_scan(monkeypatch)
    assert cli.main(scan_cmd("--fail-on", level)) == code


def test_fail_on_counts_only_open_findings_at_or_above(monkeypatch, capsys):
    s = sample()
    fixed = s.findings[0].model_copy(update={"status": "verified_fixed"})
    stub_scan(monkeypatch, [fixed, s.findings[1], s.findings[4]])  # fixed critical, one high, one medium
    assert cli.main(scan_cmd("--fail-on", "critical")) == 0
    assert cli.main(scan_cmd("--fail-on", "high")) == 1
    stub_scan(monkeypatch, [fixed, s.findings[4]])
    assert cli.main(scan_cmd("--fail-on", "high")) == 0
    assert cli.main(scan_cmd("--fail-on", "medium")) == 1
    stub_scan(monkeypatch, [])
    assert cli.main(scan_cmd("--fail-on", "low")) == 0


def test_pretty_prints_the_list_and_out_still_writes_json(monkeypatch, capsys, tmp_path):
    s = stub_scan(monkeypatch)
    assert cli.main(scan_cmd("--pretty", "--out", str(tmp_path / "s.json"))) == 0
    text = capsys.readouterr().out
    assert "● F-001  critical" in text and "Score 73/100" in text and '"findings"' not in text
    assert ScanResult.model_validate_json((tmp_path / "s.json").read_text()) == s
    cli.main(scan_cmd())
    assert '"findings"' in capsys.readouterr().out  # the default is still the JSON dump
