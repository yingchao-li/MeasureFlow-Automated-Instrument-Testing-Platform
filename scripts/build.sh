#!/usr/bin/env bash
# Build the C++ backend (Release by default) and the production frontend bundle.
#   scripts/build.sh                 # Release backend + frontend
#   MF_SANITIZE=1 scripts/build.sh   # ASan+UBSan backend in backend/build-asan (frontend skipped)
#   MF_COVERAGE=1 scripts/build.sh   # gcov-instrumented backend in backend/build-cov
#   MF_SKIP_FRONTEND=1 ...           # backend only
#   MF_WERROR=1 scripts/build.sh     # treat compiler warnings as errors (as CI does)
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$MF_ROOT"
need cmake "install CMake >= 3.16"

BUILD_TYPE="Release"
BUILD_DIR="$MF_ROOT/backend/build"
# Warnings are errors only on request (MF_WERROR=1, used by CI): a different compiler version must not block a local build.
EXTRA="-DMF_WERROR=OFF"
if [ "${MF_WERROR:-0}" = "1" ]; then EXTRA="-DMF_WERROR=ON"; fi
if [ "${MF_SANITIZE:-0}" = "1" ]; then
  BUILD_TYPE="Debug"; BUILD_DIR="$MF_ROOT/backend/build-asan"; EXTRA="$EXTRA -DMF_SANITIZE=ON"; MF_SKIP_FRONTEND=1
elif [ "${MF_COVERAGE:-0}" = "1" ]; then
  BUILD_TYPE="Debug"; BUILD_DIR="$MF_ROOT/backend/build-cov"; EXTRA="$EXTRA -DMF_COVERAGE=ON"; MF_SKIP_FRONTEND=1
fi

say "Configuring backend ($BUILD_TYPE) in ${BUILD_DIR#$MF_ROOT/}"
# shellcheck disable=SC2086
cmake -S backend -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE="$BUILD_TYPE" $EXTRA >/dev/null
say "Compiling backend"
cmake --build "$BUILD_DIR" -j"$(jobs_count)"

if [ "${MF_SKIP_FRONTEND:-0}" != "1" ]; then
  say "Building frontend"
  [ -d frontend/node_modules ] || (cd frontend && npm ci --no-audit --no-fund)
  (cd frontend && npm run build)
fi
say "Build finished"
