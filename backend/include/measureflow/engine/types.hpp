// Data model of test runs (docs/INTERFACE.md sections 5.10-5.13, 7). Plain structs, no JSON here.
#pragma once

#include <map>
#include <optional>
#include <string>
#include <vector>

#include "measureflow/util/logger.hpp"

namespace mf {

enum class Status { Pending, Running, Pass, Fail, Error, Cancelled };
const char* to_string(Status s);
std::optional<Status> parse_status(const std::string& s);
bool is_final(Status s);

struct TaskInputs {
  std::optional<double> frequency_hz;
  std::optional<double> amplitude_vpk;
  std::string function;     // "SIN" ...
  std::string measurement;  // set for sweep points ("gain")
};

struct Measured {
  double value = 0.0;
  std::string unit;
};

struct Limits {
  std::optional<double> min;
  std::optional<double> max;
  std::string unit;
};

struct TaskResult {
  std::string task_id;
  std::string run_id;
  std::string step_id;
  std::string test_name;
  std::string kind;  // rms|gain|thd|snr|noise_floor|freq_sweep
  Status status = Status::Pending;
  TaskInputs inputs;
  std::optional<Measured> measured;  // absent for ERROR/CANCELLED
  Limits limits;
  double duration_ms = 0.0;
  std::string timestamp;
  int attempts = 1;
  std::string message;
  std::string error_code;  // empty = null
  std::string dut_profile;
  std::string dut_firmware;
};

struct StepRecord {
  std::string id;
  std::string name;
  std::string type;
  Status status = Status::Pending;
  std::string started_at;  // empty = null
  double duration_ms = 0.0;
  std::string message;
};

struct RunError {
  std::string code;
  std::string message;
};

struct DutSelection {
  std::string profile;
  std::string firmware;
};

struct RunCounts {
  int pass = 0, fail = 0, error = 0, cancelled = 0, pending = 0, running = 0;
};

struct RunRecord {
  std::string run_id;
  std::string sequence_id;
  std::string sequence_name;
  std::string sequence_version;
  std::string label;
  Status status = Status::Pending;
  double progress = 0.0;
  std::string current_step;
  bool cancel_requested = false;
  std::string created_at, started_at, finished_at;  // empty = null
  double duration_ms = 0.0;
  DutSelection dut;
  int retries = 1;
  std::map<std::string, double> parameters;
  std::vector<StepRecord> steps;
  std::vector<TaskResult> tasks;
  std::vector<LogEntry> log;
  std::optional<RunError> error;
  // planning information for the progress / PENDING count
  int planned_tasks = 0;
  int running_tasks = 0;
};

RunCounts count_tasks(const RunRecord& r);
// Run-status precedence at completion: CANCELLED > ERROR > FAIL > PASS.
Status aggregate_status(bool cancelled, bool aborted, const std::vector<TaskResult>& tasks);

}  // namespace mf
