#include "measureflow/scpi/scpi_parse.hpp"

namespace mf {

std::optional<InstrumentError> parse_error_response(const std::string& raw) {
  const std::string s = trim(raw);
  const size_t comma = s.find(',');
  if (comma == std::string::npos) return std::nullopt;
  const auto code = parse_int_strict(s.substr(0, comma), -32768, 32767);
  if (!code) return std::nullopt;
  std::string msg = trim(s.substr(comma + 1));
  if (msg.size() >= 2 && msg.front() == '"' && msg.back() == '"') {
    msg = msg.substr(1, msg.size() - 2);
  } else {
    return std::nullopt;  // message must be a quoted string
  }
  return InstrumentError{static_cast<int>(*code), msg};
}

std::optional<std::vector<ParsedNumber>> parse_number_list(const std::string& s) {
  std::vector<ParsedNumber> out;
  if (trim(s).empty()) return out;
  for (const auto& part : split(s, ',')) {
    const auto n = parse_number_strict(part);
    if (!n) return std::nullopt;
    out.push_back(*n);
  }
  return out;
}

std::vector<std::string> split_fields(const std::string& s) {
  std::vector<std::string> out;
  for (const auto& p : split(s, ',')) out.push_back(trim(p));
  return out;
}

std::optional<Idn> parse_idn(const std::string& s) {
  const auto f = split_fields(s);
  if (f.size() != 4) return std::nullopt;
  for (const auto& x : f) {
    if (x.empty()) return std::nullopt;
  }
  return Idn{f[0], f[1], f[2], f[3]};
}

std::optional<bool> parse_bool_response(const std::string& s) {
  const std::string u = to_upper(trim(s));
  if (u == "1" || u == "ON") return true;
  if (u == "0" || u == "OFF") return false;
  return std::nullopt;
}

}  // namespace mf
