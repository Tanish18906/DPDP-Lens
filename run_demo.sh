#!/usr/bin/env bash
# Start the whole DPDP Lens demo on localhost. Ctrl-C stops everything this script started.
# Ports: target backend 8000, target frontend 5173, engine API 8100, dashboard 5174.
set -uo pipefail
set -m  # one process group per background job, so Ctrl-C can kill npm's children too

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
LOGS="$(mktemp -d -t dpdp-lens-demo.XXXXXX)"
PIDS=()

[ -x "$PY" ] || { echo "No .venv found. Follow the README quick start first."; exit 1; }
for d in target-app/frontend dashboard; do
  [ -d "$ROOT/$d/node_modules" ] || { echo "Run 'npm install' in $d first."; exit 1; }
done

busy=""
for p in 8000 5173 8100 5174; do
  ss -ltn "sport = :$p" 2>/dev/null | grep -q LISTEN && busy="$busy $p"
done
[ -z "$busy" ] || { echo "Ports already in use:$busy. Stop those servers and run again."; exit 1; }

cleanup() {
  trap - INT TERM EXIT
  echo; echo "Stopping servers..."
  for pid in "${PIDS[@]}"; do kill -- "-$pid" 2>/dev/null; done
  wait 2>/dev/null
}
trap cleanup INT TERM EXIT

start() { # name port dir command...
  local name=$1 port=$2 dir=$3; shift 3
  (cd "$ROOT/$dir" && exec "$@") >"$LOGS/$name.log" 2>&1 &
  PIDS+=($!)
  for _ in $(seq 1 60); do
    (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null && { echo "  $name up on :$port"; return; }
    kill -0 "$!" 2>/dev/null || break
    sleep 0.5
  done
  echo "  $name FAILED. Log: $LOGS/$name.log"; exit 1
}

echo "Re-seeding synthetic demo.db (a live scan writes to it)..."
(cd "$ROOT/target-app/backend" && "$PY" seed.py >"$LOGS/seed.log" 2>&1) || { echo "seed.py failed. Log: $LOGS/seed.log"; exit 1; }

echo "Starting servers (logs in $LOGS)..."
start backend   8000 target-app/backend  "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
start frontend  5173 target-app/frontend npm run dev
start engine    8100 engine              "$PY" -m uvicorn dpdp_lens.api:app --host 127.0.0.1 --port 8100
start dashboard 5174 dashboard           npm run dev

echo
echo "Demo ready. Open the dashboard: http://localhost:5174"
echo "Target signup page: http://localhost:5173   Engine API: http://localhost:8100/health"
echo "Ctrl-C to stop."
while [ -n "$(jobs -rp)" ]; do
  wait -n
  echo "A server exited. The others keep running. Logs: $LOGS"
done
