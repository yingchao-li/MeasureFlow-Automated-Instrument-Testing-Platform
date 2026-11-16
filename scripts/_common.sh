#!/usr/bin/env bash
# Shared helpers for MeasureFlow scripts (bash 3.2 compatible: works on macOS and Linux).
set -euo pipefail

MF_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MF_RUN_DIR="$MF_ROOT/.run"
MF_LOG_DIR="$MF_ROOT/results/logs"
MF_PORT="${MF_PORT:-8080}"
MF_SIM_BASE_PORT="${MF_SIM_BASE_PORT:-5025}"
MF_SEED="${MF_SEED:-12345}"
MF_BUILD_DIR="${MF_BUILD_DIR:-$MF_ROOT/backend/build}"

jobs_count() {
  getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 2
}

# Prefer the project virtualenv (created by install.sh), fall back to system python3.
pybin() {
  if [ -x "$MF_ROOT/.venv/bin/python" ]; then
    echo "$MF_ROOT/.venv/bin/python"
  else
    command -v python3
  fi
}
py() { "$(pybin)" "$@"; }

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing prerequisite: $1 ($2)"
}

pid_alive() {
  [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null
}

http_ok() {
  curl -fsS -m 2 "$1" >/dev/null 2>&1
}
