#include "measureflow/engine/sequence.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <set>

#include "json.hpp"
#include "measureflow/instruments/settings.hpp"
#include "measureflow/util/errors.hpp"
#include "measureflow/util/fs.hpp"
#include "measureflow/util/strings.hpp"

namespace mf {

using nlohmann::json;

const char* to_string(StepType t) {
  switch (t) {
    case StepType::Init: return "init";
    case StepType::ConfigureSignal: return "configure_signal";
    case StepType::ConfigureDut: return "configure_dut";
    case StepType::Measure: return "measure";
    case StepType::Sweep: return "sweep";
    case StepType::Cleanup: return "cleanup";
    case StepType::Report: return "report";
  }
  return "init";
}

std::optional<StepType> parse_step_type(const std::string& s) {
  static const StepType all[] = {StepType::Init,   StepType::ConfigureSignal, StepType::ConfigureDut, StepType::Measure,
                                 StepType::Sweep,  StepType::Cleanup,         StepType::Report};
  for (StepType t : all) {
    if (s == to_string(t)) return t;
  }
  return std::nullopt;
}

const ParamDef* SequenceDef::find_param(const std::string& key) const {
  for (const auto& p : parameters) {
    if (p.key == key) return &p;
  }
  return nullptr;
}

namespace {

[[noreturn]] void bad(const std::string& origin, const std::string& path, const std::string& msg) {
  throw MfError(ErrorCode::InvalidArgument, origin + ": " + (path.empty() ? "" : path + ": ") + msg);
}

bool valid_param_key(const std::string& k) {
  if (k.empty() || k.size() > 64) return false;
  if (!(std::isalpha(static_cast<unsigned char>(k[0])) || k[0] == '_')) return false;
  return std::all_of(k.begin(), k.end(), [](char c) { return std::isalnum(static_cast<unsigned char>(c)) || c == '_'; });
}

// "${name}" (whole string) -> name
std::optional<std::string> whole_template(const std::string& s) {
  if (s.size() > 3 && s[0] == '$' && s[1] == '{' && s.back() == '}') {
    const std::string k = s.substr(2, s.size() - 3);
    if (valid_param_key(k)) return k;
  }
  return std::nullopt;
}

struct Ctx {
  const std::string& origin;
  const std::set<std::string>& params;
};

NumExpr parse_numexpr(const Ctx& c, const json& v, const std::string& path, bool allow_null) {
  if (v.is_null()) {
    if (!allow_null) bad(c.origin, path, "must not be null");
    return NumExpr{};
  }
  if (v.is_number()) {
    const double d = v.get<double>();
    if (!std::isfinite(d)) bad(c.origin, path, "must be finite");
    return NumExpr::literal(d);
  }
  if (v.is_string()) {
    const auto k = whole_template(v.get<std::string>());
    if (!k) bad(c.origin, path, "string value must be a '${parameter}' template");
    if (!c.params.count(*k)) bad(c.origin, path, "references undeclared parameter '" + *k + "'");
    return NumExpr::ref(*k);
  }
  bad(c.origin, path, "must be a number, null or a '${parameter}' template");
}

std::string get_string(const std::string& origin, const json& o, const char* key, const std::string& path, bool required,
                       const std::string& def = {}, size_t max_len = 200) {
  if (!o.contains(key)) {
    if (required) bad(origin, path, std::string("missing '") + key + "'");
    return def;
  }
  if (!o[key].is_string()) bad(origin, path + "." + key, "must be a string");
  const std::string s = o[key].get<std::string>();
  if (s.size() > max_len) bad(origin, path + "." + key, "too long");
  return s;
}

}  // namespace

SequenceDef parse_sequence(const std::string& text, const std::string& origin) {
  json j = json::parse(text, nullptr, false);
  if (j.is_discarded()) bad(origin, "", "not valid JSON");
  if (!j.is_object()) bad(origin, "", "top level must be an object");
  SequenceDef seq;
  seq.id = get_string(origin, j, "id", "", true, {}, 64);
  if (!is_valid_id(seq.id)) bad(origin, "id", "must match [A-Za-z0-9._-]{1,64}");
  seq.name = get_string(origin, j, "name", "", true, {}, 128);
  if (seq.name.empty()) bad(origin, "name", "must not be empty");
  seq.version = get_string(origin, j, "version", "", false, "1.0.0", 32);
  seq.description = get_string(origin, j, "description", "", false, "", 1000);

  seq.dut.profile = "NORMAL";
  seq.dut.firmware = "1.0.0";
  if (j.contains("dut")) {
    const json& d = j["dut"];
    if (!d.is_object()) bad(origin, "dut", "must be an object");
    seq.dut.profile = to_upper(get_string(origin, d, "profile", "dut", false, "NORMAL", 32));
    seq.dut.firmware = get_string(origin, d, "firmware", "dut", false, "1.0.0", 32);
  }
  Settings dut_probe{{"profile", seq.dut.profile}, {"firmware", seq.dut.firmware}};
  try {
    validate_settings(InstrumentKind::DeviceUnderTest, dut_probe);
  } catch (const MfError& e) {
    bad(origin, "dut", e.what());
  }

  std::set<std::string> param_keys;
  if (j.contains("parameters")) {
    if (!j["parameters"].is_object()) bad(origin, "parameters", "must be an object");
    for (auto it = j["parameters"].begin(); it != j["parameters"].end(); ++it) {
      const std::string path = "parameters." + it.key();
      if (!valid_param_key(it.key())) bad(origin, path, "invalid parameter name");
      if (!it.value().is_object()) bad(origin, path, "must be an object");
      ParamDef p;
      p.key = it.key();
      p.label = get_string(origin, it.value(), "label", path, false, p.key, 128);
      p.unit = get_string(origin, it.value(), "unit", path, false, "", 16);
      for (const char* f : {"default", "min", "max"}) {
        if (!it.value().contains(f) || !it.value()[f].is_number()) bad(origin, path, std::string("'") + f + "' must be a number");
        if (!std::isfinite(it.value()[f].get<double>())) bad(origin, path, std::string("'") + f + "' must be finite");
      }
      p.def = it.value()["default"].get<double>();
      p.min = it.value()["min"].get<double>();
      p.max = it.value()["max"].get<double>();
      if (p.min > p.max) bad(origin, path, "min > max");
      if (p.def < p.min || p.def > p.max) bad(origin, path, "default outside [min, max]");
      param_keys.insert(p.key);
      seq.parameters.push_back(std::move(p));
    }
  }

  if (!j.contains("steps") || !j["steps"].is_array() || j["steps"].empty()) bad(origin, "steps", "must be a non-empty array");
  if (j["steps"].size() > 100) bad(origin, "steps", "too many steps (max 100)");
  const Ctx ctx{origin, param_keys};
  std::set<std::string> step_ids;
  int idx = 0;
  for (const json& s : j["steps"]) {
    const std::string path = "steps[" + std::to_string(idx++) + "]";
    if (!s.is_object()) bad(origin, path, "must be an object");
    StepDef st;
    st.id = get_string(origin, s, "id", path, true, {}, 64);
    if (!is_valid_id(st.id)) bad(origin, path + ".id", "must match [A-Za-z0-9._-]{1,64}");
    if (!step_ids.insert(st.id).second) bad(origin, path + ".id", "duplicate step id '" + st.id + "'");
    const std::string tname = get_string(origin, s, "type", path, true, {}, 32);
    const auto type = parse_step_type(tname);
    if (!type) bad(origin, path + ".type", "unknown step type '" + tname + "'");
    st.type = *type;
    st.name = get_string(origin, s, "name", path, false, st.id, 200);

    switch (st.type) {
      case StepType::Init: {
        if (s.contains("instruments")) {
          if (!s["instruments"].is_array()) bad(origin, path + ".instruments", "must be an array");
          for (const auto& i : s["instruments"]) {
            if (!i.is_string() || !is_valid_id(i.get<std::string>())) bad(origin, path + ".instruments", "entries must be instrument ids");
            st.instruments.push_back(i.get<std::string>());
          }
        }
        break;
      }
      case StepType::ConfigureSignal: {
        st.function = to_upper(get_string(origin, s, "function", path, false, "SIN", 8));
        if (!s.contains("frequency_hz")) bad(origin, path, "missing 'frequency_hz'");
        if (!s.contains("amplitude_vpk")) bad(origin, path, "missing 'amplitude_vpk'");
        st.frequency_hz = parse_numexpr(ctx, s["frequency_hz"], path + ".frequency_hz", false);
        st.amplitude_vpk = parse_numexpr(ctx, s["amplitude_vpk"], path + ".amplitude_vpk", false);
        if (s.contains("sample_rate_hz")) st.sample_rate_hz = parse_numexpr(ctx, s["sample_rate_hz"], path + ".sample_rate_hz", true);
        if (s.contains("settle_ms")) st.settle_ms = parse_numexpr(ctx, s["settle_ms"], path + ".settle_ms", true);
        if (s.contains("output")) {
          if (!s["output"].is_boolean()) bad(origin, path + ".output", "must be a boolean");
          st.output = s["output"].get<bool>();
        }
        break;
      }
      case StepType::ConfigureDut: {
        if (s.contains("settings")) {
          if (!s["settings"].is_object()) bad(origin, path + ".settings", "must be an object");
          for (auto it = s["settings"].begin(); it != s["settings"].end(); ++it) {
            const std::string p2 = path + ".settings." + it.key();
            if (it.value().is_string() && !whole_template(it.value().get<std::string>())) {
              st.dut_text[it.key()] = it.value().get<std::string>();
            } else {
              st.dut_numeric[it.key()] = parse_numexpr(ctx, it.value(), p2, false);
            }
          }
        }
        break;
      }
      case StepType::Measure:
      case StepType::Sweep: {
        const std::string mname = get_string(origin, s, "measurement", path, true, {}, 32);
        const auto m = parse_measurement(mname);
        if (!m) bad(origin, path + ".measurement", "unknown measurement '" + mname + "'");
        if (st.type == StepType::Sweep && *m != Measurement::Gain) bad(origin, path + ".measurement", "sweep supports only 'gain'");
        st.measurement = *m;
        if (!s.contains("limits") || !s["limits"].is_object()) bad(origin, path + ".limits", "must be an object");
        const json& l = s["limits"];
        st.limits.min = l.contains("min") ? parse_numexpr(ctx, l["min"], path + ".limits.min", true) : NumExpr{};
        st.limits.max = l.contains("max") ? parse_numexpr(ctx, l["max"], path + ".limits.max", true) : NumExpr{};
        st.limits.unit = get_string(origin, l, "unit", path + ".limits", false, measurement_unit(*m), 16);
        if (st.type == StepType::Sweep) {
          if (!s.contains("points_hz") || !s["points_hz"].is_array() || s["points_hz"].empty()) bad(origin, path + ".points_hz", "must be a non-empty array");
          if (s["points_hz"].size() > 64) bad(origin, path + ".points_hz", "too many points (max 64)");
          int pi = 0;
          for (const auto& p : s["points_hz"]) {
            st.points_hz.push_back(parse_numexpr(ctx, p, path + ".points_hz[" + std::to_string(pi++) + "]", false));
          }
          if (!s.contains("amplitude_vpk")) bad(origin, path, "missing 'amplitude_vpk'");
          st.amplitude_vpk = parse_numexpr(ctx, s["amplitude_vpk"], path + ".amplitude_vpk", false);
          if (s.contains("settle_ms")) st.settle_ms = parse_numexpr(ctx, s["settle_ms"], path + ".settle_ms", true);
        }
        break;
      }
      case StepType::Cleanup:
      case StepType::Report: break;
    }
    seq.steps.push_back(std::move(st));
  }
  return seq;
}

// ---------------------------------------------------------------------------------------------------

void SequenceLibrary::add(SequenceDef def) {
  const std::string id = def.id;
  by_id_[id] = std::move(def);
}

void SequenceLibrary::load_directory(const std::filesystem::path& dir) {
  std::error_code ec;
  if (!std::filesystem::is_directory(dir, ec)) {
    errors_.push_back("sequence directory not found: " + dir.string());
    return;
  }
  std::vector<std::filesystem::path> files;
  for (const auto& e : std::filesystem::directory_iterator(dir, ec)) {
    if (e.is_regular_file() && e.path().extension() == ".json") files.push_back(e.path());
  }
  std::sort(files.begin(), files.end());
  for (const auto& f : files) {
    const auto text = read_file(f, 1u << 20);
    if (!text) {
      errors_.push_back(f.string() + ": cannot read file");
      continue;
    }
    try {
      SequenceDef def = parse_sequence(*text, f.filename().string());
      if (by_id_.count(def.id)) {
        errors_.push_back(f.filename().string() + ": duplicate sequence id '" + def.id + "'");
        continue;
      }
      add(std::move(def));
    } catch (const MfError& e) {
      errors_.push_back(e.what());
    }
  }
}

const SequenceDef* SequenceLibrary::find(const std::string& id) const {
  const auto it = by_id_.find(id);
  return it == by_id_.end() ? nullptr : &it->second;
}

std::vector<const SequenceDef*> SequenceLibrary::list() const {
  std::vector<const SequenceDef*> out;
  for (const auto& kv : by_id_) out.push_back(&kv.second);
  return out;
}

// ---------------------------------------------------------------------------------------------------

std::map<std::string, double> resolve_parameters(const SequenceDef& seq, const std::map<std::string, double>& overrides) {
  std::map<std::string, double> out;
  for (const auto& p : seq.parameters) out[p.key] = p.def;
  for (const auto& kv : overrides) {
    const ParamDef* p = seq.find_param(kv.first);
    if (!p) throw MfError(ErrorCode::InvalidArgument, "parameter '" + kv.first + "' is not declared by sequence '" + seq.id + "'", "parameters." + kv.first);
    if (!std::isfinite(kv.second) || kv.second < p->min || kv.second > p->max) {
      throw MfError(ErrorCode::InvalidArgument,
                    "parameter '" + kv.first + "' must be within [" + format_g(p->min, 9) + ", " + format_g(p->max, 9) + "]",
                    "parameters." + kv.first);
    }
    out[kv.first] = kv.second;
  }
  return out;
}

std::string render_template(const std::string& text, const std::map<std::string, double>& params) {
  std::string out;
  size_t i = 0;
  while (i < text.size()) {
    if (text[i] == '$' && i + 1 < text.size() && text[i + 1] == '{') {
      const size_t end = text.find('}', i + 2);
      if (end != std::string::npos) {
        const std::string key = text.substr(i + 2, end - i - 2);
        const auto it = params.find(key);
        if (it != params.end()) {
          out += format_g(it->second, 9);
          i = end + 1;
          continue;
        }
      }
    }
    out += text[i++];
  }
  return out;
}

namespace {

double eval(const NumExpr& e, const std::map<std::string, double>& params) {
  if (e.kind == NumExpr::Kind::Literal) return e.value;
  const auto it = params.find(e.param);
  if (it == params.end()) throw MfError(ErrorCode::Internal, "unresolved parameter '" + e.param + "'");
  return it->second;
}

std::optional<double> eval_opt(const NumExpr& e, const std::map<std::string, double>& params) {
  if (e.is_null()) return std::nullopt;
  return eval(e, params);
}

[[noreturn]] void plan_error(const StepDef& st, const std::string& msg, const std::string& field = {}) {
  throw MfError(ErrorCode::InvalidArgument, "step '" + st.id + "': " + msg, field);
}

void check_range(const StepDef& st, const char* what, double v, double lo, double hi) {
  if (!std::isfinite(v) || v < lo || v > hi) {
    plan_error(st, std::string(what) + " = " + format_g(v, 9) + " is outside [" + format_g(lo, 9) + ", " + format_g(hi, 9) + "]");
  }
}

}  // namespace

ResolvedPlan build_plan(const SequenceDef& seq, const std::map<std::string, double>& params) {
  ResolvedPlan plan;
  for (const StepDef& st : seq.steps) {
    ResolvedStep rs;
    rs.def = &st;
    rs.name = render_template(st.name, params);
    switch (st.type) {
      case StepType::ConfigureSignal: {
        const double f = eval(st.frequency_hz, params);
        const double a = eval(st.amplitude_vpk, params);
        check_range(st, "frequency_hz", f, 10, 20000);
        check_range(st, "amplitude_vpk", a, 0, 5);
        rs.signal["function"] = st.function;
        rs.signal["frequency_hz"] = f;
        rs.signal["amplitude_vpk"] = a;
        if (!st.sample_rate_hz.is_null()) rs.signal["sample_rate_hz"] = eval(st.sample_rate_hz, params);
        rs.signal["output"] = st.output;
        try {
          Settings copy = rs.signal;
          validate_settings(InstrumentKind::SignalGenerator, copy);
          rs.signal = copy;
        } catch (const MfError& e) {
          plan_error(st, e.what(), e.field());
        }
        const double settle = st.settle_ms.is_null() ? 0.0 : eval(st.settle_ms, params);
        check_range(st, "settle_ms", settle, 0, 10000);
        rs.settle_ms = static_cast<int>(settle);
        break;
      }
      case StepType::ConfigureDut: {
        for (const auto& kv : st.dut_numeric) rs.dut[kv.first] = eval(kv.second, params);
        for (const auto& kv : st.dut_text) rs.dut[kv.first] = kv.second;
        if (!rs.dut.empty()) {
          try {
            validate_settings(InstrumentKind::DeviceUnderTest, rs.dut);
          } catch (const MfError& e) {
            plan_error(st, e.what(), e.field());
          }
        }
        break;
      }
      case StepType::Measure:
      case StepType::Sweep: {
        rs.limits.unit = st.limits.unit;
        rs.limits.min = eval_opt(st.limits.min, params);
        rs.limits.max = eval_opt(st.limits.max, params);
        if (rs.limits.min && rs.limits.max && *rs.limits.min > *rs.limits.max) {
          plan_error(st, "lower limit " + format_g(*rs.limits.min, 9) + " is greater than upper limit " + format_g(*rs.limits.max, 9));
        }
        if (st.type == StepType::Sweep) {
          for (const auto& p : st.points_hz) {
            const double f = eval(p, params);
            check_range(st, "sweep point", f, 10, 20000);
            rs.points_hz.push_back(f);
          }
          rs.sweep_amplitude_vpk = eval(st.amplitude_vpk, params);
          check_range(st, "amplitude_vpk", rs.sweep_amplitude_vpk, 0, 5);
          const double settle = st.settle_ms.is_null() ? 0.0 : eval(st.settle_ms, params);
          check_range(st, "settle_ms", settle, 0, 10000);
          rs.settle_ms = static_cast<int>(settle);
          plan.planned_tasks += static_cast<int>(rs.points_hz.size());
          plan.planned_units += static_cast<int>(rs.points_hz.size());
        } else {
          plan.planned_tasks += 1;
          plan.planned_units += 1;
        }
        break;
      }
      case StepType::Init:
      case StepType::Cleanup:
      case StepType::Report: break;
    }
    if (st.type != StepType::Measure && st.type != StepType::Sweep) plan.planned_units += 1;
    plan.steps.push_back(std::move(rs));
  }
  return plan;
}

}  // namespace mf
