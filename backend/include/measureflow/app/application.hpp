// Application: wires configuration, logger, instrument registry, sequence library, result store, report
// service, test runner, environment manager and the REST server. Used by main() and by the tests.
#pragma once

#include <filesystem>
#include <memory>
#include <optional>
#include <string>

#include "measureflow/api/api_server.hpp"
#include "measureflow/engine/result_store.hpp"
#include "measureflow/engine/runner.hpp"
#include "measureflow/engine/sequence.hpp"
#include "measureflow/env/environment.hpp"
#include "measureflow/instruments/registry.hpp"
#include "measureflow/report/report_service.hpp"
#include "measureflow/util/logger.hpp"

namespace mf {

struct AppOptions {
  std::filesystem::path root;  // repository root (configs/, results/, reports/, frontend/dist)
  std::string host = "127.0.0.1";
  int port = 8080;
  bool unsafe_bind = false;
  LogLevel log_level = LogLevel::Info;
  bool stderr_log = false;
  RunnerOptions runner;
  size_t max_body_bytes = 64 * 1024;
};

class Application {
 public:
  explicit Application(AppOptions options);
  ~Application();
  Application(const Application&) = delete;
  Application& operator=(const Application&) = delete;

  // Binds the REST server and serves in the background. Returns the bound port.
  int start();
  // Blocks the calling thread until shutdown() has been requested elsewhere (signal watcher).
  // Graceful shutdown: cancel the active run (cleanup executes), switch outputs off, close sockets, stop HTTP.
  void shutdown();

  Logger& logger() { return *logger_; }
  InstrumentRegistry& registry() { return *registry_; }
  TestRunner& runner() { return *runner_; }
  ResultStore& store() { return *store_; }
  ReportService& reports() { return *reports_; }
  SequenceLibrary& sequences() { return sequences_; }
  EnvironmentManager& env() { return *env_; }
  ApiServer& api() { return *api_; }
  const AppOptions& options() const { return options_; }
  const ConfigStatus& config_status() const { return config_status_; }

 private:
  AppOptions options_;
  std::unique_ptr<Logger> logger_;
  ConfigStatus config_status_;
  std::shared_ptr<CalibrationBook> calibration_;
  std::unique_ptr<InstrumentRegistry> registry_;
  SequenceLibrary sequences_;
  std::unique_ptr<ResultStore> store_;
  std::unique_ptr<ReportService> reports_;
  std::unique_ptr<TestRunner> runner_;
  std::unique_ptr<EnvironmentManager> env_;
  std::unique_ptr<ApiServer> api_;
  bool shut_down_ = false;
};

}  // namespace mf
