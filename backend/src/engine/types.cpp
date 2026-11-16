#include "measureflow/engine/types.hpp"

namespace mf {

const char* to_string(Status s) {
  switch (s) {
    case Status::Pending: return "PENDING";
    case Status::Running: return "RUNNING";
    case Status::Pass: return "PASS";
    case Status::Fail: return "FAIL";
    case Status::Error: return "ERROR";
    case Status::Cancelled: return "CANCELLED";
  }
  return "PENDING";
}

std::optional<Status> parse_status(const std::string& s) {
  if (s == "PENDING") return Status::Pending;
  if (s == "RUNNING") return Status::Running;
  if (s == "PASS") return Status::Pass;
  if (s == "FAIL") return Status::Fail;
  if (s == "ERROR") return Status::Error;
  if (s == "CANCELLED") return Status::Cancelled;
  return std::nullopt;
}

bool is_final(Status s) { return s == Status::Pass || s == Status::Fail || s == Status::Error || s == Status::Cancelled; }

RunCounts count_tasks(const RunRecord& r) {
  RunCounts c;
  for (const auto& t : r.tasks) {
    switch (t.status) {
      case Status::Pass: ++c.pass; break;
      case Status::Fail: ++c.fail; break;
      case Status::Error: ++c.error; break;
      case Status::Cancelled: ++c.cancelled; break;
      case Status::Pending: ++c.pending; break;
      case Status::Running: ++c.running; break;
    }
  }
  if (!is_final(r.status)) {
    c.running += r.running_tasks;
    const int remaining = r.planned_tasks - static_cast<int>(r.tasks.size()) - r.running_tasks;
    if (remaining > 0) c.pending += remaining;
  }
  return c;
}

Status aggregate_status(bool cancelled, bool aborted, const std::vector<TaskResult>& tasks) {
  if (cancelled) return Status::Cancelled;
  bool any_fail = false;
  bool any_error = aborted;
  for (const auto& t : tasks) {
    if (t.status == Status::Error) any_error = true;
    if (t.status == Status::Fail) any_fail = true;
  }
  if (any_error) return Status::Error;
  if (any_fail) return Status::Fail;
  return Status::Pass;
}

}  // namespace mf
