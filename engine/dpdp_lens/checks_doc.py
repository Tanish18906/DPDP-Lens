"""The list of checks and the rules we wrote, as one generated document (docs/15 S7, CS-01 deliverable).
`python -m dpdp_lens checks [--md|--json]` prints it. docs/CHECKS.md is the --md output, and a test keeps it current."""
import json

from .checks import CHECKS
from .models import SEVERITY_WEIGHTS
from .runner import CLAUSES
from .scanners import config_scan

RECOGNIZERS = [
    ("Aadhaar", "12 digits starting 2 to 9, Verhoeff checksum valid, and the column name or a nearby word says aadhaar, aadhar or uid"),
    ("PAN", "5 letters (4th is one of P C H F A T B L J G), 4 digits, 1 letter, not 0000"),
    ("Indian mobile", "10 digits starting 6 to 9 (optionally written 5 + 5), optional +91 or 0, not inside a longer digit run and not a decimal, and the column name or a nearby word says phone, mobile or contact. A nearby word does not count when build, version, release, order, invoice, ticket, tracking, serial, batch, sku, ref, reference or id stands just before the number"),
    ("Email", "local part, @, domain with a dot"),
    ("Date of birth", "YYYY-MM-DD in 19xx or 20xx, and the column name or a nearby word says dob or birth"),
    ("Name", "a column or JSON key that is `name` or ends in `_name` (not `username`)"),
    ("Column name context", "the column name is checked first, the value second, so a column called aadhaar or pan is a hint even before the value is read"),
    ("Masking", "Aadhaar XXXX XXXX 1234, PAN XXXXX1234X, phone 98XXXXXX10, email a***@x.com, date of birth year only. Raw values never leave the recognizer module"),
]

SECRET_RULES = [
    f"A key matches `{config_scan.KEY}` and its value is a literal of 4 or more characters.",
    "Not a literal: `${...}`, `$VAR`, `<...>`, `your-...`, `xxx`, `null`, `none`, `changeme`, `replace-me`, `example`, `sample`, `dummy`, `placeholder`, `todo`, `redacted` or an empty value.",
    "A value with a vendor token shape counts whatever the key is called: AWS access key id (`AKIA...`), GitHub (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`), Slack (`xox...-`), Stripe secret (`sk_live_`, `rk_live_`). JavaScript, TypeScript and shell files are read for these shapes only.",
    "A URL with `user:password@host` counts, with the password as the secret.",
    "`.env.example`, `.env.sample` and `.env.template` are never flagged.",
    "Python is read with `ast` (assignments of a string literal to a secret-like name), other config files line by line.",
    "Test folders, `test_*.py` and `conftest.py` are skipped. JavaScript and TypeScript source is not scanned for secrets by key name.",
    "A secret is shown as its first 2 characters plus `***`, never in full. One finding per file.",
]

CONFIG_RULES = [
    "Dockerfile: `COPY` or `ADD` of a `.env` file, or `ENV` or `ARG` with a secret literal (`config_env_in_image`).",
    "Dockerfile: no `USER`, or the last `USER` is root or 0 (`config_container_root`).",
    "CORS: `allow_origins` holds `\"*\"` in Python, or an `Access-Control-Allow-Origin: *` header in a config file. Credentials make it worse (`config_cors_wildcard`).",
    "Debug: `DEBUG` true in an env or config file, `debug=True` or `DEBUG = True` in Python, `--reload` or `--debug` in a container command (`config_debug_enabled`).",
    "Compose: a database image or a database port (5432, 3306, 27017, 6379, 1433) published without a 127.0.0.1 binding. A common default password is added to the reason (`config_db_exposed`).",
]

STATIC_RULES = [
    "Logs: Python `logging` and `print` calls through `ast`. JavaScript and TypeScript (`.js .jsx .ts .tsx .mjs .cjs`) `console.*` and `logger.*` calls through a small tokenizer that ignores comments and the text of strings (template `${...}` code is read). A name is personal data when one of its words (split on `_` and camelCase) is email, phone, aadhaar, pan, dob, password or token, unless its last word is count, total, sent, length, size, id, ids, type or status. JavaScript test files are skipped. Regex literals are not recognised (`log_pii`).",
    "Front end: `name=` or `id=` of input, select and textarea in `.html`, `.jsx`, `.tsx`, `.js` feed the notice drift block as `frontend:<file>:<line>`.",
    "Front end: `localStorage.setItem` or `sessionStorage.setItem` whose key or value names personal data (`fe_pii_in_storage`). JavaScript and TypeScript files are read without their comments, so a commented-out call is not a finding.",
    "Consent: a consent table, column or model field counts as a record. Comments, strings, the front end and tests do not (`consent_not_recorded`).",
    "Consent: a route in the OpenAPI spec that mentions consent, withdraw, revoke, opt out or unsubscribe (`consent_no_withdrawal`).",
    "Locations: routes through an `ast` walk of decorators, columns through `CREATE TABLE` or model classes, text through a file search. All paths are relative to the app folder.",
]

LIMITS = [
    "These checks are a subset of the DPDP duties. A clean scan is never a compliance result.",
    "Findings say an app likely does not meet a safeguard. They are readiness findings, not legal advice.",
    "A static scan cannot see consent kept in a service or database outside the scanned source.",
]


def _clauses():
    return json.loads(CLAUSES.read_text())


def as_dicts() -> list[dict]:
    clauses = _clauses()
    return [{"id": c.id, "layer": c.layer, "severity": c.severity, "title": c.title,
             "clauses": [x["ref"] for x in clauses[c.id]], "detection": c.detection,
             "recommendation": c.recommendation, "verified_fix": c.fixable, "proof": c.proof} for c in CHECKS.values()]


def to_json() -> str:
    return json.dumps({"checks": as_dicts(), "weights": SEVERITY_WEIGHTS, "recognizers": dict(RECOGNIZERS),
                       "secret_rules": SECRET_RULES, "config_rules": CONFIG_RULES, "static_rules": STATIC_RULES,
                       "limits": LIMITS}, indent=2) + "\n"


def to_markdown() -> str:
    w = ", ".join(f"{k} {v}" for k, v in SEVERITY_WEIGHTS.items())
    rows = "\n".join(
        f"| `{d['id']}` | {d['layer']} | {d['severity']} | {', '.join(d['clauses'])} | {d['detection']} | {d['recommendation']} | "
        f"{d['proof']} | {'yes' if d['verified_fix'] else 'no'} |" for d in as_dicts())
    lines = lambda items: "\n".join(f"- {i}" for i in items)  # noqa: E731
    return f"""# Checks and rules

Generated by `python -m dpdp_lens checks --md`. Do not edit by hand: a test fails when this file is out of date.
Clauses come from `contract/clauses.json`, checked against the DPDP Act 2023 and the DPDP Rules 2025.

Score = 100 minus open finding weights ({w}), floor 0.

## Checks ({len(CHECKS)})

Proof: `probed` is behaviour confirmed by a live request, `observed` is seen in live data, `static` is read from files.

| Check id | Layer | Severity | Clauses | What it detects | Recommended fix | Proof | Verified fix |
|----------|-------|----------|---------|-----------------|-----------------|-------|--------------|
{rows}

## Rules we wrote

### Personal data recognizers
{lines(f"**{k}**: {v}" for k, v in RECOGNIZERS)}

### Secret rule
{lines(SECRET_RULES)}

### Config rules
{lines(CONFIG_RULES)}

### Front end, consent and location rules
{lines(STATIC_RULES)}

## Limits
{lines(LIMITS)}
"""
