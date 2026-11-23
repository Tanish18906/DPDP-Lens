#!/usr/bin/env bash
# Scan TutorNest and write the sample deliverables to reports/ (override with OUT): tutornest-scan.json, tutornest-report.html,
# tutornest.sarif. All 4 demo ports free: it starts ./run_demo.sh and stops it at the end. All 4 up: it reuses them.
# It then greps the files for raw personal data and the planted secret values and fails if it finds any. demo.db is re-seeded at the end.
set -uo pipefail
set -m

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
OUT="${OUT:-$ROOT/reports}"
PORTS=(8000 5173 8100 5174)
DEMO_PID=""

[ -x "$PY" ] || { echo "No .venv found. Follow the README quick start first."; exit 2; }

listening() { ss -ltn "sport = :$1" 2>/dev/null | grep -q LISTEN; }
up=0
for p in "${PORTS[@]}"; do listening "$p" && up=$((up + 1)); done

stop_stack() {
  [ -n "$DEMO_PID" ] || return 0
  kill -TERM "$DEMO_PID" 2>/dev/null
  wait "$DEMO_PID" 2>/dev/null
  DEMO_PID=""
}
trap stop_stack EXIT INT TERM

if [ "$up" -eq 0 ]; then
  LOG="$(mktemp -d -t dpdp-lens-report.XXXXXX)/demo.log"
  echo "Starting the demo stack (log: $LOG)..."
  export DPDP_STATE_DIR="$(mktemp -d -t dpdp-lens-state.XXXXXX)"
  "$ROOT/run_demo.sh" >"$LOG" 2>&1 &
  DEMO_PID=$!
  for _ in $(seq 1 120); do
    grep -q "Demo ready" "$LOG" 2>/dev/null && break
    kill -0 "$DEMO_PID" 2>/dev/null || { echo "run_demo.sh exited early:"; cat "$LOG"; exit 2; }
    sleep 1
  done
  grep -q "Demo ready" "$LOG" || { echo "The demo stack did not become ready in 120 s. Log: $LOG"; exit 2; }
elif [ "$up" -ne 4 ]; then
  echo "Only $up of the ports ${PORTS[*]} are in use. Stop them all, or start all of them (./run_demo.sh), then run again."
  exit 2
fi

mkdir -p "$OUT"
STATUS=0
(cd "$ROOT/engine" && "$PY" -m dpdp_lens scan --target http://localhost:8000 --repo ../target-app/backend \
  --db ../target-app/backend/demo.db --out "$OUT/tutornest-scan.json" --sarif "$OUT/tutornest.sarif" \
  && "$PY" -m dpdp_lens report "$OUT/tutornest-scan.json" --out "$OUT/tutornest-report.html") || STATUS=1

stop_stack
echo "Re-seeding demo.db..."
(cd "$ROOT/target-app/backend" && "$PY" seed.py >/dev/null 2>&1) || { echo "seed.py failed"; STATUS=1; }

# Masked data only: no Aadhaar, PAN, 10 digit phone, and none of the planted secret values (docs/15 D7).
if grep -rEn '(^|[^0-9])[2-9][0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}([^0-9]|$)|[A-Z]{3}[PCHFATBLJG][A-Z][0-9]{4}[A-Z]|(^|[^0-9])[6-9][0-9]{9}([^0-9]|$)|tutornest-demo-secret-123|admin123|mail-demo-pass-456|hackathon-insecure|StudentPass123' \
    "$OUT/tutornest-scan.json" "$OUT/tutornest-report.html" "$OUT/tutornest.sarif" >/dev/null 2>&1; then
  echo "FAIL: raw personal data or a planted secret value is in $OUT"
  STATUS=1
fi
[ "$STATUS" -eq 0 ] && echo "Sample report written to $OUT (masked data only)." || echo "FAILED"
exit "$STATUS"
