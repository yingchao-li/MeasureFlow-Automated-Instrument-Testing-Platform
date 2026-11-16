#pragma once

#include <string>

#include "measureflow/util/time.hpp"

namespace mf {

// run-YYYYMMDD-HHMMSS-xxxx (UTC, 4 lowercase hex chars from a thread-safe RNG)
std::string make_run_id(SystemClock::time_point tp = SystemClock::now());
// <run_id>-T003
std::string make_task_id(const std::string& run_id, int index);

}  // namespace mf
