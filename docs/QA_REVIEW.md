# QA review

Scope: what was tested, how, what was found, what is still open. Everything here was measured on the final tree against
the **simulated** instruments; nothing was validated on real hardware.

## 1. Test inventory

| Suite | Location | Result (final tree) | What it exercises |
|---|---|---|---|
| C++ unit tests (Catch2) | `backend/tests` | 48 cases / 870 assertions pass; same result under ASan + UBSan | util, TCP/SCPI client (framing, timeouts, retry, reconnect, error queue) against a fake instrument, sequence parsing/validation |
| Simulator tests | `simulator/tests` | 310 pass, 1 skipped (`::1` is not bindable in the sandbox) | SCPI grammar, DSP, DUT chain, fault injection, analytic truth |
| API + integration + regression | `tests/api`, `tests/integration`, `tests/regression` | 621 pass, 8 `xfail(strict)` (see §3) | real backend binary + real simulator over TCP: REST contract, run engine, persistence, reports (CSV/HTML/PDF), error mapping, cancellation, restart, regression baseline |
| Frontend unit tests (Vitest) | `frontend/src/**/*.test.*` | 192 pass (14 files) | components, formatting, scales, SCPI console, filters |
| Browser E2E (Playwright) | `tests/e2e` | 16 pass | the four pages against a private real stack, offline banner, backend restart, simulator loss, console-error watchdog |
| Experiments E01-E10 | `experiments` | 10/10 completed, 0 harness defects | see `docs/EXPERIMENT_REPORT.md` |

Static checks run on the final tree: `tsc --noEmit`, ESLint (frontend), C++ built with `-Wall -Wextra -Wpedantic -Wshadow -Wconversion
-Wold-style-cast -Werror`, `vulture` (Python dead code) and `knip` (TypeScript dead exports), `jscpd` duplicate detection
(0 clones of >= 12 lines / 90 tokens across `frontend/src`, `backend/src`, `simulator/mfsim`, `experiments`, `tests`).

## 2. Coverage (measured, not estimated)

| Component | Line coverage | How measured |
|---|---|---|
| C++ backend (`backend/src`, 5072 lines) | **90.7 %** lines, 94.2 % functions, 66.9 % branches (throw branches excluded) | `MF_COVERAGE=1 scripts/build.sh`, Catch2 tests + the 629 pytest tests run against the instrumented binary, merged with `gcovr`. The Catch2 tests alone reach only 23.7 %: most of the engine, API and report code is exercised through the real server |
| Python simulator (`mfsim`, 1070 statements) | **99 %** | `pytest --cov=mfsim` |
| Frontend (`frontend/src`, Vitest only) | **55.6 %** lines, 53.7 % statements, 45.0 % branches | `vitest --coverage` (v8). **Below the 85 % target.** The page-level components (Instruments, Sequences, Reports, app shell) have no unit tests and are covered only by the Playwright E2E tests, whose coverage was not measured |

No coverage was padded: the simulator tests were checked for assertion-free test functions (none), there are no
`# pragma: no cover` or omit rules, and no test exists only to touch lines.

## 3. Findings

### Open (documented, not fixed - requirements were frozen)

| ID | Severity | Finding | Where | Test |
|---|---|---|---|---|
| QA-001 | low | `POST /api/instruments/connect` checks the loopback rule on the *trimmed* `host`, then stores/uses the raw string, so `"127.0.0.1\n"`, `" 127.0.0.1"` and `"\t127.0.0.1"` are accepted. A non-loopback host is still refused (the check runs on the trimmed value), so this is an input-hygiene defect, not a bypass. | `routes_instruments.cpp` (`require_loopback`, line 68) | `test_malformed_host_values_are_rejected_not_connected` (strict xfail) |
| QA-003 | low | `POST /api/instruments/command` trims the command before validating, so a trailing `\n` / `\r` is accepted although INTERFACE.md says "no newline". The trimmed command is what is sent; an embedded newline in the middle is rejected. | `routes_instruments.cpp` line 128 (`command = trim(command)`) | `test_command_validation` (strict xfail) |
| QA-004 | low | `GET /api/measurements/live?points=` / `?bins=` (empty value) is treated as "absent" and the default is used instead of answering 400. | `query_int` in `validation.cpp` | `test_live_parameter_bounds` (strict xfail) |
| QA-005 | info | Non-JSON `Content-Type` on POST endpoints is either accepted or rejected with 400/415 depending on the body; the contract does not require 415. Tests accept both but require a unified error body and no side effect on rejection. | API layer | `test_non_json_content_type_*` |

The xfails are `strict`: if one of these is fixed the test starts to pass, which fails the run until the marker is removed.
ID QA-002 is not used.

### Found during integration and resolved

| # | Finding | Resolution |
|---|---|---|
| 1 | REST calls took ~44 ms each (E01). Cause: the HTTP server wrote headers and body separately and Nagle + delayed ACK interacted. | `set_tcp_nodelay(true)` in `api_server.cpp`; REST p50 is now 0.7 ms. All reported experiment data come from the fixed binary. |
| 2 | `GET /api/logs` with more matching entries than `limit` returns the **newest** `limit` entries; the test and the contract text had assumed the oldest. | Behaviour kept (it is what a log viewer wants); INTERFACE.md section 5.15 and the test corrected. |
| 3 | The HTML report test asserted that a hostile test label produced no `<h1>` at all, but the report has its own title `<h1>`. | Test now asserts no injected `<img>` and exactly one `<h1>`. |
| 4 | A cross-site `multipart/form-data` POST answered 400 instead of 403. | Test accepts 400 or 403 for multipart (still refused, no side effect); other simple content types must be 403. |
| 5 | 27 regression tests were skipped because `tests/regression/baseline.json` did not exist; the first baseline audit showed the SNR / noise-floor tolerance (0.3 dB) was below 4 sigma of the seed-to-seed spread. | Baseline generated from a real run (`update_baseline.py`), tolerances widened to 0.7 dB (SNR) and 0.6 dB (noise floor) with the reasoning in the module docstring. |
| 6 | E08 executed 429 of 500 cases; 22 runs ended ERROR with zero tasks and were silently dropped from classification (so "unexpected errors = 0" was misleading). Cause: a *persistent* injected timeout fault left its counter in the simulator, so the next run's `*IDN?` timed out. The backend behaved correctly (`COMM_TIMEOUT` in `init`). | Harness bug, not a product defect. The experiment now clears simulator state after every fault run and counts any run-level ERROR without an injected fault as an unexpected software error. Re-run: 500/500 executed, 0 unexpected errors. |
| 7 | E03 value-error statistics included CLIPPING SNR / noise-floor points that have no analytic truth. | Excluded from the error statistics (they were already excluded from the verdicts). |
| 8 | `test_many_consecutive_runs_do_not_leak_fds_threads_or_memory` fails under ASan (RSS 219 -> 435 MB). | Not a leak: ASan's quarantine and shadow memory make RSS meaningless as a leak signal. The test passes on the Release and coverage builds; fd and thread counts are checked separately and pass under ASan too. Run the other 620 tests under ASan with `--deselect` of that test. |

### Limitations of the product that the experiments exposed

* **THD under noise.** The analyzer's THD estimator sums the power in the H2-H10 bins, so output noise that falls into those bins is counted as
  distortion. On the NOISY profile at 0.01 Vpk the mean THD error is +0.32 %-points against the noise-free analytic truth; at 0.05 and 0.1 Vpk it
  is 0.004 and 0.002 %-points (E02). This is a property of the estimator (documented in `EXPERIMENT_REPORT.md`), not a numerical bug.
* **Memory growth.** Backend RSS grows over a few hundred runs (E08: 6.3 -> 24 MB after 161 runs). The cause was not investigated and no soak test
  was run; file descriptors and threads stay constant.

## 4. What was not done

* The GitHub Actions workflow (`.github/workflows/ci.yml`) parses as valid YAML but **has never been executed**; the first push may need adjustments.
* No test on real instruments (VISA / GPIB / USB), no timing validation against real hardware, no IEC / ANSI hearing-aid standard conformance,
  no medical-device certification of any kind.
* No security audit. The backend binds to loopback only (`--unsafe-bind` overrides this) and rejects non-loopback instrument hosts, but it has no authentication.
* No long-duration soak test, no load test beyond the 500-case batch, no cross-platform run by the author (everything ran on one Linux x86-64 machine). The first build on a macOS machine (Clang, `-Werror`) failed on an unused lambda capture that GCC does not report. Fixed in `routes_instruments.cpp`; `-Werror` is now opt-in (`MF_WERROR=1`, used by CI). While fixing it, `SOCK_CLOEXEC` and `MSG_NOSIGNAL` (not defined on macOS) and floating-point `std::from_chars` (missing in older libc++) were made portable. Verified with GCC 13 and Clang 18 (`-Werror`) on Linux, and with the strtod fallback forced (`-DMF_FORCE_STRTOD`): Catch2 and 629 pytest tests pass. Not compiled with Apple clang. A second user-reported problem on macOS: `scripts/start.sh` gave up after 5 s waiting for the simulator, whose first start (cold Python/numpy/scipy imports) took longer; the wait is now up to 60 s (backend 30 s), a leftover simulator from a failed start is stopped, and a failed start cleans up after itself.
* No accessibility audit beyond semantic roles and labels used by the Playwright selectors.
