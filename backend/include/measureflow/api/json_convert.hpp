#pragma once

#include "json.hpp"
#include "measureflow/engine/statistics.hpp"
#include "measureflow/env/environment.hpp"
#include "measureflow/instruments/registry.hpp"

namespace mf {

nlohmann::json instrument_to_json(const InstrumentInfo& i);
nlohmann::json health_to_json(const HealthReport& h);
nlohmann::json environment_to_json(const EnvironmentReport& e);
nlohmann::json summary_to_json(const SummaryReport& s);
// Number rendering shared by the API: NaN/Inf become null.
nlohmann::json finite_or_null(double v);

}  // namespace mf
