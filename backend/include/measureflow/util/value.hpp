// Tiny variant used for typed instrument settings; converted to JSON in the API layer only.
#pragma once

#include <map>
#include <string>
#include <variant>

namespace mf {

using SettingValue = std::variant<bool, double, std::string>;
using Settings = std::map<std::string, SettingValue>;

inline bool is_number(const SettingValue& v) { return std::holds_alternative<double>(v); }
inline bool is_string(const SettingValue& v) { return std::holds_alternative<std::string>(v); }
inline bool is_bool(const SettingValue& v) { return std::holds_alternative<bool>(v); }

}  // namespace mf
