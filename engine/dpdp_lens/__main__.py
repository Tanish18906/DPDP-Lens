"""CLI. `scan` is added in step 3; for now `sample` prints the contract sample scan."""
import argparse
import sys
from pathlib import Path

from .models import ScanResult

SAMPLE = Path(__file__).resolve().parents[2] / "contract" / "sample-scan.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dpdp_lens")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample", help="validate and print contract/sample-scan.json")
    args = parser.parse_args(argv)

    if args.cmd == "sample":
        scan = ScanResult.model_validate_json(SAMPLE.read_text())  # fails loudly if the sample drifts from the models
        print(scan.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
