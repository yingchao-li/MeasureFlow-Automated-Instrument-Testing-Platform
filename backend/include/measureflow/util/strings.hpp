// Small string helpers: strict number parsing, escaping for CSV/HTML/PDF/JSON-ish output.
#pragma once

#include <cstddef>
#include <optional>
#include <string>
#include <vector>

namespace mf {

std::string trim(const std::string& s);
std::string to_upper(std::string s);
std::string to_lower(std::string s);
bool starts_with(const std::string& s, const std::string& prefix);
bool ends_with(const std::string& s, const std::string& suffix);
std::vector<std::string> split(const std::string& s, char sep);

// printable ASCII (0x20..0x7E) only, no control characters.
bool is_printable_ascii(const std::string& s);
// ^[A-Za-z0-9._-]{1,64}$ and not "." / ".." only — safe as a file stem.
bool is_valid_id(const std::string& s);

enum class NumberClass { Finite, NaN, PosInf, NegInf };
struct ParsedNumber {
  double value = 0.0;
  NumberClass cls = NumberClass::Finite;
  bool is_finite() const { return cls == NumberClass::Finite; }
};
// Strict: whole string must be a decimal/exponent float, or NAN / INF / +INF / -INF (case-insensitive).
// Leading/trailing ASCII whitespace is tolerated, nothing else. Returns nullopt for anything else
// (empty, hex, "1,2", "1e", overflow ...).
std::optional<ParsedNumber> parse_number_strict(const std::string& s);
// Same grammar, finite values only.
std::optional<double> parse_finite_strict(const std::string& s);
// Strict integer in [lo, hi].
std::optional<long long> parse_int_strict(const std::string& s, long long lo, long long hi);

// "%.9g"-style compact formatting; non-finite values yield "NaN"/"Inf"/"-Inf".
std::string format_g(double v, int precision = 9);
// Fixed decimals.
std::string format_fixed(double v, int decimals);

// CSV field escaping (RFC 4180) plus neutralisation of spreadsheet formula injection
// (text beginning with = + - @ TAB CR gets a leading apostrophe) when `text_cell` is true.
std::string csv_escape(const std::string& s, bool text_cell = true);
// HTML text/attribute escaping.
std::string html_escape(const std::string& s);
// Truncates to at most `max_chars` bytes (UTF-8 safe) appending "..." when cut.
std::string truncate_utf8(const std::string& s, size_t max_chars);

}  // namespace mf
