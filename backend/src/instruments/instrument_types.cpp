#include "measureflow/instruments/instrument_types.hpp"

#include <set>

#include "json.hpp"
#include "measureflow/util/errors.hpp"
#include "measureflow/util/fs.hpp"
#include "measureflow/util/strings.hpp"

namespace mf {

const char* to_string(InstrumentKind kind) {
  switch (kind) {
    case InstrumentKind::SignalGenerator: return "signal_generator";
    case InstrumentKind::AudioAnalyzer: return "audio_analyzer";
    case InstrumentKind::DeviceUnderTest: return "device_under_test";
  }
  return "unknown";
}

const char* to_string(InstrumentState state) {
  switch (state) {
    case InstrumentState::Disconnected: return "disconnected";
    case InstrumentState::Connecting: return "connecting";
    case InstrumentState::Connected: return "connected";
    case InstrumentState::Error: return "error";
  }
  return "disconnected";
}

std::optional<InstrumentKind> parse_instrument_kind(const std::string& s) {
  if (s == "signal_generator") return InstrumentKind::SignalGenerator;
  if (s == "audio_analyzer") return InstrumentKind::AudioAnalyzer;
  if (s == "device_under_test") return InstrumentKind::DeviceUnderTest;
  return std::nullopt;
}

bool is_loopback_host(const std::string& host) {
  const std::string h = to_lower(trim(host));
  if (h == "localhost" || h == "::1" || h == "[::1]") return true;
  // 127.0.0.0/8 literal, strictly dotted-quad
  const auto parts = split(h, '.');
  if (parts.size() != 4) return false;
  for (size_t i = 0; i < 4; ++i) {
    const auto v = parse_int_strict(parts[i], 0, 255);
    if (!v) return false;
    if (parts[i].size() > 3 || (parts[i].size() > 1 && parts[i][0] == '0')) return false;
    if (i == 0 && *v != 127) return false;
  }
  return true;
}

void require_loopback(const std::string& host) {
  if (!is_loopback_host(host)) {
    throw MfError(ErrorCode::ForbiddenHost, "host '" + host + "' is not a loopback address; only 127.0.0.1, localhost and ::1 are allowed",
                  "host");
  }
}

namespace {
[[noreturn]] void bad(const std::string& path, const std::string& msg) {
  throw MfError(ErrorCode::InvalidArgument, path + ": " + msg);
}

int get_int(const nlohmann::json& o, const char* key, int def, int lo, int hi, const std::string& where) {
  if (!o.contains(key)) return def;
  const auto& v = o.at(key);
  if (!v.is_number_integer()) bad(where, std::string(key) + " must be an integer");
  const long long x = v.get<long long>();
  if (x < lo || x > hi) bad(where, std::string(key) + " must be within [" + std::to_string(lo) + ", " + std::to_string(hi) + "]");
  return static_cast<int>(x);
}
}  // namespace

InstrumentsFile load_instruments_file(const std::filesystem::path& path) {
  const auto text = read_file(path, 1u << 20);
  if (!text) bad(path.string(), "cannot read file");
  nlohmann::json j = nlohmann::json::parse(*text, nullptr, false);
  if (j.is_discarded() || !j.is_object()) bad(path.string(), "not a valid JSON object");
  InstrumentsFile out;
  if (j.contains("config_version")) {
    if (!j["config_version"].is_string()) bad(path.string(), "config_version must be a string");
    out.config_version = j["config_version"].get<std::string>();
  }
  if (j.contains("max_response_bytes")) {
    out.max_response_bytes = static_cast<size_t>(get_int(j, "max_response_bytes", 1048576, 1024, 64 * 1024 * 1024, path.string()));
  }
  if (!j.contains("instruments") || !j["instruments"].is_array()) bad(path.string(), "'instruments' must be an array");
  std::set<std::string> seen;
  int idx = 0;
  for (const auto& e : j["instruments"]) {
    const std::string where = path.string() + " instruments[" + std::to_string(idx++) + "]";
    if (!e.is_object()) bad(where, "must be an object");
    InstrumentConfig c;
    if (!e.contains("id") || !e["id"].is_string() || !is_valid_id(e["id"].get<std::string>())) bad(where, "id must match [A-Za-z0-9._-]{1,64}");
    c.id = e["id"].get<std::string>();
    if (!seen.insert(c.id).second) bad(where, "duplicate id '" + c.id + "'");
    c.name = e.contains("name") && e["name"].is_string() ? e["name"].get<std::string>() : c.id;
    const auto kind = e.contains("kind") && e["kind"].is_string() ? parse_instrument_kind(e["kind"].get<std::string>()) : std::nullopt;
    if (!kind) bad(where, "kind must be signal_generator | audio_analyzer | device_under_test");
    c.kind = *kind;
    if (e.contains("host")) {
      if (!e["host"].is_string()) bad(where, "host must be a string");
      c.host = e["host"].get<std::string>();
    }
    if (!is_loopback_host(c.host)) bad(where, "host '" + c.host + "' is not loopback (FORBIDDEN_HOST)");
    c.port = static_cast<uint16_t>(get_int(e, "port", 0, 1, 65535, where));
    if (!e.contains("port")) bad(where, "port is required");
    c.timeout_ms = get_int(e, "timeout_ms", 1000, 20, 120000, where);
    c.connect_timeout_ms = get_int(e, "connect_timeout_ms", 500, 20, 60000, where);
    c.max_retries = get_int(e, "max_retries", 2, 0, 10, where);
    out.instruments.push_back(std::move(c));
  }
  return out;
}

}  // namespace mf
