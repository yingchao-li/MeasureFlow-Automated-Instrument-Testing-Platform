#!/usr/bin/env bash
# Run the automated test suites. Every suite that runs is reported; suites that cannot run are
# reported as SKIPPED with the reason — they are never silently counted as passed.
#   scripts/test.sh            unit + integration suites (C++, Python, frontend, API/integration)
#   scripts/test.sh --asan     additionally run the C++ tests under ASan+UBSan
#   scripts/test.sh --e2e      additionally run the Playwright end-to-end tests
#   scripts/test.sh --all      everything
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$MF_ROOT"
RUN_ASAN=0; RUN_E2E=0
for a in "$@"; do
  case "$a" in
    --asan) RUN_ASAN=1 ;;
    --e2e)  RUN_E2E=1 ;;
    --all)  RUN_ASAN=1; RUN_E2E=1 ;;
    *) die "unknown option $a" ;;
  esac
done

RESULTS=""
FAILED=0
record() { RESULTS="$RESULTS$1|$2
"; [ "$2" = "FAILED" ] && FAILED=1 || true; }
run_suite() {  # name, command...
  local name="$1"; shift
  say "$name"
  if "$@"; then record "$name" "passed"; else record "$name" "FAILED"; fi
}

if [ -x "$MF_BUILD_DIR/measureflow_tests" ]; then
  run_suite "C++ unit tests (Catch2)" "$MF_BUILD_DIR/measureflow_tests"
else
  record "C++ unit tests (Catch2)" "SKIPPED (not built: run scripts/build.sh)"
fi
if [ "$RUN_ASAN" = 1 ]; then
  MF_SANITIZE=1 "$MF_ROOT/scripts/build.sh" && run_suite "C++ unit tests (ASan+UBSan)" "$MF_ROOT/backend/build-asan/measureflow_tests" \
    || record "C++ unit tests (ASan+UBSan)" "FAILED"
fi
run_suite "Python simulator tests (pytest)" py -m pytest -q simulator/tests

if [ -d frontend/node_modules ]; then
  run_suite "Frontend component tests (Vitest)" bash -c 'cd frontend && npm test --silent'
else
  record "Frontend component tests (Vitest)" "SKIPPED (npm ci not run)"
fi

if [ -d tests/integration ] && ls tests/integration/test_*.py >/dev/null 2>&1; then
  if [ -x "$MF_BUILD_DIR/measureflow_backend" ]; then
    run_suite "Integration + API + regression tests (pytest)" py -m pytest -q tests/integration tests/api tests/regression
  else
    record "Integration + API + regression tests (pytest)" "SKIPPED (backend not built)"
  fi
fi

if [ "$RUN_E2E" = 1 ]; then
  if [ -f tests/e2e/package.json ]; then
    run_suite "Playwright E2E" bash -c 'cd tests/e2e && npx playwright test'
  else
    record "Playwright E2E" "SKIPPED (tests/e2e not present)"
  fi
fi

echo
echo "================ test summary ================"
printf '%s' "$RESULTS" | while IFS='|' read -r n s; do [ -n "$n" ] && printf '  %-48s %s\n' "$n" "$s"; done
echo "=============================================="
exit "$FAILED"
