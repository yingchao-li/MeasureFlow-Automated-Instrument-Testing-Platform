// JSON (de)serialisation of the run data model — the exact shapes of docs/INTERFACE.md.
// This header includes json.hpp: include it only from .cpp files.
#pragma once

#include <optional>
#include <string>

#include "json.hpp"
#include "measureflow/engine/types.hpp"
#include "measureflow/util/logger.hpp"
#include "measureflow/util/value.hpp"

namespace mf {

// round to `decimals` places (JSON friendliness for durations etc.)
double round_to(double v, int decimals);

nlohmann::json settings_to_json(const Settings& s);
nlohmann::json log_entry_to_json(const LogEntry& e);
nlohmann::json task_to_json(const TaskResult& t);
nlohmann::json step_to_json(const StepRecord& s);
nlohmann::json counts_to_json(const RunCounts& c);
// Run summary (5.10 / 5.11 / 5.13 runs list).
nlohmann::json run_summary_to_json(const RunRecord& r);
// Run detail: summary + parameters + steps + tasks + last `log_tail` log entries (0 = all).
nlohmann::json run_detail_to_json(const RunRecord& r, size_t log_tail);

// Strict-ish loader used for run.json files: returns nullopt and fills `err` when the document is unusable.
std::optional<RunRecord> run_from_json(const nlohmann::json& j, std::string* err);

}  // namespace mf
