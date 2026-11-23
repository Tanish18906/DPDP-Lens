#!/usr/bin/env bash
# Stop what scripts/demo_up.sh started (engine, dashboard, Slack bot). Safe to run twice.
set -uo pipefail
RUN=/tmp/dpdp-lens-demo.run
[ -f "$RUN" ] || { echo "Nothing to stop ($RUN does not exist)."; exit 0; }
while read -r pid name; do
  [[ "$pid" =~ ^[0-9]+$ ]] || continue
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null   # setsid made each one its own process group
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -0 "$pid" 2>/dev/null && kill -KILL -- "-$pid" 2>/dev/null
    echo "stopped $name"
  else
    echo "$name was not running"
  fi
done <"$RUN"
grep '^LOGS=' "$RUN" | head -1 | sed 's/^LOGS=/Logs were in /'
rm -f "$RUN"
