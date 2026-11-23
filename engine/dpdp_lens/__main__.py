"""CLI. With no arguments it opens the interactive shell. `sample` prints the contract sample scan, `scan` audits a running target, `checks` lists every check and rule,
`report` renders the HTML report of a saved scan."""
import argparse
import json
import sys
from pathlib import Path

from . import checks_doc
from .models import ScanResult
from .report import render_report
from .runner import run_scan
from .sarif import to_sarif

SEV_ORDER = ["critical", "high", "medium", "low"]  # most severe first
SAMPLE = Path(__file__).resolve().parents[2] / "contract" / "sample-scan.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dpdp_lens")
    sub = parser.add_subparsers(dest="cmd")  # no command: the shell
    sub.add_parser("sample", help="validate and print contract/sample-scan.json")
    scan_p = sub.add_parser("scan", help="scan a running target and write the scan JSON")
    scan_p.add_argument("--target", required=True, help="e.g. http://localhost:8000")
    scan_p.add_argument("--repo", required=True, help="target backend source folder")
    scan_p.add_argument("--db", required=True, help="target SQLite file (opened read only)")
    scan_p.add_argument("--out", help="write JSON here (default: print it)")
    scan_p.add_argument("--sarif", help="also write a SARIF 2.1.0 file here")
    scan_p.add_argument("--pretty", action="store_true", help="print the grouped findings list instead of the JSON")
    scan_p.add_argument("--fail-on", choices=[*SEV_ORDER, "none"], default="none",
                        help="exit 1 if an open finding is at or above this severity (CI use)")
    checks_p = sub.add_parser("checks", help="list every check and the rules we wrote")
    fmt = checks_p.add_mutually_exclusive_group()
    fmt.add_argument("--md", action="store_true", help="Markdown (the default, same as docs/CHECKS.md)")
    fmt.add_argument("--json", action="store_true", help="JSON")
    report_p = sub.add_parser("report", help="render the HTML report of a saved scan JSON")
    report_p.add_argument("scan_json")
    report_p.add_argument("--out", required=True, help="write the HTML here")
    args = parser.parse_args(argv)

    if args.cmd is None:
        from .shell import main as shell_main  # imported here so the other commands do not need prompt_toolkit
        return shell_main()
    if args.cmd == "sample":
        scan = ScanResult.model_validate_json(SAMPLE.read_text())  # fails loudly if the sample drifts from the models
        print(scan.model_dump_json(indent=2))
    elif args.cmd == "checks":
        sys.stdout.write(checks_doc.to_json() if args.json else checks_doc.to_markdown())
    elif args.cmd == "report":
        Path(args.out).write_text(render_report(ScanResult.model_validate_json(Path(args.scan_json).read_text())))
        print(f"report -> {args.out}")
    elif args.cmd == "scan":
        result = run_scan(args.target, args.repo, args.db)
        text = result.model_dump_json(indent=2)
        if args.sarif:
            Path(args.sarif).write_text(json.dumps(to_sarif(result), indent=2) + "\n")
        if args.out:
            Path(args.out).write_text(text + "\n")
            print(f"{result.scan_id}: score {result.score}, {len(result.findings)} findings -> {args.out}")
        if args.pretty:
            from rich.console import Console
            from .shell import print_findings
            print_findings(Console(highlight=False), result)
        elif not args.out:
            print(text)
        if args.fail_on != "none":
            limit = SEV_ORDER.index(args.fail_on)
            return int(any(f.status == "open" and SEV_ORDER.index(f.severity) <= limit for f in result.findings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
