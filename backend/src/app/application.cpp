#include "measureflow/app/application.hpp"

#include "measureflow/util/errors.hpp"
#include "measureflow/util/fs.hpp"

namespace mf {

Application::Application(AppOptions options) : options_(std::move(options)) {
  namespace fs = std::filesystem;
  const fs::path root = options_.root;
  logger_ = std::make_unique<Logger>(5000);
  logger_->set_min_level(options_.log_level);
  logger_->set_stderr_echo(options_.stderr_log);
  ensure_dir(root / "results");
  ensure_dir(root / "reports");
  if (!logger_->open_file(root / "results" / "logs" / "measureflow.jsonl")) {
    logger_->warn("system", "cannot open the log file under results/logs; logging to memory only");
  }
  logger_->info("system", std::string("MeasureFlow backend ") + MF_VERSION + " starting", {{"root", root.string()}});

  // ---- configuration -------------------------------------------------------------------------
  InstrumentsFile instruments;
  try {
    instruments = load_instruments_file(root / "configs" / "instruments.json");
    config_status_.instruments_version = instruments.config_version;
    logger_->info("system", "loaded " + std::to_string(instruments.instruments.size()) + " instrument definition(s)",
                  {{"config_version", instruments.config_version}});
  } catch (const MfError& e) {
    config_status_.instruments_ok = false;
    config_status_.problems.push_back(e.what());
    logger_->error("system", std::string("instrument configuration unusable: ") + e.what());
  }
  calibration_ = std::make_shared<CalibrationBook>(CalibrationBook::load(root / "configs" / "calibration.json"));
  for (const auto& w : calibration_->warnings()) {
    config_status_.problems.push_back(w);
    logger_->warn("system", w);
  }
  sequences_.load_directory(root / "configs" / "sequences");
  for (const auto& e : sequences_.errors()) {
    config_status_.problems.push_back(e);
    logger_->error("system", "sequence skipped: " + e);
  }
  logger_->info("system", "loaded " + std::to_string(sequences_.size()) + " sequence(s)");

  // ---- services --------------------------------------------------------------------------------
  registry_ = std::make_unique<InstrumentRegistry>(std::move(instruments), *logger_, calibration_);
  store_ = std::make_unique<ResultStore>(root, logger_.get());
  const IndexReport idx = store_->rebuild_index();
  logger_->info("system", "result history: " + std::to_string(idx.loaded) + " run(s) indexed, " + std::to_string(idx.corrupt) + " corrupt file(s) skipped",
                {{"recovered_interrupted", static_cast<int64_t>(idx.recovered_interrupted)}});
  reports_ = std::make_unique<ReportService>(root, *store_, logger_.get());
  runner_ = std::make_unique<TestRunner>(*registry_, sequences_, *store_, *reports_, *logger_, options_.runner);

  EnvPaths paths;
  paths.root = root;
  paths.instruments_json = root / "configs" / "instruments.json";
  paths.calibration_json = root / "configs" / "calibration.json";
  paths.sequences_dir = root / "configs" / "sequences";
  paths.results_dir = root / "results";
  paths.reports_dir = root / "reports";
  paths.frontend_dist = root / "frontend" / "dist";
  env_ = std::make_unique<EnvironmentManager>(paths, *registry_, *store_, sequences_, calibration_, *runner_, *logger_, config_status_);

  AppServices svc{*logger_, *registry_, sequences_, *store_, *reports_, *runner_, *env_};
  ApiOptions ao;
  ao.host = options_.host;
  ao.port = options_.port;
  ao.unsafe_bind = options_.unsafe_bind;
  ao.max_body_bytes = options_.max_body_bytes;
  ao.frontend_dist = paths.frontend_dist;
  api_ = std::make_unique<ApiServer>(svc, ao);
}

Application::~Application() { shutdown(); }

int Application::start() {
  const int port = api_->start_in_background();
  logger_->info("system", "REST API listening on http://" + options_.host + ":" + std::to_string(port),
                {{"port", static_cast<int64_t>(port)}, {"unsafe_bind", options_.unsafe_bind}});
  const HealthReport h = env_->health();  // emits calibration warnings once
  logger_->info("system", "environment status: " + h.status);
  return port;
}

void Application::shutdown() {
  if (shut_down_) return;
  shut_down_ = true;
  logger_->info("system", "shutting down");
  runner_->shutdown();    // cancels the active run; cleanup (output OFF, lease release) executes
  api_->stop();           // no new requests
  registry_->shutdown();  // outputs off, sockets closed
  logger_->info("system", "shutdown complete");
}

}  // namespace mf
