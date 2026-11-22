"""CLI. `sample` prints the contract sample scan, `scan` audits a running target."""
import argparse
import json
import sys
from pathlib import Path

from .models import ScanResult
from .runner import run_scan
from .sarif import to_sarif

SAMPLE = Path(__file__).resolve().parents[2] / "contract" / "sample-scan.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dpdp_lens")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample", help="validate and print contract/sample-scan.json")
    scan_p = sub.add_parser("scan", help="scan a running target and write the scan JSON")
    scan_p.add_argument("--target", required=True, help="e.g. http://localhost:8000")
    scan_p.add_argument("--repo", required=True, help="target backend source folder")
    scan_p.add_argument("--db", required=True, help="target SQLite file (opened read only)")
    scan_p.add_argument("--out", help="write JSON here (default: print it)")
    scan_p.add_argument("--sarif", help="also write a SARIF 2.1.0 file here")
    args = parser.parse_args(argv)

    if args.cmd == "sample":
        scan = ScanResult.model_validate_json(SAMPLE.read_text())  # fails loudly if the sample drifts from the models
        print(scan.model_dump_json(indent=2))
    elif args.cmd == "scan":
        result = run_scan(args.target, args.repo, args.db)
        text = result.model_dump_json(indent=2)
        if args.sarif:
            Path(args.sarif).write_text(json.dumps(to_sarif(result), indent=2) + "\n")
        if args.out:
            Path(args.out).write_text(text + "\n")
            print(f"{result.scan_id}: score {result.score}, {len(result.findings)} findings -> {args.out}")
        else:
            print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
