#!/usr/bin/env bash
# Start the virtual instruments and the C++ backend (which also serves the built frontend).
# Everything binds to 127.0.0.1 only. Stop with scripts/stop.sh.
#   MF_PORT=8080  MF_SIM_BASE_PORT=5025  MF_SEED=12345  MF_BUILD_DIR=backend/build
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$MF_ROOT"
mkdir -p "$MF_RUN_DIR" "$MF_LOG_DIR"

BACKEND="$MF_BUILD_DIR/measureflow_backend"
[ -x "$BACKEND" ] || die "backend binary not found ($BACKEND) — run scripts/build.sh first"

if [ -f "$MF_RUN_DIR/backend.pid" ] && pid_alive "$(cat "$MF_RUN_DIR/backend.pid")"; then
  die "already running (pid $(cat "$MF_RUN_DIR/backend.pid")); run scripts/stop.sh first"
fi

# A simulator left over from an earlier failed start would hold the ports: stop it first.
if [ -f "$MF_RUN_DIR/simulator.pid" ] && pid_alive "$(cat "$MF_RUN_DIR/simulator.pid")"; then
  warn "stopping a leftover simulator from an earlier start"
  "$MF_ROOT/scripts/stop.sh" >/dev/null || true
fi
# Give up (and stop what was started) with a message.
abort_start() { "$MF_ROOT/scripts/stop.sh" >/dev/null 2>&1 || true; die "$1"; }

say "Starting virtual instruments (ports $MF_SIM_BASE_PORT-$((MF_SIM_BASE_PORT + 2)), seed $MF_SEED)"
(
  cd "$MF_ROOT/simulator"
  nohup "$(pybin)" \
    -m mfsim --host 127.0.0.1 --base-port "$MF_SIM_BASE_PORT" --seed "$MF_SEED" \
    >"$MF_LOG_DIR/simulator.out" 2>&1 &
  echo $! >"$MF_RUN_DIR/simulator.pid"
)
# The first start can be slow (cold Python/numpy/scipy imports): wait up to 60 s.
for _ in $(seq 1 300); do
  grep -q '^READY' "$MF_LOG_DIR/simulator.out" 2>/dev/null && break
  pid_alive "$(cat "$MF_RUN_DIR/simulator.pid")" || { cat "$MF_LOG_DIR/simulator.out" >&2; abort_start "simulator exited early"; }
  sleep 0.2
done
grep -q '^READY' "$MF_LOG_DIR/simulator.out" || abort_start "simulator did not become ready within 60 s (see results/logs/simulator.out)"

say "Starting backend on http://127.0.0.1:$MF_PORT"
nohup "$BACKEND" --root "$MF_ROOT" --host 127.0.0.1 --port "$MF_PORT" >"$MF_LOG_DIR/backend.out" 2>&1 &
echo $! >"$MF_RUN_DIR/backend.pid"
for _ in $(seq 1 150); do
  http_ok "http://127.0.0.1:$MF_PORT/api/health" && break
  pid_alive "$(cat "$MF_RUN_DIR/backend.pid")" || { cat "$MF_LOG_DIR/backend.out" >&2; abort_start "backend exited early"; }
  sleep 0.2
done
http_ok "http://127.0.0.1:$MF_PORT/api/health" || abort_start "backend did not answer /api/health within 30 s (see results/logs/backend.out)"

say "MeasureFlow is running:  http://127.0.0.1:$MF_PORT   (logs: results/logs/)"
[ -f frontend/dist/index.html ] || warn "frontend/dist missing — run scripts/build.sh to enable the UI (API works)"
