#include "measureflow/env/environment.hpp"

#include <algorithm>

#include "measureflow/scpi/scpi_client.hpp"
#include "measureflow/util/fs.hpp"
#include "measureflow/util/strings.hpp"
#include "measureflow/util/time.hpp"

namespace mf {

namespace {
constexpr int kProbeCacheMs = 2000;
constexpr int kProbeTimeoutMs = 200;
}  // namespace

EnvironmentManager::EnvironmentManager(EnvPaths paths, InstrumentRegistry& registry, ResultStore& store, const SequenceLibrary& sequences,
                                       std::shared_ptr<const CalibrationBook> calibration, TestRunner& runner, Logger& logger,
                                       ConfigStatus config)
    : paths_(std::move(paths)),
      registry_(registry),
      store_(store),
      sequences_(sequences),
      calibration_(std::move(calibration)),
      runner_(runner),
      logger_(logger),
      config_(std::move(config)),
      started_(SteadyClock::now()) {
  if (!calibration_) calibration_ = std::make_shared<CalibrationBook>();
}

std::string EnvironmentManager::compiler_string() {
#if defined(__clang__)
  return "Clang " + std::to_string(__clang_major__) + "." + std::to_string(__clang_minor__) + "." + std::to_string(__clang_patchlevel__);
#elif defined(__GNUC__)
  return "GNU " + std::to_string(__GNUC__) + "." + std::to_string(__GNUC_MINOR__) + "." + std::to_string(__GNUC_PATCHLEVEL__);
#else
  return "unknown";
#endif
}

void EnvironmentManager::warn_once(const std::string& key, const std::string& message) {
  {
    std::lock_guard<std::mutex> lock(mu_);
    if (std::find(warned_.begin(), warned_.end(), key) != warned_.end()) return;
    warned_.push_back(key);
  }
  logger_.warn("env", message);
}

EnvironmentManager::Probes EnvironmentManager::probes(bool force) {
  {
    std::lock_guard<std::mutex> lock(mu_);
    if (!force && cache_.valid &&
        std::chrono::duration_cast<std::chrono::milliseconds>(SteadyClock::now() - cache_.at).count() < kProbeCacheMs) {
      return cache_;
    }
  }
  Probes p;
  p.results_writable = dir_writable(paths_.results_dir);
  p.results_detail = paths_.results_dir.string() + (p.results_writable ? " is writable" : " is not writable");
  p.reports_writable = dir_writable(paths_.reports_dir);
  p.reports_detail = paths_.reports_dir.string() + (p.reports_writable ? " is writable" : " is not writable");
  bool first = true;
  for (const auto& id : registry_.ids()) {
    const InstrumentInfo info = registry_.info(id);
    HealthCheck c;
    c.name = "simulator_" + id + "_port";
    std::string detail;
    const bool ok = probe_tcp(info.host, info.port, kProbeTimeoutMs, &detail);
    c.status = ok ? "ok" : "fail";
    c.detail = ok ? (info.host + ":" + std::to_string(info.port) + " reachable") : (info.host + ":" + std::to_string(info.port) + " not reachable (" + detail + ")");
    p.ports.push_back(c);
    if (ok && first) {
      std::string ver;
      if (probe_query(info.host, info.port, "MF:SIM:VERS?", 300, &ver) && !ver.empty()) p.simulator_version = trim(ver);
      first = false;
    }
  }
  p.valid = true;
  p.at = SteadyClock::now();
  std::lock_guard<std::mutex> lock(mu_);
  cache_ = p;
  return p;
}

HealthReport EnvironmentManager::health() {
  HealthReport h;
  h.time = iso_now();
  h.uptime_s = std::chrono::duration<double>(SteadyClock::now() - started_).count();
  h.backend_version = MF_VERSION;
  h.config_version = config_.instruments_version;
  h.running_test = runner_.active_run_id();
  const auto infos = registry_.list();
  h.instruments_total = infos.size();
  const Probes p = probes(false);
  h.simulator_version = p.simulator_version;

  h.checks.push_back({"results_dir_writable", p.results_writable ? "ok" : "fail", p.results_detail});
  h.checks.push_back({"reports_dir_writable", p.reports_writable ? "ok" : "warn", p.reports_detail});
  {
    HealthCheck c{"configs_readable", "ok", "instruments.json and " + std::to_string(sequences_.size()) + " sequence(s) loaded"};
    if (!config_.instruments_ok) {
      c.status = "fail";
      c.detail = config_.problems.empty() ? "instruments.json unreadable" : config_.problems.front();
    } else if (!config_.problems.empty()) {
      c.status = "warn";
      c.detail = config_.problems.front() + (config_.problems.size() > 1 ? " (+" + std::to_string(config_.problems.size() - 1) + " more)" : "");
    }
    h.checks.push_back(c);
  }
  bool any_port_down = false;
  for (const auto& c : p.ports) any_port_down = any_port_down || c.status != "ok";
  if (!p.ports.empty()) {
    HealthCheck c{"simulator_reachable", any_port_down ? "warn" : "ok", {}};
    if (any_port_down) {
      for (const auto& pc : p.ports) {
        if (pc.status != "ok") c.detail += (c.detail.empty() ? "" : "; ") + pc.detail;
      }
    } else {
      c.detail = "all instrument ports reachable";
    }
    h.checks.push_back(c);
  }
  const int64_t today = today_days();
  for (const auto& i : infos) {
    if (i.state == InstrumentState::Connected) ++h.instruments_online;
    HealthCheck c{"instrument_" + i.id, i.state == InstrumentState::Connected ? "ok" : "warn", std::string(to_string(i.state))};
    if (i.state != InstrumentState::Connected && !i.last_error.empty()) c.detail += ": " + i.last_error;
    h.checks.push_back(c);
    const CalibrationStatus cs = calibration_->status_for(i.id, today);
    if (cs.status != "none") {
      HealthCheck cc{"calibration_" + i.id, cs.status == "valid" ? "ok" : "warn", {}};
      cc.detail = cs.status + ", due " + cs.due + " (" + std::to_string(cs.days_remaining.value_or(0)) + " days remaining)";
      h.checks.push_back(cc);
      if (cs.status == "expired") warn_once("cal-expired-" + i.id, "calibration of instrument '" + i.id + "' expired on " + cs.due);
      else if (cs.status == "due_soon") warn_once("cal-due-" + i.id, "calibration of instrument '" + i.id + "' is due on " + cs.due);
    }
  }
  bool any_fail = false, any_warn = false;
  for (const auto& c : h.checks) {
    any_fail = any_fail || c.status == "fail";
    any_warn = any_warn || c.status == "warn";
  }
  h.status = any_fail ? "down" : (any_warn ? "degraded" : "ok");
  return h;
}

EnvironmentReport EnvironmentManager::environment() {
  EnvironmentReport r;
  const Probes p = probes(true);
  r.backend_version = MF_VERSION;
  r.simulator_version = p.simulator_version;
  r.config_version = config_.instruments_version;
  r.compiler = compiler_string();
  r.api_version = "1.0";
  r.instruments = registry_.list();
  const int64_t today = today_days();
  for (const auto& i : r.instruments) {
    const CalibrationStatus cs = calibration_->status_for(i.id, today);
    if (cs.status != "none") r.calibration.emplace_back(i.id, cs);
  }
  for (const auto& c : p.ports) r.dependencies.push_back(c);
  r.dependencies.push_back({"results_dir_writable", p.results_writable ? "ok" : "fail", p.results_detail});
  r.dependencies.push_back({"reports_dir_writable", p.reports_writable ? "ok" : "fail", p.reports_detail});
  std::error_code ec;
  const bool dist = std::filesystem::is_regular_file(paths_.frontend_dist / "index.html", ec);
  r.dependencies.push_back({"frontend_dist", dist ? "ok" : "warn",
                            dist ? paths_.frontend_dist.string() + " present" : paths_.frontend_dist.string() + " not built (run 'npm run build' in frontend/)"});
  r.dependencies.push_back({"configs", config_.instruments_ok ? (config_.problems.empty() ? "ok" : "warn") : "fail",
                            config_.problems.empty() ? "configuration loaded" : config_.problems.front()});
  r.history = store_.history();
  r.instruments_version = config_.instruments_version;
  r.sequences = sequences_.size();
  r.problems = config_.problems;
  return r;
}

}  // namespace mf
