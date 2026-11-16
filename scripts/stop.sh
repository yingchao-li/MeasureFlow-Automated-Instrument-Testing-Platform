#!/usr/bin/env bash
# Stop backend and simulator started by scripts/start.sh (SIGTERM, then SIGKILL after 5 s).
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$MF_ROOT"
stopped=0
for name in backend simulator; do
  f="$MF_RUN_DIR/$name.pid"
  [ -f "$f" ] || continue
  pid="$(cat "$f")"
  if pid_alive "$pid"; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do pid_alive "$pid" || break; sleep 0.1; done
    if pid_alive "$pid"; then kill -9 "$pid" 2>/dev/null || true; fi
    say "stopped $name (pid $pid)"; stopped=1
  fi
  rm -f "$f"
done
[ "$stopped" = 1 ] || say "nothing was running"
