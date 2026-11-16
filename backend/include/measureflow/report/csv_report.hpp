#pragma once

#include <string>

#include "measureflow/engine/types.hpp"

namespace mf {

// Header of results.csv (docs/INTERFACE.md section 7).
const char* csv_header();
// One CSV document per run: header + one row per task (RFC 4180 quoting, formula-injection neutralised).
std::string run_to_csv(const RunRecord& run);

}  // namespace mf
