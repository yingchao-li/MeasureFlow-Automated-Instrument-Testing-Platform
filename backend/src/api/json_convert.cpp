#include "measureflow/api/json_convert.hpp"

#include <cmath>

#include "measureflow/engine/serialize.hpp"

namespace mf {

using nlohmann::json;

json finite_or_null(double v) { return std::isfinite(v) ? json(v) : json(nullptr); }

static json opt_str(const std::string& s) { return s.empty() ? json(nullptr) : json(s); }

json instrument_to_json(const InstrumentInfo& i) {
  json cal = json{{"status", i.calibration.status},
                  {"due", i.calibration.due.empty() ? json(nullptr) : json(i.calibration.due)},
                  {"days_remaining", i.calibration.days_remaining ? json(*i.calibration.days_remaining) : json(nullptr)}};
  return json{{"id", i.id},
              {"name", i.name},
              {"kind", to_string(i.kind)},
              {"host", i.host},
              {"port", i.port},
              {"state", to_string(i.state)},
              {"idn", opt_str(i.idn)},
              {"firmware", opt_str(i.firmware)},
              {"last_error", opt_str(i.last_error)},
              {"last_seen", opt_str(i.last_seen)},
              {"latency_ms", i.latency_ms ? json(round_to(*i.latency_ms, 2)) : json(nullptr)},
              {"leased_by", opt_str(i.leased_by)},
              {"calibration", cal},
              {"settings", i.settings ? settings_to_json(*i.settings) : json(nullptr)}};
}

static json checks_to_json(const std::vector<HealthCheck>& checks) {
  json a = json::array();
  for (const auto& c : checks) a.push_back(json{{"name", c.name}, {"status", c.status}, {"detail", c.detail}});
  return a;
}

json health_to_json(const HealthReport& h) {
  return json{{"status", h.status},
              {"version", h.backend_version},
              {"time", h.time},
              {"uptime_s", round_to(h.uptime_s, 1)},
              {"instruments_online", h.instruments_online},
              {"instruments_total", h.instruments_total},
              {"running_test", h.running_test ? json(*h.running_test) : json(nullptr)},
              {"software", json{{"backend", h.backend_version}, {"simulator", h.simulator_version}, {"config_version", h.config_version}}},
              {"checks", checks_to_json(h.checks)}};
}

json environment_to_json(const EnvironmentReport& e) {
  json inst = json::array();
  for (const auto& i : e.instruments) {
    inst.push_back(json{{"id", i.id},
                        {"idn", opt_str(i.idn)},
                        {"firmware", opt_str(i.firmware)},
                        {"state", to_string(i.state)}});
  }
  json cal = json::array();
  for (const auto& kv : e.calibration) {
    const CalibrationStatus& c = kv.second;
    cal.push_back(json{{"instrument_id", kv.first},
                       {"certificate", c.certificate},
                       {"calibrated_on", c.calibrated_on},
                       {"due", c.due.empty() ? json(nullptr) : json(c.due)},
                       {"days_remaining", c.days_remaining ? json(*c.days_remaining) : json(nullptr)},
                       {"status", c.status},
                       {"simulated", c.simulated}});
  }
  json hist = json{{"runs", e.history.runs},
                   {"tasks", e.history.tasks},
                   {"first_run", opt_str(e.history.first_run)},
                   {"last_run", opt_str(e.history.last_run)}};
  return json{{"software", json{{"backend", e.backend_version},
                                {"simulator", e.simulator_version},
                                {"config_version", e.config_version},
                                {"compiler", e.compiler},
                                {"api_version", e.api_version}}},
              {"instruments", inst},
              {"calibration", cal},
              {"dependencies", checks_to_json(e.dependencies)},
              {"history", hist},
              {"config", json{{"instruments_version", e.instruments_version}, {"sequences", e.sequences}, {"problems", e.problems}}}};
}

static json value_stats_json(const ValueStats& v, bool with_verdicts) {
  json j = json::object();
  j["count"] = v.count;
  if (with_verdicts) {
    j["pass"] = v.pass;
    j["fail"] = v.fail;
    j["error"] = v.error;
  }
  if (v.n_values > 0) {
    j["mean"] = round_to(v.mean, 6);
    j["std"] = round_to(v.std, 6);
    j["min"] = v.min;
    j["max"] = v.max;
  } else {
    j["mean"] = nullptr;
    j["std"] = nullptr;
    j["min"] = nullptr;
    j["max"] = nullptr;
  }
  j["unit"] = v.unit;
  return j;
}

json summary_to_json(const SummaryReport& s) {
  json by_kind = json::object();
  for (const auto& kv : s.by_kind) by_kind[kv.first] = value_stats_json(kv.second, true);
  json fws = json::array();
  for (const auto& f : s.by_firmware) {
    json bk = json::object();
    for (const auto& kv : f.by_kind) bk[kv.first] = value_stats_json(kv.second, false);
    fws.push_back(json{{"firmware", f.firmware}, {"tasks", f.tasks}, {"pass", f.pass}, {"fail", f.fail},
                       {"error", f.error}, {"pass_rate", round_to(f.pass_rate, 4)}, {"by_kind", bk}});
  }
  json reasons = json::array();
  for (const auto& r : s.failure_reasons) reasons.push_back(json{{"reason", r.first}, {"count", r.second}});
  json trend = json::array();
  for (const auto& t : s.trend) {
    trend.push_back(json{{"timestamp", t.timestamp}, {"run_id", t.run_id}, {"kind", t.kind}, {"value", t.value},
                         {"unit", t.unit}, {"status", t.status}, {"firmware", t.firmware}});
  }
  return json{{"generated_at", s.generated_at},
              {"runs", json{{"total", s.runs_total}, {"PASS", s.runs_pass}, {"FAIL", s.runs_fail}, {"ERROR", s.runs_error}, {"CANCELLED", s.runs_cancelled}}},
              {"tasks", json{{"total", s.tasks_total}, {"PASS", s.tasks_pass}, {"FAIL", s.tasks_fail}, {"ERROR", s.tasks_error},
                             {"CANCELLED", s.tasks_cancelled}, {"pass_rate", round_to(s.pass_rate, 4)}}},
              {"by_kind", by_kind},
              {"by_firmware", fws},
              {"failure_reasons", reasons},
              {"recovery", json{{"tasks_with_retry", s.tasks_with_retry}, {"recovered", s.recovered}, {"unrecovered", s.unrecovered},
                                {"recovery_rate", round_to(s.recovery_rate, 4)}}},
              {"trend", trend}};
}

}  // namespace mf
