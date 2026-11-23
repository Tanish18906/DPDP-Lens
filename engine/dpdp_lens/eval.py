"""Scanner accuracy on a labelled corpus (block 06): precision and recall per check, measured, never claimed.

    cd engine && python -m dpdp_lens.eval [--json | --md | --floors] [--corpus DIR]

The corpus is engine/tests/accuracy/:
  cases/<check id>/<pos|neg>_<name>/<files>   one small app per case. `pos` means the check must fire, `neg` that it must not.
                                              A file name starting DOT_ is written with a "." (DOT_env becomes .env). {{aws}},
                                              {{ghp}}, {{ghpat}}, {{slack}}, {{stripe}} become fake tokens built here at run time, so no
                                              token-shaped string is committed.
  recognizers.json                            text snippets for find_pii and the personal data types they must (not) report.
  tutornest.json                              the planted violations the static scan of target-app must find, and nothing else.

Scoring is per case: a pos case with at least one finding of its check is a true positive, without one a false negative; a neg case
with one is a false positive. Recognizer cases are scored per type. Only masked output is ever printed: no value is shown."""
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from stdnum import verhoeff

from .recognizers import find_pii
from .runner import run_scan
from .scanners import config_scan, consent_scan, frontend_scan, log_scan

ENGINE = Path(__file__).resolve().parents[1]
CORPUS = ENGINE / "tests" / "accuracy"
TARGET_APP = ENGINE.parent / "target-app"


def _aadhaar(prefix="23412341234") -> str:
    return prefix + verhoeff.calc_check_digit(prefix)


def tokens() -> dict[str, str]:
    """Fake secrets with the shapes of real ones, joined here so the source never holds a whole token."""
    good = _aadhaar()
    return {
        "aws": "AK" + "IA" + "IOSFODNN7EXAMPLE",
        "ghp": "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
        "ghpat": "github_" + "pat_" + "11ABCDEFG0aBcDeFgHiJkL_mNoPqRsTuVwXyZ0123456789aBcDeFgHiJkLmNoPq",
        "slack": "xo" + "xb-" + "123456789012-1234567890123-aBcDeFgHiJkLmNoPqRsTuVwX",
        "stripe": "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc",
        "aadhaar": good,
        "aadhaar_spaced": f"{good[:4]} {good[4:8]} {good[8:]}",
        "aadhaar_dashed": f"{good[:4]}-{good[4:8]}-{good[8:]}",
        "aadhaar_bad": good[:-1] + str((int(good[-1]) + 1) % 10),
        "aadhaar_one": "1" + good[1:-1] + verhoeff.calc_check_digit("1" + good[1:-1]),
    }


# Which scanner produces which check, run on a folder that stands for the app root. All static, nothing is started.
CHECK_SCANNERS = {
    **{c: config_scan.scan for c in ("config_secret_committed", "config_env_in_image", "config_container_root", "config_cors_wildcard",
                                     "config_debug_enabled", "config_db_exposed")},
    "log_pii": log_scan.scan,
    "fe_pii_in_storage": frontend_scan.scan,
    "consent_not_recorded": lambda root: consent_scan.scan("", root),
}


@dataclass
class Tally:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    misses: list = field(default_factory=list)  # names of the cases that went wrong, for the report (never any value)

    @property
    def precision(self):
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self):
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    def add(self, predicted: bool, expected: bool, name: str):
        key = ("tp" if predicted else "fn") if expected else ("fp" if predicted else "tn")
        setattr(self, key, getattr(self, key) + 1)
        if key in ("fp", "fn"):
            self.misses.append(f"{key.upper()} {name}")

    def as_dict(self):
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn, "precision": self.precision, "recall": self.recall,
                "misses": self.misses}


def materialise(case: Path, dest: Path, subs: dict[str, str]):
    for f in sorted(p for p in case.rglob("*") if p.is_file()):
        rel = f.relative_to(case)
        out = dest / Path(*[("." + part[4:]) if part.startswith("DOT_") else part for part in rel.parts])
        out.parent.mkdir(parents=True, exist_ok=True)
        text = f.read_text()
        for key, value in subs.items():
            text = text.replace("{{" + key + "}}", value)
        out.write_text(text)


def run_file_cases(corpus: Path) -> dict[str, Tally]:
    results, subs = {}, tokens()
    for check_dir in sorted(p for p in (corpus / "cases").iterdir() if p.is_dir()):
        check, scan = check_dir.name, CHECK_SCANNERS[check_dir.name]
        tally = results.setdefault(check, Tally())
        for case in sorted(p for p in check_dir.iterdir() if p.is_dir()):
            with tempfile.TemporaryDirectory(prefix="dpdp-eval-") as tmp:
                root = Path(tmp) / "app"
                root.mkdir()
                materialise(case, root, subs)
                predicted = any(f.check == check for f in scan(str(root)))
            tally.add(predicted, case.name.startswith("pos_"), f"{check}/{case.name}")
    return results


def run_recognizer_cases(corpus: Path) -> dict[str, Tally]:
    results, subs = {}, tokens()
    for case in json.loads((corpus / "recognizers.json").read_text()):
        text = case["text"]
        for key, value in subs.items():
            text = text.replace("{{" + key + "}}", value)
        found = {t for t, *_ in find_pii(text, case["column"])}
        for kind in sorted(found | set(case["expect"])):
            results.setdefault(f"pii_{kind}", Tally()).add(kind in found, kind in case["expect"], f"pii_{kind}/{case['id']}")
    return results


def run_tutornest(corpus: Path) -> Tally:
    """Static scan of the demo app against its ground truth: every planted violation found, nothing extra."""
    truth = {(g["check"], g["file"]) for g in json.loads((corpus / "tutornest.json").read_text())["expected"]}
    result = run_scan("", str(TARGET_APP / "backend"), "", mode="static")
    got = {(f.check, f.evidence.location.file) for f in result.findings}
    tally = Tally(tp=len(truth & got), fp=len(got - truth), fn=len(truth - got))
    tally.misses = [f"FN {c} {f}" for c, f in sorted(truth - got)] + [f"FP {c} {f}" for c, f in sorted(got - truth)]
    return tally


def evaluate(corpus: Path = CORPUS) -> dict:
    checks = {**run_file_cases(corpus), **run_recognizer_cases(corpus)}
    overall = Tally()
    for t in checks.values():
        overall.tp, overall.fp, overall.fn, overall.tn = overall.tp + t.tp, overall.fp + t.fp, overall.fn + t.fn, overall.tn + t.tn
    return {"checks": {k: v.as_dict() for k, v in checks.items()}, "overall": overall.as_dict(), "tutornest": run_tutornest(corpus).as_dict()}


def pct(x):
    return "n/a" if x is None else f"{x * 100:.0f}%"


def table(report: dict) -> list[list[str]]:
    rows = [[name, str(t["tp"]), str(t["fp"]), str(t["fn"]), str(t["tn"]), pct(t["precision"]), pct(t["recall"])]
            for name, t in sorted(report["checks"].items())]
    o, n = report["overall"], report["tutornest"]
    rows.append(["OVERALL (corpus)", str(o["tp"]), str(o["fp"]), str(o["fn"]), str(o["tn"]), pct(o["precision"]), pct(o["recall"])])
    rows.append(["TutorNest static ground truth", str(n["tp"]), str(n["fp"]), str(n["fn"]), "-", pct(n["precision"]), pct(n["recall"])])
    return rows


HEAD = ["Check", "TP", "FP", "FN", "TN", "Precision", "Recall"]


def to_text(report: dict) -> str:
    rows = [HEAD, *table(report)]
    widths = [max(len(r[i]) for r in rows) for i in range(len(HEAD))]
    out = ["  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(r, widths))) for r in rows]
    misses = [m for t in [*report["checks"].values(), report["tutornest"]] for m in t["misses"]]
    return "\n".join(out + ["", f"{len(misses)} misses:", *[f"  {m}" for m in misses]]) + "\n"


def to_markdown(report: dict) -> str:
    rows = "\n".join("| " + " | ".join(r) + " |" for r in table(report))
    misses = "\n".join(f"- `{m}`" for t in [*report["checks"].values(), report["tutornest"]] for m in t["misses"]) or "- none"
    return f"""# Scanner accuracy

Generated by `cd engine && python -m dpdp_lens.eval --md`. Do not edit above the History heading: a test fails when this part is out of date.

How it is measured: a labelled corpus in `engine/tests/accuracy/` (one small app per case, marked `pos` or `neg`, with hard negatives such as
placeholder secrets, numbers that look like an Aadhaar or a phone number, test files and comments). A `pos` case is a true positive when
its check fires, a false negative when it does not; a `neg` case that fires is a false positive. The recognizers (`pii_*`) are scored per
type on text snippets. The TutorNest row compares the static scan of `target-app/backend` with the planted violations and the one real
secret (`app/auth.py`). Live checks (API, database, browser) are not in this corpus. The corpus is small and written by us, so these numbers
describe it, not code in general.

## Current numbers

| {" | ".join(HEAD)} |
|{"|".join("---" for _ in HEAD)}|
{rows}

## Misses (every false positive and false negative)

{misses}
"""


def register(sub) -> None:
    """For __main__.py: add this module to its MODULES list and `python -m dpdp_lens eval` works too."""
    p = sub.add_parser("eval", help="precision and recall of the scanners on the labelled corpus (engine/tests/accuracy)")
    p.add_argument("--json", action="store_true", help="the full report as JSON")
    p.add_argument("--md", action="store_true", help="the Markdown of docs/ACCURACY.md (above its History heading)")
    p.add_argument("--floors", action="store_true", help="the least precision and recall the test accepts, as JSON")
    p.add_argument("--corpus", help="a corpus folder (default: engine/tests/accuracy)")
    p.set_defaults(func=lambda a: main([f for f in ("--json", "--md", "--floors") if getattr(a, f[2:])] + (["--corpus", a.corpus] if a.corpus else [])))


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    corpus = Path(args[args.index("--corpus") + 1]) if "--corpus" in args else CORPUS
    report = evaluate(corpus)
    if "--floors" in args:  # the least precision and recall a test accepts for each check: raise them when a change improves a number
        floors = {k: {"precision": t["precision"], "recall": t["recall"]} for k, t in report["checks"].items()}
        sys.stdout.write(json.dumps({"checks": floors}, indent=1) + "\n")
        return 0
    sys.stdout.write(json.dumps(report, indent=1) + "\n" if "--json" in args else to_markdown(report) if "--md" in args else to_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
