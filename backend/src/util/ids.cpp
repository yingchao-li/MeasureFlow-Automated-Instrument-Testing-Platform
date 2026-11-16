#include "measureflow/util/ids.hpp"

#include <cstdio>
#include <mutex>
#include <random>

namespace mf {

std::string make_run_id(SystemClock::time_point tp) {
  static std::mutex mu;
  static std::mt19937 rng{std::random_device{}()};
  unsigned v;
  {
    std::lock_guard<std::mutex> lock(mu);
    v = static_cast<unsigned>(rng() & 0xFFFFu);
  }
  char buf[8];
  std::snprintf(buf, sizeof buf, "%04x", v);
  return "run-" + compact_stamp(tp) + "-" + buf;
}

std::string make_task_id(const std::string& run_id, int index) {
  char buf[16];
  std::snprintf(buf, sizeof buf, "-T%03d", index);
  return run_id + buf;
}

}  // namespace mf
