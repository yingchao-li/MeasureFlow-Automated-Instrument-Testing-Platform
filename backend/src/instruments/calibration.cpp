#include "measureflow/instruments/calibration.hpp"

#include "json.hpp"
#include "measureflow/util/fs.hpp"
#include "measureflow/util/strings.hpp"
#include "measureflow/util/time.hpp"

namespace mf {

const char* classify_days_remaining(int64_t days_remaining) {
  if (days_remaining < 0) return "expired";
  if (days_remaining <= kCalibrationDueSoonDays) return "due_soon";
  return "valid";
}

CalibrationStatus compute_calibration_status(const CalibrationRecord& rec, int64_t today) {
  CalibrationStatus st;
  st.certificate = rec.certificate;
  st.calibrated_on = rec.calibrated_on;
  st.simulated = rec.simulated;
  const auto day = parse_iso_date(rec.calibrated_on);
  if (!day || rec.valid_days <= 0) return st;
  const int64_t due_day = *day + rec.valid_days;
  st.due = date_from_days(due_day);
  st.days_remaining = due_day - today;
  st.status = classify_days_remaining(*st.days_remaining);
  return st;
}

CalibrationBook CalibrationBook::load(const std::filesystem::path& path) {
  CalibrationBook book;
  const auto text = read_file(path, 1u << 20);
  if (!text) {
    book.warnings_.push_back("calibration file not readable: " + path.string());
    return book;
  }
  const nlohmann::json j = nlohmann::json::parse(*text, nullptr, false);
  if (j.is_discarded() || !j.is_object() || !j.contains("records") || !j["records"].is_array()) {
    book.warnings_.push_back("calibration file is not valid: " + path.string());
    return book;
  }
  int idx = 0;
  for (const auto& r : j["records"]) {
    const std::string where = "records[" + std::to_string(idx++) + "]";
    if (!r.is_object() || !r.contains("instrument_id") || !r["instrument_id"].is_string() || !r.contains("calibrated_on") ||
        !r["calibrated_on"].is_string() || !r.contains("valid_days") || !r["valid_days"].is_number_integer()) {
      book.warnings_.push_back(where + ": missing/invalid instrument_id, calibrated_on or valid_days");
      continue;
    }
    CalibrationRecord rec;
    rec.instrument_id = r["instrument_id"].get<std::string>();
    rec.calibrated_on = r["calibrated_on"].get<std::string>();
    rec.valid_days = r["valid_days"].get<int>();
    rec.certificate = r.contains("certificate") && r["certificate"].is_string() ? r["certificate"].get<std::string>() : "";
    rec.simulated = !r.contains("simulated") || !r["simulated"].is_boolean() || r["simulated"].get<bool>();
    if (!parse_iso_date(rec.calibrated_on) || rec.valid_days <= 0) {
      book.warnings_.push_back(where + " (" + rec.instrument_id + "): invalid calibrated_on '" + rec.calibrated_on + "' or valid_days");
    }
    book.records_[rec.instrument_id] = std::move(rec);
  }
  return book;
}

const CalibrationRecord* CalibrationBook::find(const std::string& instrument_id) const {
  const auto it = records_.find(instrument_id);
  return it == records_.end() ? nullptr : &it->second;
}

CalibrationStatus CalibrationBook::status_for(const std::string& instrument_id, int64_t today) const {
  const auto* rec = find(instrument_id);
  if (!rec) return CalibrationStatus{};
  return compute_calibration_status(*rec, today);
}

}  // namespace mf
