// Time helpers: ISO-8601 UTC formatting with milliseconds, civil-date maths
// (no dependency on the platform's timezone database), monotonic stopwatch.
#pragma once

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>

namespace mf {

using SystemClock = std::chrono::system_clock;
using SteadyClock = std::chrono::steady_clock;

// "2026-11-16T17:21:29.043Z"
std::string iso_from(SystemClock::time_point tp);
std::string iso_now();
// "20261116-172129" (UTC)
std::string compact_stamp(SystemClock::time_point tp);

// Days since 1970-01-01 for a civil date (proleptic Gregorian).
int64_t days_from_civil(int y, unsigned m, unsigned d);
// "YYYY-MM-DD" for a day number.
std::string date_from_days(int64_t days);
// Strict "YYYY-MM-DD" parser (validates month/day ranges incl. leap years).
std::optional<int64_t> parse_iso_date(const std::string& s);
// Today (UTC) as day number.
int64_t today_days();

// Parses "YYYY-MM-DDTHH:MM:SS(.mmm)Z"; returns epoch milliseconds.
std::optional<int64_t> parse_iso_millis(const std::string& s);

class Stopwatch {
 public:
  Stopwatch() : start_(SteadyClock::now()) {}
  double elapsed_ms() const {
    return std::chrono::duration<double, std::milli>(SteadyClock::now() - start_).count();
  }
  void restart() { start_ = SteadyClock::now(); }

 private:
  SteadyClock::time_point start_;
};

}  // namespace mf
