#include "measureflow/engine/serialize.hpp"

#include <cmath>

namespace mf {

using nlohmann::json;

double round_to(double v, int decimals) {
  if (!std::isfinite(v)) return 0.0;
  const double f = std::pow(10.0, decimals);
  return std::round(v * f) / f;
}

namespace {
json opt_str(const std::string& s) { return s.empty() ? json(nullptr) : json(s); }
json opt_num(const std::optional<double>& v) { return v ? json(*v) : json(nullptr); }
}  // namespace

json settings_to_json(const Settings& s) {
  json o = json::object();
  for (const auto& kv : s) std::visit([&](const auto& v) { o[kv.first] = v; }, kv.second);
  return o;
}

json log_entry_to_json(const LogEntry& e) {
  json f = json::object();
  for (const auto& kv : e.fields) std::visit([&](const auto& v) { f[kv.first] = v; }, kv.second);
  return json{{"seq", e.seq}, {"ts", e.ts}, {"level", to_string(e.level)}, {"source", e.source}, {"message", e.message}, {"fields", f}};
}

json task_to_json(const TaskResult& t) {
  json inputs = json::object();
  if (t.inputs.frequency_hz) inputs["frequency_hz"] = *t.inputs.frequency_hz;
  if (t.inputs.amplitude_vpk) inputs["amplitude_vpk"] = *t.inputs.amplitude_vpk;
  if (!t.inputs.function.empty()) inputs["function"] = t.inputs.function;
  if (!t.inputs.measurement.empty()) inputs["measurement"] = t.inputs.measurement;
  json measured = nullptr;
  if (t.measured) measured = json{{"value", t.measured->value}, {"unit", t.measured->unit}};
  return json{{"task_id", t.task_id},
              {"run_id", t.run_id},
              {"step_id", t.step_id},
              {"test_name", t.test_name},
              {"kind", t.kind},
              {"status", to_string(t.status)},
              {"inputs", inputs},
              {"measured", measured},
              {"limits", json{{"min", opt_num(t.limits.min)}, {"max", opt_num(t.limits.max)}, {"unit", t.limits.unit}}},
              {"duration_ms", round_to(t.duration_ms, 3)},
              {"timestamp", t.timestamp},
              {"attempts", t.attempts},
              {"message", t.message},
              {"error_code", opt_str(t.error_code)},
              {"dut_profile", t.dut_profile},
              {"dut_firmware", t.dut_firmware}};
}

json step_to_json(const StepRecord& s) {
  return json{{"id", s.id},
              {"name", s.name},
              {"type", s.type},
              {"status", to_string(s.status)},
              {"started_at", opt_str(s.started_at)},
              {"duration_ms", round_to(s.duration_ms, 3)},
              {"message", s.message}};
}

json counts_to_json(const RunCounts& c) {
  return json{{"PASS", c.pass}, {"FAIL", c.fail}, {"ERROR", c.error}, {"CANCELLED", c.cancelled}, {"PENDING", c.pending}, {"RUNNING", c.running}};
}

json run_summary_to_json(const RunRecord& r) {
  json err = nullptr;
  if (r.error) err = json{{"code", r.error->code}, {"message", r.error->message}};
  return json{{"run_id", r.run_id},
              {"sequence_id", r.sequence_id},
              {"sequence_name", r.sequence_name},
              {"label", r.label},
              {"status", to_string(r.status)},
              {"progress", round_to(r.progress, 4)},
              {"current_step", opt_str(r.current_step)},
              {"cancel_requested", r.cancel_requested},
              {"created_at", r.created_at},
              {"started_at", opt_str(r.started_at)},
              {"finished_at", opt_str(r.finished_at)},
              {"duration_ms", round_to(r.duration_ms, 3)},
              {"dut", json{{"profile", r.dut.profile}, {"firmware", r.dut.firmware}}},
              {"retries", r.retries},
              {"counts", counts_to_json(count_tasks(r))},
              {"error", err}};
}

json run_detail_to_json(const RunRecord& r, size_t log_tail) {
  json j = run_summary_to_json(r);
  json params = json::object();
  for (const auto& kv : r.parameters) params[kv.first] = kv.second;
  j["parameters"] = params;
  j["sequence_version"] = r.sequence_version;
  j["steps"] = json::array();
  for (const auto& s : r.steps) j["steps"].push_back(step_to_json(s));
  j["tasks"] = json::array();
  for (const auto& t : r.tasks) j["tasks"].push_back(task_to_json(t));
  j["log"] = json::array();
  size_t start = 0;
  if (log_tail > 0 && r.log.size() > log_tail) start = r.log.size() - log_tail;
  for (size_t i = start; i < r.log.size(); ++i) j["log"].push_back(log_entry_to_json(r.log[i]));
  return j;
}

// ---------------------------------------------------------------------------------------------------
namespace {

std::string str_or(const json& o, const char* key, const std::string& def = {}) {
  if (o.is_object() && o.contains(key) && o[key].is_string()) return o[key].get<std::string>();
  return def;
}
double num_or(const json& o, const char* key, double def) {
  if (o.is_object() && o.contains(key) && o[key].is_number()) return o[key].get<double>();
  return def;
}
std::optional<double> opt_num_of(const json& o, const char* key) {
  if (o.is_object() && o.contains(key) && o[key].is_number()) return o[key].get<double>();
  return std::nullopt;
}

bool task_from_json(const json& j, TaskResult* t) {
  if (!j.is_object()) return false;
  t->task_id = str_or(j, "task_id");
  t->run_id = str_or(j, "run_id");
  t->step_id = str_or(j, "step_id");
  t->test_name = str_or(j, "test_name");
  t->kind = str_or(j, "kind");
  const auto st = parse_status(str_or(j, "status"));
  if (!st || t->task_id.empty()) return false;
  t->status = *st;
  if (j.contains("inputs") && j["inputs"].is_object()) {
    const json& in = j["inputs"];
    t->inputs.frequency_hz = opt_num_of(in, "frequency_hz");
    t->inputs.amplitude_vpk = opt_num_of(in, "amplitude_vpk");
    t->inputs.function = str_or(in, "function");
    t->inputs.measurement = str_or(in, "measurement");
  }
  if (j.contains("measured") && j["measured"].is_object() && j["measured"].contains("value") && j["measured"]["value"].is_number()) {
    t->measured = Measured{j["measured"]["value"].get<double>(), str_or(j["measured"], "unit")};
  }
  if (j.contains("limits") && j["limits"].is_object()) {
    t->limits.min = opt_num_of(j["limits"], "min");
    t->limits.max = opt_num_of(j["limits"], "max");
    t->limits.unit = str_or(j["limits"], "unit");
  }
  t->duration_ms = num_or(j, "duration_ms", 0);
  t->timestamp = str_or(j, "timestamp");
  t->attempts = static_cast<int>(num_or(j, "attempts", 1));
  t->message = str_or(j, "message");
  t->error_code = str_or(j, "error_code");
  t->dut_profile = str_or(j, "dut_profile");
  t->dut_firmware = str_or(j, "dut_firmware");
  return true;
}

}  // namespace

std::optional<RunRecord> run_from_json(const json& j, std::string* err) {
  auto fail = [&](const std::string& m) -> std::optional<RunRecord> {
    if (err) *err = m;
    return std::nullopt;
  };
  if (!j.is_object()) return fail("not an object");
  RunRecord r;
  r.run_id = str_or(j, "run_id");
  if (r.run_id.empty()) return fail("missing run_id");
  r.sequence_id = str_or(j, "sequence_id");
  r.sequence_name = str_or(j, "sequence_name");
  r.sequence_version = str_or(j, "sequence_version");
  r.label = str_or(j, "label");
  const auto st = parse_status(str_or(j, "status"));
  if (!st) return fail("invalid status");
  r.status = *st;
  r.progress = num_or(j, "progress", 0);
  r.current_step = str_or(j, "current_step");
  r.cancel_requested = j.contains("cancel_requested") && j["cancel_requested"].is_boolean() && j["cancel_requested"].get<bool>();
  r.created_at = str_or(j, "created_at");
  r.started_at = str_or(j, "started_at");
  r.finished_at = str_or(j, "finished_at");
  r.duration_ms = num_or(j, "duration_ms", 0);
  if (j.contains("dut") && j["dut"].is_object()) {
    r.dut.profile = str_or(j["dut"], "profile");
    r.dut.firmware = str_or(j["dut"], "firmware");
  }
  r.retries = static_cast<int>(num_or(j, "retries", 1));
  if (j.contains("parameters") && j["parameters"].is_object()) {
    for (auto it = j["parameters"].begin(); it != j["parameters"].end(); ++it) {
      if (it.value().is_number()) r.parameters[it.key()] = it.value().get<double>();
    }
  }
  if (j.contains("steps") && j["steps"].is_array()) {
    for (const auto& s : j["steps"]) {
      StepRecord sr;
      sr.id = str_or(s, "id");
      sr.name = str_or(s, "name");
      sr.type = str_or(s, "type");
      const auto ss = parse_status(str_or(s, "status"));
      sr.status = ss ? *ss : Status::Pending;
      sr.started_at = str_or(s, "started_at");
      sr.duration_ms = num_or(s, "duration_ms", 0);
      sr.message = str_or(s, "message");
      r.steps.push_back(std::move(sr));
    }
  }
  if (j.contains("tasks") && j["tasks"].is_array()) {
    for (const auto& tj : j["tasks"]) {
      TaskResult t;
      if (!task_from_json(tj, &t)) return fail("invalid task entry");
      r.tasks.push_back(std::move(t));
    }
  }
  if (j.contains("log") && j["log"].is_array()) {
    for (const auto& lj : j["log"]) {
      LogEntry e;
      e.seq = lj.contains("seq") && lj["seq"].is_number_unsigned() ? lj["seq"].get<uint64_t>() : 0;
      e.ts = str_or(lj, "ts");
      e.level = parse_log_level(str_or(lj, "level")).value_or(LogLevel::Info);
      e.source = str_or(lj, "source");
      e.message = str_or(lj, "message");
      if (lj.contains("fields") && lj["fields"].is_object()) {
        for (auto it = lj["fields"].begin(); it != lj["fields"].end(); ++it) {
          if (it.value().is_string()) e.fields.emplace_back(it.key(), it.value().get<std::string>());
          else if (it.value().is_boolean()) e.fields.emplace_back(it.key(), it.value().get<bool>());
          else if (it.value().is_number_integer()) e.fields.emplace_back(it.key(), it.value().get<int64_t>());
          else if (it.value().is_number()) e.fields.emplace_back(it.key(), it.value().get<double>());
        }
      }
      r.log.push_back(std::move(e));
    }
  }
  if (j.contains("error") && j["error"].is_object()) {
    r.error = RunError{str_or(j["error"], "code"), str_or(j["error"], "message")};
  }
  r.planned_tasks = static_cast<int>(r.tasks.size());
  return r;
}

}  // namespace mf
