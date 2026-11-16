// Simulated calibration records and the validity maths used by the Environment Manager.
#pragma once

#include <cstdint>
#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace mf {

struct CalibrationRecord {
  std::string instrument_id;
  std::string certificate;
  std::string calibrated_on;  // YYYY-MM-DD
  int valid_days = 0;
  bool simulated = true;
};

struct CalibrationStatus {
  std::string status = "none";  // valid | due_soon | expired | none
  std::string certificate;
  std::string calibrated_on;
  std::string due;               // empty when status == none
  std::optional<int64_t> days_remaining;
  bool simulated = true;
};

inline constexpr int kCalibrationDueSoonDays = 30;

// days_remaining = (calibrated_on + valid_days) - today
//   > 30  -> valid;  0..30 -> due_soon;  < 0 -> expired.
// Returns status "none" when the date cannot be parsed.
CalibrationStatus compute_calibration_status(const CalibrationRecord& rec, int64_t today_days);
// Pure threshold function (exposed for boundary tests).
const char* classify_days_remaining(int64_t days_remaining);

class CalibrationBook {
 public:
  // Never throws: problems are collected in warnings() so a bad record cannot take the system down.
  static CalibrationBook load(const std::filesystem::path& path);
  void add(CalibrationRecord rec) { records_[rec.instrument_id] = std::move(rec); }
  const CalibrationRecord* find(const std::string& instrument_id) const;
  CalibrationStatus status_for(const std::string& instrument_id, int64_t today_days) const;
  const std::map<std::string, CalibrationRecord>& records() const { return records_; }
  const std::vector<std::string>& warnings() const { return warnings_; }

 private:
  std::map<std::string, CalibrationRecord> records_;
  std::vector<std::string> warnings_;
};

}  // namespace mf
