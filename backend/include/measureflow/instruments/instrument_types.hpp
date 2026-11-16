#pragma once

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace mf {

enum class InstrumentKind { SignalGenerator, AudioAnalyzer, DeviceUnderTest };
enum class InstrumentState { Disconnected, Connecting, Connected, Error };

const char* to_string(InstrumentKind kind);
const char* to_string(InstrumentState state);
std::optional<InstrumentKind> parse_instrument_kind(const std::string& s);

struct InstrumentConfig {
  std::string id;
  std::string name;
  InstrumentKind kind = InstrumentKind::SignalGenerator;
  std::string host = "127.0.0.1";
  uint16_t port = 0;
  int timeout_ms = 1000;
  int connect_timeout_ms = 500;
  int max_retries = 2;
};

struct InstrumentsFile {
  std::string config_version = "0.0.0";
  size_t max_response_bytes = 1048576;
  std::vector<InstrumentConfig> instruments;
};

// Loopback-only policy: 127.0.0.1 / localhost / ::1 (and the rest of 127.0.0.0/8).
bool is_loopback_host(const std::string& host);
// Throws MfError(ForbiddenHost) otherwise.
void require_loopback(const std::string& host);

// Strict loader. Throws MfError(InvalidArgument) with a precise message on any problem
// (unreadable file, wrong types, ranges, duplicate ids, non-loopback host ...).
InstrumentsFile load_instruments_file(const std::filesystem::path& path);

}  // namespace mf
