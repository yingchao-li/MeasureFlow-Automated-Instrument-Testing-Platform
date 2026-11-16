#!/usr/bin/env bash
# Install everything needed to build and test MeasureFlow locally (no sudo, no global changes).
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$MF_ROOT"

say "Checking prerequisites"
need cmake "install CMake >= 3.16 (brew install cmake / apt install cmake)"
need python3 "install Python >= 3.10"
need node "install Node.js >= 18"
need npm "install npm"
need curl "install curl"
if ! command -v c++ >/dev/null 2>&1 && ! command -v g++ >/dev/null 2>&1 && ! command -v clang++ >/dev/null 2>&1; then
  die "no C++17 compiler found (install Xcode command line tools or build-essential)"
fi
python3 - <<'PY' || die "Python >= 3.10 required"
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY

say "Creating Python virtual environment (.venv)"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r simulator/requirements.txt
if [ -f tests/requirements.txt ]; then
  .venv/bin/python -m pip install --quiet -r tests/requirements.txt
fi

say "Installing frontend dependencies"
(cd frontend && npm ci --no-audit --no-fund)

if [ -f tests/e2e/package.json ]; then
  say "Installing Playwright test dependencies"
  (cd tests/e2e && npm ci --no-audit --no-fund)
  if [ "${MF_SKIP_BROWSER_INSTALL:-0}" != "1" ]; then
    say "Installing Playwright Chromium (set MF_SKIP_BROWSER_INSTALL=1 to skip)"
    (cd tests/e2e && npx --no-install playwright install chromium) || warn "browser download failed; set PW_CHANNEL=chrome to use installed Chrome"
  fi
fi

say "Done. Next: scripts/build.sh && scripts/start.sh"
