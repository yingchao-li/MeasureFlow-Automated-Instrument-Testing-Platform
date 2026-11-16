// Test Environment Manager: health checks, software versions, calibration validity, dependency/port checks and
// history statistics. Expensive probes (disk write, TCP probes) are cached for 2 s; in-memory facts are live.
//
// Locking: `mu_` guards the probe cache only (leaf lock, never held during probes).
#pragma once

#include <filesystem>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

#include "measureflow/engine/result_store.hpp"
#include "measureflow/engine/runner.hpp"
#include "measureflow/engine/sequence.hpp"
#include "measureflow/instruments/calibration.hpp"
#include "measureflow/instruments/registry.hpp"
#include "measureflow/util/logger.hpp"

namespace mf {

struct EnvPaths {
  std::filesystem::path root;
  std::filesystem::path instruments_json, calibration_json, sequences_dir, results_dir, reports_dir, frontend_dist;
};

struct ConfigStatus {
  std::string instruments_version = "unknown";
  bool instruments_ok = true;
  std::vector<std::string> problems;  // config/sequence/calibration warnings and errors
};

struct HealthCheck {
  std::string name;
  std::string status;  // ok | warn | fail
  std::string detail;
};

struct HealthReport {
  std::string status;  // ok | degraded | down
  std::string time;
  double uptime_s = 0;
  size_t instruments_online = 0, instruments_total = 0;
  std::optional<std::string> running_test;
  std::string backend_version, simulator_version, config_version;
  std::vector<HealthCheck> checks;
};

struct EnvironmentReport {
  std::string backend_version, simulator_version, config_version, compiler, api_version;
  std::vector<InstrumentInfo> instruments;
  std::vector<std::pair<std::string, CalibrationStatus>> calibration;
  std::vector<HealthCheck> dependencies;
  HistoryStats history;
  std::string instruments_version;
  size_t sequences = 0;
  std::vector<std::string> problems;
};

class EnvironmentManager {
 public:
  EnvironmentManager(EnvPaths paths, InstrumentRegistry& registry, ResultStore& store, const SequenceLibrary& sequences,
                     std::shared_ptr<const CalibrationBook> calibration, TestRunner& runner, Logger& logger, ConfigStatus config);

  HealthReport health();
  EnvironmentReport environment();
  static std::string compiler_string();

 private:
  struct Probes {
    bool valid = false;
    SteadyClock::time_point at{};
    bool results_writable = false, reports_writable = false;
    std::string results_detail, reports_detail;
    std::vector<HealthCheck> ports;  // simulator_<id>_port
    std::string simulator_version = "unknown";
  };
  Probes probes(bool force);
  void warn_once(const std::string& key, const std::string& message);

  EnvPaths paths_;
  InstrumentRegistry& registry_;
  ResultStore& store_;
  const SequenceLibrary& sequences_;
  std::shared_ptr<const CalibrationBook> calibration_;
  TestRunner& runner_;
  Logger& logger_;
  ConfigStatus config_;
  SteadyClock::time_point started_;

  std::mutex mu_;
  Probes cache_;
  std::vector<std::string> warned_;
};

}  // namespace mf
