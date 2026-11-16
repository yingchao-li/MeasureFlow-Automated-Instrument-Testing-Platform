#include "measureflow/report/csv_report.hpp"

#include "measureflow/util/strings.hpp"

namespace mf {

const char* csv_header() {
  return "task_id,run_id,sequence_id,step_id,test_name,kind,status,value,unit,limit_min,limit_max,frequency_hz,"
         "amplitude_vpk,attempts,duration_ms,timestamp,dut_profile,dut_firmware,error_code,message";
}

namespace {
std::string num(const std::optional<double>& v) { return v ? format_g(*v, 9) : std::string(); }
}  // namespace

std::string run_to_csv(const RunRecord& run) {
  std::string out = csv_header();
  out += '\n';
  for (const auto& t : run.tasks) {
    const std::string unit = t.measured ? t.measured->unit : t.limits.unit;
    const std::vector<std::string> cols = {
        csv_escape(t.task_id, false),
        csv_escape(t.run_id, false),
        csv_escape(run.sequence_id, true),
        csv_escape(t.step_id, true),
        csv_escape(t.test_name, true),
        csv_escape(t.kind, true),
        csv_escape(to_string(t.status), false),
        t.measured ? format_g(t.measured->value, 9) : std::string(),
        csv_escape(unit, true),
        num(t.limits.min),
        num(t.limits.max),
        num(t.inputs.frequency_hz),
        num(t.inputs.amplitude_vpk),
        std::to_string(t.attempts),
        format_fixed(t.duration_ms, 3),
        csv_escape(t.timestamp, false),
        csv_escape(t.dut_profile, true),
        csv_escape(t.dut_firmware, true),
        csv_escape(t.error_code, true),
        csv_escape(t.message, true)};
    for (size_t i = 0; i < cols.size(); ++i) {
      if (i) out += ',';
      out += cols[i];
    }
    out += '\n';
  }
  return out;
}

}  // namespace mf
