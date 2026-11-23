#!/usr/bin/env bash
# Undo scripts/demo_mutate.sh: restore app/main.py from the backup and restart the backend on :8000.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
MAIN="$ROOT/target-app/backend/app/main.py"
BAK=/tmp/main.py.demo.bak
LOG=/tmp/dpdp-lens-backend.log

[ -e "$BAK" ] || { echo "No backup at $BAK. Nothing to restore (main.py was not changed by demo_mutate.sh)."; exit 1; }
cp -p "$BAK" "$MAIN"
rm -f "$BAK"
echo "Restored app/main.py"

pid=$(ss -ltnp "sport = :8000" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2 || true)
if [ -n "$pid" ]; then
  ps -o args= -p "$pid" | grep -q "uvicorn app.main:app" || { echo "Port 8000 is used by something else (pid $pid). Not touching it."; exit 1; }
  kill "$pid"
  for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
  ! kill -0 "$pid" 2>/dev/null || { echo "Backend pid $pid did not stop."; exit 1; }
fi
(cd "$ROOT/target-app/backend" && setsid nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >"$LOG" 2>&1 &)
for _ in $(seq 1 60); do
  curl -fs -m 1 http://127.0.0.1:8000/health >/dev/null && { echo "Backend up on :8000 (original code)"; exit 0; }
  sleep 0.5
done
echo "Backend did not answer /health. Log: $LOG"
exit 1
