#!/usr/bin/env bash
# Start the Slack demo stack in the background: engine (:8100), dashboard (:5174) and the Slack bot.
# Reads scripts/demo_env (copy scripts/demo_env.example), runs the preflight before and after, prints the URLs.
# DPDP_PREFLIGHT_ARGS=--offline skips the GitHub and Slack checks (a rehearsal without network). Stop with scripts/demo_down.sh. Logs: the folder printed below (it never holds a token: the bot and engine redact them).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
ENVFILE="${DPDP_DEMO_ENV:-$ROOT/scripts/demo_env}"
RUN=/tmp/dpdp-lens-demo.run   # one line per process: "<pid> <name>", plus "LOGS=<folder>"

[ -x "$PY" ] || { echo "No .venv found. Follow the README quick start first."; exit 2; }
[ -f "$ENVFILE" ] || { echo "No $ENVFILE. Copy scripts/demo_env.example to scripts/demo_env and fill it in."; exit 2; }
[ -d "$ROOT/dashboard/node_modules" ] || { echo "Run 'npm install' in dashboard first."; exit 2; }
if [ -f "$RUN" ]; then
  alive=0
  while read -r pid _; do [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null && alive=1; done <"$RUN"
  [ "$alive" -eq 0 ] || { echo "A demo is already running (see $RUN). Run scripts/demo_down.sh first."; exit 1; }
  rm -f "$RUN"  # left over from a run that is gone
fi

set -a; . "$ENVFILE"; set +a                       # exported to the engine, the dashboard (VITE_*) and the bot, never printed
[ -n "${DPDP_MONITOR:-}" ] || unset DPDP_MONITOR   # an empty value would read as "not 0": same as unset, but keep it clean
[ -n "${DPDP_DB:-}" ] || unset DPDP_DB

echo "1/3 Preflight (before start)"
"$PY" "$ROOT/scripts/preflight.py" --stage env ${DPDP_PREFLIGHT_ARGS:-} || { echo; echo "Fix the FAIL lines above, then run scripts/demo_up.sh again."; exit 1; }

busy=""
for p in 8100 5174; do ss -ltn "sport = :$p" 2>/dev/null | grep -q LISTEN && busy="$busy $p"; done
[ -z "$busy" ] || { echo "Ports already in use:$busy. Stop those servers (scripts/demo_down.sh, or ./run_demo.sh's Ctrl-C) and run again."; exit 1; }

LOGS="$(mktemp -d -t dpdp-lens-demo.XXXXXX)"
echo "LOGS=$LOGS" >"$RUN"
launch() { # name dir command...
  local name=$1 dir=$2; shift 2
  (cd "$ROOT/$dir" && exec setsid "$@") >"$LOGS/$name.log" 2>&1 &
  echo "$! $name" >>"$RUN"
}
echo "2/3 Starting (logs in $LOGS)"
launch engine engine "$PY" -m uvicorn dpdp_lens.api:app --host 127.0.0.1 --port 8100
launch dashboard dashboard npm run dev
launch slackbot engine "$PY" -m dpdp_lens.slackbot

for _ in $(seq 1 60); do
  curl -fs -m 1 "${ENGINE_URL:-http://127.0.0.1:8100}/health" >/dev/null && curl -fs -m 1 -o /dev/null "${DASHBOARD_URL:-http://localhost:5174}" && break
  sleep 0.5
done
sleep 3  # the bot needs a moment: if it died on a bad token, it is gone by now
dead=0
while read -r pid name; do
  [[ "$pid" =~ ^[0-9]+$ ]] || continue
  kill -0 "$pid" 2>/dev/null || { echo "  $name is NOT running. Read $LOGS/$name.log"; dead=1; }
done <"$RUN"

echo "3/3 Preflight (running stack)"
"$PY" "$ROOT/scripts/preflight.py" --stage services; rc=$?
echo
echo "Dashboard:  ${DASHBOARD_URL:-http://localhost:5174}"
echo "Engine:     ${ENGINE_URL:-http://127.0.0.1:8100}/health"
echo "Slack bot:  log $LOGS/slackbot.log (watch it while you type /dpdp in Slack)"
echo "Stop:       scripts/demo_down.sh      Fresh start: scripts/demo_down.sh && scripts/demo_reset.sh && scripts/demo_up.sh"
[ "$dead" -eq 0 ] || { echo; echo "A process died (see above): the demo is NOT ready."; exit 1; }
exit $rc
