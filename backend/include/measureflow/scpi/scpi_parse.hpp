// Parsing helpers for SCPI responses (pure functions, unit-tested).
#pragma once

#include <optional>
#include <string>
#include <vector>

#include "measureflow/scpi/scpi_error.hpp"
#include "measureflow/util/strings.hpp"

namespace mf {

// "-222,\"Data out of range\"" -> {-222, "Data out of range"}; nullopt when malformed.
std::optional<InstrumentError> parse_error_response(const std::string& s);
// "1,2.5,-3e2" -> numbers; nullopt if any element is not a strict number (NAN/INF allowed, flagged by class).
std::optional<std::vector<ParsedNumber>> parse_number_list(const std::string& s);
// "MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0" -> 4 trimmed fields; nullopt unless exactly 4 non-empty fields.
struct Idn {
  std::string manufacturer, model, serial, firmware;
};
std::optional<Idn> parse_idn(const std::string& s);
// "1"/"0"/"ON"/"OFF" -> bool
std::optional<bool> parse_bool_response(const std::string& s);
// Splits a response on ',' and trims each field.
std::vector<std::string> split_fields(const std::string& s);

}  // namespace mf
