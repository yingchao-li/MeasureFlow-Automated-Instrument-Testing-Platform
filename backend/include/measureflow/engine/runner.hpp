// TestRunner: executes test sequences on a worker thread against leased instruments.
//
// State machine of a run: PENDING -> RUNNING -> PASS | FAIL | ERROR | CANCELLED
//   precedence at completion: CANCELLED (cancel observed before all steps completed) > ERROR (a task ERROR or an
//   aborted step) > FAIL (any task FAIL) > PASS. FAIL (valid finite measurement outside limits) and ERROR
//   (communication/software problem, non-finite or invalid measurement) are never conflated.
//
// Guarantees:
//   * only one run is active at a time (start() -> CONFLICT otherwise); all instruments are leased
//     exclusively for the duration of the run (API calls get INSTRUMENT_BUSY)
//   * cleanup is guaranteed: an RAII guard switches the generator output OFF and releases the lease on
//     completion, cancellation, error and exceptions
//   * cancellation is cooperative: checked between steps, inside SCPI waits (<= 25 ms granularity), settle
//     waits and retry back-offs
//
// Locking: TestRunner::mu_ protects the run records (active/last) and is held only for short critical
// sections, never during instrument I/O or file I/O. start_mu_ serialises start() calls and is taken
// before mu_. Order: start_mu_ > mu_ ; Registry/Client/Logger locks are only taken without mu_ held.
#pragma once

#include <atomic>
#include <condition_variable>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>

#include "measureflow/engine/result_store.hpp"
#include "measureflow/engine/sequence.hpp"
#include "measureflow/engine/types.hpp"
#include "measureflow/instruments/registry.hpp"
#include "measureflow/report/report_service.hpp"
#include "measureflow/util/logger.hpp"

namespace mf {

struct RunRequest {
  std::string sequence_id;
  std::map<std::string, double> parameters;
  std::optional<std::string> dut_profile;
  std::optional<std::string> dut_firmware;
  int retries = 1;
  std::string label;
};

struct RunnerOptions {
  int retry_backoff_ms = 100;  // base back-off between task-level attempts (x attempt number)
  int lease_wait_ms = 500;     // how long start() waits for transient API leases
};

class TestRunner {
 public:
  TestRunner(InstrumentRegistry& registry, const SequenceLibrary& sequences, ResultStore& store, ReportService& reports,
             Logger& logger, RunnerOptions options = {});
  ~TestRunner();
  TestRunner(const TestRunner&) = delete;
  TestRunner& operator=(const TestRunner&) = delete;

  // Validates the request, leases all instruments and starts the worker. Throws MfError:
  // INVALID_ARGUMENT / NOT_FOUND (sequence) / CONFLICT (a run is active) / INSTRUMENT_BUSY.
  RunRecord start(const RunRequest& request);
  // Requests cancellation; returns the run (status RUNNING, cancel_requested true).
  // NOT_FOUND if unknown, CONFLICT if the run already finished. Empty id = active run.
  RunRecord cancel(const std::string& run_id);
  // Active run, else (for an empty id) the most recent finished one; `log_tail` entries of the run log.
  std::optional<RunRecord> status(const std::string& run_id, size_t log_tail);
  std::optional<std::string> active_run_id() const;
  // Blocks until no run is active (true) or the timeout elapsed (false).
  bool wait_idle(int timeout_ms);
  // Cancels the active run (if any) and joins the worker.
  void shutdown();

 private:
  struct Ctx;
  friend class RunExecutor;
  RunRecord snapshot(const std::shared_ptr<Ctx>& ctx, size_t log_tail) const;
  void join_worker(const std::shared_ptr<Ctx>& ctx);

  InstrumentRegistry& registry_;
  const SequenceLibrary& sequences_;
  ResultStore& store_;
  ReportService& reports_;
  Logger& logger_;
  RunnerOptions options_;

  std::mutex start_mu_;
  mutable std::mutex mu_;
  std::condition_variable idle_cv_;
  std::shared_ptr<Ctx> active_;
  std::shared_ptr<Ctx> last_;
  bool shutting_down_ = false;
};

}  // namespace mf
