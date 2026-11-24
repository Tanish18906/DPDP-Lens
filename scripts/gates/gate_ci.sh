#!/usr/bin/env bash
# CI gate: `ci` against target-app with a baseline of every current finding passes (exit 0), and the same app with one added
# logger.info("x %s", req.aadhaar) line fails (exit 1) with exactly one new finding. Static scan, so no ports and no running app.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "No .venv found. Follow the README quick start first."; exit 2; }
TMP="$(mktemp -d -t dpdp-gate-ci.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
cd "$ROOT/engine" || exit 2
ci() { "$PY" -m dpdp_lens ci "$@"; }
fails=0
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; else echo "FAIL $1  [got $2, want $3]"; fails=$((fails + 1)); fi; }

ci --repo-dir "$ROOT/target-app" --write-baseline --baseline "$TMP/base.json" >/dev/null
check "baseline written" "$?" 0
ci --repo-dir "$ROOT/target-app" --new-only --baseline "$TMP/base.json" >/dev/null
check "all findings in the baseline: exit 0" "$?" 0

COPY="$TMP/app"
mkdir "$COPY" && tar -C "$ROOT/target-app" --exclude=node_modules --exclude=__pycache__ --exclude='*.db' --exclude='*.log' -cf - . | tar -C "$COPY" -xf -
printf '\nlogger.info("x %%s", req.aadhaar)\n' >> "$COPY/backend/app/main.py"
ci --repo-dir "$COPY" --new-only --baseline "$TMP/base.json" --json "$TMP/new.json" >/dev/null
check "one added log line: exit 1" "$?" 1
NEW="$("$PY" -c "import json,sys; ev=json.load(open(sys.argv[1]))['evaluation']; print(sum(i['is_new'] for i in ev['items']))" "$TMP/new.json")"
check "exactly one new finding" "$NEW" 1

echo "gate_ci: $((4 - fails))/4 passed"
[ "$fails" -eq 0 ]
