#!/usr/bin/env bash
# Start the next demo clean: delete the findings database (repos, findings, audit log, outbox) and the saved scan files.
# It lists what it will delete and does nothing unless you type "yes". Stop the stack first (scripts/demo_down.sh).
# It never touches the target app's demo.db, the code, or scripts/demo_env.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVFILE="${DPDP_DEMO_ENV:-$ROOT/scripts/demo_env}"
[ ! -f "$ENVFILE" ] || { set -a; . "$ENVFILE"; set +a; }
STATE="${DPDP_STATE_DIR:-$ROOT/.dpdp-state}"
DB="${DPDP_DB:-$STATE/dpdp.db}"

if ss -ltn "sport = :8100" 2>/dev/null | grep -q LISTEN; then
  echo "Something is listening on :8100 (the engine?). Run scripts/demo_down.sh first."; exit 1
fi
files=()
for f in "$DB" "$DB-wal" "$DB-shm"; do [ -f "$f" ] && files+=("$f"); done
for f in "$STATE"/S-*.json "$STATE"/S-*.json.tmp; do [ -f "$f" ] && files+=("$f"); done
if [ ${#files[@]} -eq 0 ]; then echo "Nothing to delete (no database and no saved scans in $STATE)."; exit 0; fi
echo "This deletes ${#files[@]} files:"
printf '  %s\n' "${files[@]}"
printf 'Type "yes" to delete them: '
read -r answer
[ "$answer" = "yes" ] || { echo "Not deleted."; exit 1; }
rm -f -- "${files[@]}"
echo "Deleted. The next scripts/demo_up.sh starts with no repos and no findings."
