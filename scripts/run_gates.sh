#!/usr/bin/env bash
# Run every Playwright gate against the demo stack and print PASS or FAIL per gate. Exit code 1 if any gate fails.
# All 4 ports free: it starts ./run_demo.sh and stops it at the end. All 4 up: it reuses them. A mix: it stops.
# Screenshots go to docs/fallback-shots (override with SHOT_DIR). demo.db is re-seeded at the end.
set -uo pipefail
set -m  # own process group for the demo stack, so it can be stopped cleanly

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
GATES=(rehearsal all_fixes children data_flow offline fix_states)
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
  LOG="$(mktemp -d -t dpdp-lens-gates.XXXXXX)/demo.log"
  echo "Starting the demo stack (log: $LOG)..."
  export DPDP_STATE_DIR="$(mktemp -d -t dpdp-lens-state.XXXXXX)"  # gate scans must not pile up in the repo
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

FAILED=()
for g in "${GATES[@]}"; do
  out="$("$PY" "$ROOT/scripts/gates/gate_$g.py" 2>&1)"
  if [ $? -eq 0 ]; then
    echo "PASS  $g  ($(echo "$out" | tail -1))"
  else
    echo "FAIL  $g"
    echo "$out" | sed 's/^/      /'
    FAILED+=("$g")
  fi
done

stop_stack
echo "Re-seeding demo.db..."
(cd "$ROOT/target-app/backend" && "$PY" seed.py >/dev/null 2>&1) || { echo "seed.py failed"; FAILED+=("seed"); }

if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "ALL GATES PASSED. Screenshots: ${SHOT_DIR:-docs/fallback-shots}"
else
  echo "FAILED: ${FAILED[*]}"
  exit 1
fi
