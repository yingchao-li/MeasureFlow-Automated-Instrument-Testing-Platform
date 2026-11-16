#include "measureflow/instruments/settings.hpp"

#include <cmath>

#include "measureflow/util/errors.hpp"
#include "measureflow/util/strings.hpp"

namespace mf {

namespace {
using T = SettingSpec::Type;

SettingSpec num(const char* key, double lo, double hi, bool writable = true) {
  return SettingSpec{key, T::Number, lo, hi, {}, writable};
}
SettingSpec str(const char* key, std::vector<std::string> choices) {
  return SettingSpec{key, T::String, 0, 0, std::move(choices), true};
}
SettingSpec boolean(const char* key, bool writable = true) { return SettingSpec{key, T::Bool, 0, 0, {}, writable}; }

std::string fmt(double v) { return format_g(v, 12); }
}  // namespace

const std::vector<std::string>& dut_profiles() {
  static const std::vector<std::string> v = {"NORMAL", "LOWGAIN", "HIGHTHD", "NOISY", "CLIPPING"};
  return v;
}

const std::vector<std::string>& dut_firmwares() {
  static const std::vector<std::string> v = {"1.0.0", "1.1.0", "1.2.0"};
  return v;
}

const std::vector<SettingSpec>& setting_specs(InstrumentKind kind) {
  static const std::vector<SettingSpec> siggen = {
      str("function", {"SIN", "SQU", "CHIR", "NOIS"}), num("frequency_hz", 10, 20000), num("amplitude_vpk", 0, 5),
      num("sample_rate_hz", 8000, 192000), boolean("output")};
  static const std::vector<SettingSpec> analyzer = {num("points", 1024, 65536), num("sample_rate_hz", 0, 0, false),
                                                    boolean("acquisition_stored", false)};
  static const std::vector<SettingSpec> dut = {
      str("profile", dut_profiles()), str("firmware", dut_firmwares()), num("gain_db", -20, 60), num("hpf_hz", 20, 1000),
      num("lpf_hz", 1000, 20000),     num("noise_dbv", -140, 0),         num("hd2", 0, 1),        num("hd3", 0, 1),
      num("clip_vpk", 0.01, 10)};
  switch (kind) {
    case InstrumentKind::SignalGenerator: return siggen;
    case InstrumentKind::AudioAnalyzer: return analyzer;
    case InstrumentKind::DeviceUnderTest: return dut;
  }
  return siggen;
}

void validate_settings(InstrumentKind kind, Settings& settings) {
  if (settings.empty()) throw MfError(ErrorCode::InvalidArgument, "settings must not be empty", "settings");
  const auto& specs = setting_specs(kind);
  for (auto& kv : settings) {
    const SettingSpec* spec = nullptr;
    for (const auto& s : specs) {
      if (s.key == kv.first) spec = &s;
    }
    if (!spec) throw MfError(ErrorCode::InvalidArgument, "unknown setting '" + kv.first + "' for this instrument", kv.first);
    if (!spec->writable) throw MfError(ErrorCode::InvalidArgument, "setting '" + kv.first + "' is read-only", kv.first);
    switch (spec->type) {
      case T::Number: {
        if (!is_number(kv.second)) throw MfError(ErrorCode::InvalidArgument, kv.first + " must be a number", kv.first);
        const double v = std::get<double>(kv.second);
        if (!std::isfinite(v) || v < spec->min || v > spec->max) {
          throw MfError(ErrorCode::InvalidArgument, kv.first + " must be within [" + fmt(spec->min) + ", " + fmt(spec->max) + "]", kv.first);
        }
        if (kv.first == "points") {
          const auto n = static_cast<long long>(v);
          if (static_cast<double>(n) != v || (n & (n - 1)) != 0) {
            throw MfError(ErrorCode::InvalidArgument, "points must be a power of two", kv.first);
          }
        }
        break;
      }
      case T::String: {
        if (!is_string(kv.second)) throw MfError(ErrorCode::InvalidArgument, kv.first + " must be a string", kv.first);
        std::string v = std::get<std::string>(kv.second);
        if (kv.first != "firmware") v = to_upper(v);
        bool ok = false;
        for (const auto& c : spec->choices) ok = ok || c == v;
        if (!ok) {
          std::string list;
          for (const auto& c : spec->choices) list += (list.empty() ? "" : ", ") + c;
          throw MfError(ErrorCode::InvalidArgument, kv.first + " must be one of: " + list, kv.first);
        }
        kv.second = v;
        break;
      }
      case T::Bool:
        if (!is_bool(kv.second)) throw MfError(ErrorCode::InvalidArgument, kv.first + " must be a boolean", kv.first);
        break;
    }
  }
}

}  // namespace mf
