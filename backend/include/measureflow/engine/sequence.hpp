// Test sequence model, strict loader/validator, `${param}` templating and plan resolution.
#pragma once

#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "measureflow/engine/types.hpp"
#include "measureflow/instruments/adapters.hpp"
#include "measureflow/util/value.hpp"

namespace mf {

// A numeric field of a step: absent/null, a literal, or a reference "${param}".
struct NumExpr {
  enum class Kind { Null, Literal, Param };
  Kind kind = Kind::Null;
  double value = 0.0;
  std::string param;
  bool is_null() const { return kind == Kind::Null; }
  static NumExpr literal(double v) {
    NumExpr e;
    e.kind = Kind::Literal;
    e.value = v;
    return e;
  }
  static NumExpr ref(std::string name) {
    NumExpr e;
    e.kind = Kind::Param;
    e.param = std::move(name);
    return e;
  }
};

struct ParamDef {
  std::string key, label, unit;
  double def = 0, min = 0, max = 0;
};

struct LimitsDef {
  NumExpr min, max;
  std::string unit;
};

enum class StepType { Init, ConfigureSignal, ConfigureDut, Measure, Sweep, Cleanup, Report };
const char* to_string(StepType t);
std::optional<StepType> parse_step_type(const std::string& s);

struct StepDef {
  std::string id;
  std::string name;  // may contain ${param} substrings
  StepType type = StepType::Init;
  // init
  std::vector<std::string> instruments;
  // configure_signal
  std::string function = "SIN";
  NumExpr frequency_hz, amplitude_vpk, sample_rate_hz, settle_ms;
  bool output = false;
  // configure_dut
  std::map<std::string, NumExpr> dut_numeric;
  std::map<std::string, std::string> dut_text;
  // measure / sweep
  Measurement measurement = Measurement::Rms;
  LimitsDef limits;
  std::vector<NumExpr> points_hz;
};

struct SequenceDef {
  std::string id, name, version, description;
  DutSelection dut;
  std::vector<ParamDef> parameters;
  std::vector<StepDef> steps;
  const ParamDef* find_param(const std::string& key) const;
};

// Parses and validates one sequence document. Throws MfError(InvalidArgument) naming the offending path.
SequenceDef parse_sequence(const std::string& json_text, const std::string& origin);

class SequenceLibrary {
 public:
  // Loads every *.json in `dir`. Invalid files are skipped and reported through errors().
  void load_directory(const std::filesystem::path& dir);
  void add(SequenceDef def);
  const SequenceDef* find(const std::string& id) const;
  std::vector<const SequenceDef*> list() const;  // sorted by id
  const std::vector<std::string>& errors() const { return errors_; }
  size_t size() const { return by_id_.size(); }

 private:
  std::map<std::string, SequenceDef> by_id_;
  std::vector<std::string> errors_;
};

// ---- run-time resolution ------------------------------------------------------------------------

// Defaults overlaid with `overrides`; unknown keys / out-of-range / non-finite -> MfError(InvalidArgument).
std::map<std::string, double> resolve_parameters(const SequenceDef& seq, const std::map<std::string, double>& overrides);
// Replaces every "${key}" inside `text` with the value formatted compactly; unknown keys are left untouched.
std::string render_template(const std::string& text, const std::map<std::string, double>& params);

struct ResolvedStep {
  const StepDef* def = nullptr;
  std::string name;
  Settings signal;       // configure_signal: function, frequency_hz, amplitude_vpk, [sample_rate_hz], output
  int settle_ms = 0;
  Settings dut;          // configure_dut settings (applied after profile/firmware)
  Limits limits;         // measure / sweep
  std::vector<double> points_hz;
  double sweep_amplitude_vpk = 0;
};

struct ResolvedPlan {
  std::vector<ResolvedStep> steps;
  int planned_tasks = 0;       // measurement tasks
  int planned_units = 0;       // tasks + non-measure steps (denominator of progress)
};

// Resolves and validates every step value against the instrument ranges. Throws MfError(InvalidArgument).
ResolvedPlan build_plan(const SequenceDef& seq, const std::map<std::string, double>& params);

}  // namespace mf
