#include "measureflow/util/strings.hpp"

#include <algorithm>
#include <charconv>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <limits>

namespace mf {

namespace {
bool is_space(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }

// Parse text that already matches the numeric grammar of parse_number_strict into a double.
// Returns nullopt when the value is out of range (overflow, or underflow to zero), like std::from_chars.
// Floating-point std::from_chars is missing from older libc++ (Apple clang), so there is a strtod fallback;
// compile with -DMF_FORCE_STRTOD to test the fallback on any platform.
#if defined(__cpp_lib_to_chars) && !defined(MF_FORCE_STRTOD)
std::optional<double> parse_double_text(const char* first, const char* last) {
  double v = 0.0;
  const auto res = std::from_chars(first, last, v);
  if (res.ec != std::errc() || res.ptr != last) return std::nullopt;
  return v;
}
#else
std::optional<double> parse_double_text(const char* first, const char* last) {
  const std::string text(first, last);
  errno = 0;
  char* end = nullptr;
  const double v = std::strtod(text.c_str(), &end);
  if (end != text.c_str() + text.size()) return std::nullopt;
  if (errno == ERANGE) {
    if (std::isinf(v)) return std::nullopt;  // overflow
    if (v == 0.0) {                          // underflow to zero is only an error if the mantissa is not zero
      for (const char c : text) {
        if (c == 'e' || c == 'E') break;
        if (c >= '1' && c <= '9') return std::nullopt;
      }
    }
  }
  return v;
}
#endif
}  // namespace

std::string trim(const std::string& s) {
  size_t b = 0, e = s.size();
  while (b < e && is_space(s[b])) ++b;
  while (e > b && is_space(s[e - 1])) --e;
  return s.substr(b, e - b);
}

std::string to_upper(std::string s) {
  for (char& c : s) {
    if (c >= 'a' && c <= 'z') c = static_cast<char>(c - 'a' + 'A');
  }
  return s;
}

std::string to_lower(std::string s) {
  for (char& c : s) {
    if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
  }
  return s;
}

bool starts_with(const std::string& s, const std::string& prefix) {
  return s.size() >= prefix.size() && s.compare(0, prefix.size(), prefix) == 0;
}

bool ends_with(const std::string& s, const std::string& suffix) {
  return s.size() >= suffix.size() && s.compare(s.size() - suffix.size(), suffix.size(), suffix) == 0;
}

std::vector<std::string> split(const std::string& s, char sep) {
  std::vector<std::string> out;
  size_t start = 0;
  while (true) {
    const size_t pos = s.find(sep, start);
    if (pos == std::string::npos) {
      out.push_back(s.substr(start));
      break;
    }
    out.push_back(s.substr(start, pos - start));
    start = pos + 1;
  }
  return out;
}

bool is_printable_ascii(const std::string& s) {
  return std::all_of(s.begin(), s.end(), [](char c) {
    const auto u = static_cast<unsigned char>(c);
    return u >= 0x20 && u <= 0x7E;
  });
}

bool is_valid_id(const std::string& s) {
  if (s.empty() || s.size() > 64) return false;
  if (s == "." || s == "..") return false;
  return std::all_of(s.begin(), s.end(), [](char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' ||
           c == '_' || c == '-';
  });
}

std::optional<ParsedNumber> parse_number_strict(const std::string& raw) {
  const std::string s = trim(raw);
  if (s.empty()) return std::nullopt;
  // Textual specials.
  {
    const std::string u = to_upper(s);
    if (u == "NAN" || u == "+NAN" || u == "-NAN") return ParsedNumber{std::numeric_limits<double>::quiet_NaN(), NumberClass::NaN};
    if (u == "INF" || u == "+INF" || u == "INFINITY" || u == "+INFINITY")
      return ParsedNumber{std::numeric_limits<double>::infinity(), NumberClass::PosInf};
    if (u == "-INF" || u == "-INFINITY")
      return ParsedNumber{-std::numeric_limits<double>::infinity(), NumberClass::NegInf};
  }
  // Grammar: [+-]? (digits [. digits?] | . digits) ([eE] [+-]? digits)?
  size_t i = 0;
  const size_t n = s.size();
  if (s[i] == '+' || s[i] == '-') ++i;
  size_t int_digits = 0, frac_digits = 0;
  while (i < n && s[i] >= '0' && s[i] <= '9') {
    ++i;
    ++int_digits;
  }
  if (i < n && s[i] == '.') {
    ++i;
    while (i < n && s[i] >= '0' && s[i] <= '9') {
      ++i;
      ++frac_digits;
    }
  }
  if (int_digits + frac_digits == 0) return std::nullopt;
  if (i < n && (s[i] == 'e' || s[i] == 'E')) {
    ++i;
    if (i < n && (s[i] == '+' || s[i] == '-')) ++i;
    size_t exp_digits = 0;
    while (i < n && s[i] >= '0' && s[i] <= '9') {
      ++i;
      ++exp_digits;
    }
    if (exp_digits == 0) return std::nullopt;
  }
  if (i != n) return std::nullopt;

  // std::from_chars does not accept a leading '+'.
  const char* first = s.data();
  const char* last = s.data() + s.size();
  if (*first == '+') ++first;
  const auto parsed = parse_double_text(first, last);
  if (!parsed || !std::isfinite(*parsed)) return std::nullopt;  // includes overflow
  return ParsedNumber{*parsed, NumberClass::Finite};
}

std::optional<double> parse_finite_strict(const std::string& s) {
  const auto p = parse_number_strict(s);
  if (!p || !p->is_finite()) return std::nullopt;
  return p->value;
}

std::optional<long long> parse_int_strict(const std::string& raw, long long lo, long long hi) {
  const std::string s = trim(raw);
  if (s.empty()) return std::nullopt;
  const char* first = s.data();
  const char* last = s.data() + s.size();
  if (*first == '+') ++first;
  long long v = 0;
  const auto res = std::from_chars(first, last, v);
  if (res.ec != std::errc() || res.ptr != last) return std::nullopt;
  if (v < lo || v > hi) return std::nullopt;
  return v;
}

std::string format_g(double v, int precision) {
  if (std::isnan(v)) return "NaN";
  if (std::isinf(v)) return v > 0 ? "Inf" : "-Inf";
  char buf[48];
  std::snprintf(buf, sizeof buf, "%.*g", precision, v);
  return buf;
}

std::string format_fixed(double v, int decimals) {
  if (std::isnan(v)) return "NaN";
  if (std::isinf(v)) return v > 0 ? "Inf" : "-Inf";
  char buf[64];
  std::snprintf(buf, sizeof buf, "%.*f", decimals, v);
  return buf;
}

std::string csv_escape(const std::string& s, bool text_cell) {
  std::string v = s;
  if (text_cell && !v.empty()) {
    const char c = v[0];
    if (c == '=' || c == '+' || c == '-' || c == '@' || c == '\t' || c == '\r') v.insert(v.begin(), '\'');
  }
  const bool needs_quotes = v.find_first_of(",\"\r\n") != std::string::npos;
  if (!needs_quotes) return v;
  std::string out = "\"";
  for (char c : v) {
    if (c == '"') out += '"';
    out += c;
  }
  out += '"';
  return out;
}

std::string html_escape(const std::string& s) {
  std::string out;
  out.reserve(s.size() + 8);
  for (char c : s) {
    switch (c) {
      case '&': out += "&amp;"; break;
      case '<': out += "&lt;"; break;
      case '>': out += "&gt;"; break;
      case '"': out += "&quot;"; break;
      case '\'': out += "&#39;"; break;
      default: out += c;
    }
  }
  return out;
}

std::string truncate_utf8(const std::string& s, size_t max_chars) {
  if (s.size() <= max_chars) return s;
  size_t cut = max_chars > 3 ? max_chars - 3 : max_chars;
  // do not cut in the middle of a UTF-8 sequence
  while (cut > 0 && (static_cast<unsigned char>(s[cut]) & 0xC0) == 0x80) --cut;
  return s.substr(0, cut) + (max_chars > 3 ? "..." : "");
}

}  // namespace mf
