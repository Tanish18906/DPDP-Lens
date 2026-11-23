#!/usr/bin/env bash
# Live demo step: add one new public route to the target app, then restart the backend on :8000.
# Undo with scripts/demo_revert.sh. Needs the demo stack from ./run_demo.sh to be running.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
MAIN="$ROOT/target-app/backend/app/main.py"
BAK=/tmp/main.py.demo.bak
LOG=/tmp/dpdp-lens-backend.log

# A second run would copy the already changed file over the real backup.
[ ! -e "$BAK" ] || { echo "$BAK exists: run scripts/demo_revert.sh first."; exit 1; }
grep -q '"/api/export"' "$MAIN" && { echo "main.py already has /api/export. Nothing to do."; exit 1; }

cp -p "$MAIN" "$BAK"
[ -z "$(tail -c1 "$MAIN")" ] || echo >> "$MAIN"  # file must end with a newline before we append
cat >> "$MAIN" <<'EOF'

# DEMO MUTATION: added by scripts/demo_mutate.sh, removed by scripts/demo_revert.sh
@app.get("/api/export")
def export_students():
    return db.all_students()
EOF
echo "Added GET /api/export to app/main.py (backup: $BAK)"

pid=$(ss -ltnp "sport = :8000" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2 || true)
if [ -n "$pid" ]; then
  ps -o args= -p "$pid" | grep -q "uvicorn app.main:app" || { echo "Port 8000 is used by something else (pid $pid). Not touching it."; exit 1; }
  kill "$pid"
  for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
  ! kill -0 "$pid" 2>/dev/null || { echo "Backend pid $pid did not stop."; exit 1; }
fi
(cd "$ROOT/target-app/backend" && setsid nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >"$LOG" 2>&1 &)
for _ in $(seq 1 60); do
  curl -fs -m 1 http://127.0.0.1:8000/health >/dev/null && { echo "Backend up on :8000 with /api/export"; exit 0; }
  sleep 0.5
done
echo "Backend did not answer /health. Log: $LOG. Run scripts/demo_revert.sh."
exit 1
