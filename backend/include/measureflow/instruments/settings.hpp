// Typed instrument settings: allowed keys, types and ranges (docs/INTERFACE.md sections 3 and 5.7).
#pragma once

#include <string>
#include <vector>

#include "measureflow/instruments/instrument_types.hpp"
#include "measureflow/util/value.hpp"

namespace mf {

struct SettingSpec {
  enum class Type { Number, String, Bool };
  std::string key;
  Type type;
  double min = 0;
  double max = 0;
  std::vector<std::string> choices;  // for String
  bool writable = true;
};

const std::vector<SettingSpec>& setting_specs(InstrumentKind kind);
const std::vector<std::string>& dut_profiles();
const std::vector<std::string>& dut_firmwares();

// Validates keys/types/ranges, normalises enum strings to upper case. Throws MfError(InvalidArgument)
// with `field` set to the offending key. An empty map is rejected.
void validate_settings(InstrumentKind kind, Settings& settings);

}  // namespace mf
