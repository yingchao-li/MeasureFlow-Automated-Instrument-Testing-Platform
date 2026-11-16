// Aggregated statistics over persisted history (GET /api/reports/summary).
#pragma once

#include <map>
#include <string>
#include <vector>

#include "measureflow/engine/types.hpp"

namespace mf {

struct ValueStats {
  int count = 0;      // tasks with a verdict (PASS/FAIL/ERROR) of this kind
  int pass = 0, fail = 0, error = 0;
  int n_values = 0;   // tasks with a measured value
  double mean = 0, std = 0, min = 0, max = 0;  // meaningful only when n_values > 0 (sample std, n-1)
  std::string unit;
};

struct FirmwareStats {
  std::string firmware;
  int tasks = 0, pass = 0, fail = 0, error = 0;
  double pass_rate = 0;
  std::map<std::string, ValueStats> by_kind;
};

struct TrendPoint {
  std::string timestamp, run_id, kind, unit, status, firmware;
  double value = 0;
};

struct SummaryReport {
  std::string generated_at;
  int runs_total = 0, runs_pass = 0, runs_fail = 0, runs_error = 0, runs_cancelled = 0;
  int tasks_total = 0, tasks_pass = 0, tasks_fail = 0, tasks_error = 0, tasks_cancelled = 0;
  double pass_rate = 0;  // PASS / (PASS+FAIL+ERROR); CANCELLED tasks carry no verdict
  std::map<std::string, ValueStats> by_kind;
  std::vector<FirmwareStats> by_firmware;
  std::vector<std::pair<std::string, int>> failure_reasons;  // sorted by count desc, then name
  int tasks_with_retry = 0, recovered = 0, unrecovered = 0;
  double recovery_rate = 0;
  std::vector<TrendPoint> trend;  // last <= 500 measured tasks, oldest first
};

// `runs` must be ordered newest first (as ResultStore returns them).
SummaryReport compute_summary(const std::vector<const RunRecord*>& runs);

// Running mean/std accumulator (Welford), exposed for tests.
class RunningStats {
 public:
  void add(double v);
  int count() const { return n_; }
  double mean() const { return mean_; }
  double stddev() const;  // sample standard deviation, 0 for n < 2
  double min() const { return min_; }
  double max() const { return max_; }

 private:
  int n_ = 0;
  double mean_ = 0, m2_ = 0, min_ = 0, max_ = 0;
};

}  // namespace mf
