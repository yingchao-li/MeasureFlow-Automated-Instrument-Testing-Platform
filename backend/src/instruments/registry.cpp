#include "measureflow/instruments/registry.hpp"

#include <algorithm>
#include <chrono>

#include "measureflow/util/errors.hpp"
#include "measureflow/util/strings.hpp"

namespace mf {

// ------------------------------------------------------------------ Lease
Lease::~Lease() { release(); }

Lease::Lease(Lease&& other) noexcept : reg_(other.reg_), ids_(std::move(other.ids_)), owner_(std::move(other.owner_)) {
  other.reg_ = nullptr;
  other.ids_.clear();
}

Lease& Lease::operator=(Lease&& other) noexcept {
  if (this != &other) {
    release();
    reg_ = other.reg_;
    ids_ = std::move(other.ids_);
    owner_ = std::move(other.owner_);
    other.reg_ = nullptr;
    other.ids_.clear();
  }
  return *this;
}

void Lease::release() {
  if (!reg_) return;
  InstrumentRegistry* r = reg_;
  reg_ = nullptr;
  r->release_lease(ids_);
  ids_.clear();
}

void Lease::check_member(const std::string& id) const {
  if (!reg_ || std::find(ids_.begin(), ids_.end(), id) == ids_.end()) {
    throw MfError(ErrorCode::Internal, "instrument '" + id + "' is not part of this lease");
  }
}

InstrumentAdapter& Lease::adapter(const std::string& id) const {
  check_member(id);
  return *reg_->find_entry(id)->adapter;
}

ScpiClient& Lease::client(const std::string& id) const {
  check_member(id);
  return *reg_->find_entry(id)->client;
}

InstrumentKind Lease::kind_of(const std::string& id) const {
  check_member(id);
  return reg_->find_entry(id)->cfg.kind;
}

namespace {
template <typename A>
A& typed(const Lease& l, InstrumentKind kind, const char* what) {
  for (const auto& id : l.ids()) {
    if (l.kind_of(id) == kind) return static_cast<A&>(l.adapter(id));
  }
  throw MfError(ErrorCode::NotFound, std::string("no ") + what + " instrument available", "id");
}
}  // namespace

SignalGeneratorAdapter& Lease::siggen() const { return typed<SignalGeneratorAdapter>(*this, InstrumentKind::SignalGenerator, "signal generator"); }
AudioAnalyzerAdapter& Lease::analyzer() const { return typed<AudioAnalyzerAdapter>(*this, InstrumentKind::AudioAnalyzer, "audio analyzer"); }
DutAdapter& Lease::dut() const { return typed<DutAdapter>(*this, InstrumentKind::DeviceUnderTest, "device under test"); }

InstrumentInfo Lease::connect(const std::string& id, const std::optional<std::string>& host,
                              const std::optional<uint16_t>& port) const {
  check_member(id);
  return reg_->connect_entry(*reg_->find_entry(id), host, port);
}

void Lease::refresh_settings(const std::string& id, const CallOptions& opts) const {
  check_member(id);
  auto* e = reg_->find_entry(id);
  reg_->store_settings(*e, e->adapter->read_settings(opts));
}

void Lease::detach_cancel() const {
  if (!reg_) return;
  for (const auto& id : ids_) reg_->find_entry(id)->client->set_cancel_flag(nullptr);
}

// ------------------------------------------------------------------ Registry
InstrumentRegistry::InstrumentRegistry(InstrumentsFile file, Logger& logger, std::shared_ptr<const CalibrationBook> calibration)
    : logger_(logger), calibration_(std::move(calibration)), config_version_(file.config_version) {
  if (!calibration_) calibration_ = std::make_shared<CalibrationBook>();
  for (auto& cfg : file.instruments) {
    auto e = std::make_unique<Entry>();
    e->cfg = cfg;
    ScpiConfig sc;
    sc.id = cfg.id;
    sc.host = cfg.host;
    sc.port = cfg.port;
    sc.timeout_ms = cfg.timeout_ms;
    sc.connect_timeout_ms = cfg.connect_timeout_ms;
    sc.max_retries = cfg.max_retries;
    sc.max_response_bytes = file.max_response_bytes;
    Entry* raw = e.get();
    e->client = std::make_unique<ScpiClient>(sc, [this, raw](const CommEvent& ev) { on_comm(*raw, ev); });
    switch (cfg.kind) {
      case InstrumentKind::SignalGenerator: e->adapter = std::make_unique<SignalGeneratorAdapter>(*e->client); break;
      case InstrumentKind::AudioAnalyzer: e->adapter = std::make_unique<AudioAnalyzerAdapter>(*e->client); break;
      case InstrumentKind::DeviceUnderTest: e->adapter = std::make_unique<DutAdapter>(*e->client); break;
    }
    entries_[cfg.id] = std::move(e);
  }
}

InstrumentRegistry::~InstrumentRegistry() { shutdown(); }

InstrumentRegistry::Entry* InstrumentRegistry::find_entry(const std::string& id) const {
  // entries_ is never modified after construction -> safe without the lock
  const auto it = entries_.find(id);
  if (it == entries_.end()) throw MfError(ErrorCode::NotFound, "unknown instrument '" + id + "'", "id");
  return it->second.get();
}

std::vector<std::string> InstrumentRegistry::ids() const {
  std::vector<std::string> out;
  for (const auto& kv : entries_) out.push_back(kv.first);
  return out;
}

bool InstrumentRegistry::contains(const std::string& id) const { return entries_.count(id) != 0; }

InstrumentKind InstrumentRegistry::kind_of(const std::string& id) const { return find_entry(id)->cfg.kind; }

InstrumentInfo InstrumentRegistry::snapshot_locked(const Entry& e) const {
  InstrumentInfo i;
  i.id = e.cfg.id;
  i.name = e.cfg.name;
  i.kind = e.cfg.kind;
  i.host = e.cfg.host;
  i.port = e.cfg.port;
  i.state = e.state;
  i.idn = e.idn;
  i.firmware = e.firmware;
  i.last_error = e.last_error;
  i.last_seen = e.last_seen;
  i.latency_ms = e.latency_ms;
  if (e.leased && e.lease_is_run) i.leased_by = e.lease_owner;
  i.calibration = calibration_->status_for(e.cfg.id, today_days());
  if (e.state == InstrumentState::Connected) i.settings = e.settings;
  return i;
}

InstrumentInfo InstrumentRegistry::info(const std::string& id) const {
  const Entry* e = find_entry(id);
  std::lock_guard<std::mutex> lock(mu_);
  return snapshot_locked(*e);
}

std::vector<InstrumentInfo> InstrumentRegistry::list() const {
  std::lock_guard<std::mutex> lock(mu_);
  std::vector<InstrumentInfo> out;
  for (const auto& kv : entries_) out.push_back(snapshot_locked(*kv.second));
  return out;
}

size_t InstrumentRegistry::connected_count() const {
  std::lock_guard<std::mutex> lock(mu_);
  size_t n = 0;
  for (const auto& kv : entries_) n += kv.second->state == InstrumentState::Connected ? 1 : 0;
  return n;
}

std::optional<std::string> InstrumentRegistry::run_leasing() const {
  std::lock_guard<std::mutex> lock(mu_);
  for (const auto& kv : entries_) {
    if (kv.second->leased && kv.second->lease_is_run) return kv.second->lease_owner;
  }
  return std::nullopt;
}

ScpiStats InstrumentRegistry::client_stats(const std::string& id) const { return find_entry(id)->client->stats(); }

void InstrumentRegistry::store_settings(Entry& e, Settings s) {
  std::lock_guard<std::mutex> lock(mu_);
  e.settings = std::move(s);
  e.settings_at = SteadyClock::now();
}

void InstrumentRegistry::on_comm(Entry& e, const CommEvent& ev) {
  std::string run_id;
  {
    std::lock_guard<std::mutex> lock(mu_);
    if (e.leased && e.lease_is_run) run_id = e.lease_owner;
    switch (ev.type) {
      case CommEvent::Type::Rx:
        e.last_seen = iso_now();
        e.latency_ms = ev.duration_ms;
        if (e.state == InstrumentState::Error) {
          e.state = InstrumentState::Connected;  // automatic recovery after reconnect
          e.last_error.clear();
        }
        break;
      case CommEvent::Type::Error:
        if (is_communication_kind(ev.kind) && e.state == InstrumentState::Connected) {
          e.state = InstrumentState::Error;
          e.last_error = ev.text;
        }
        break;
      default: break;
    }
  }
  const std::string& inst = e.cfg.id;
  switch (ev.type) {
    case CommEvent::Type::Tx:
    case CommEvent::Type::Rx: {
      const bool tx = ev.type == CommEvent::Type::Tx;
      LogFields f{{"instrument", inst}, {"direction", tx ? "TX" : "RX"}, {"text", ev.text}, {"duration_ms", ev.duration_ms}};
      logger_.log(ev.quiet ? LogLevel::Debug : LogLevel::Info, "scpi", inst + (tx ? " TX " : " RX ") + ev.text, std::move(f), run_id);
      break;
    }
    case CommEvent::Type::Error: {
      LogFields f{{"instrument", inst}, {"kind", to_string(ev.kind)}};
      logger_.log(ev.kind == ScpiErrorKind::Cancelled ? LogLevel::Info : (ev.quiet ? LogLevel::Warn : LogLevel::Error), "scpi",
                  inst + ": " + ev.text, std::move(f), run_id);
      break;
    }
    case CommEvent::Type::Retry:
      logger_.log(LogLevel::Warn, "scpi", inst + ": retry " + std::to_string(ev.attempt) + " of '" + ev.text + "' after " + to_string(ev.kind),
                  {{"instrument", inst}, {"kind", to_string(ev.kind)}, {"attempt", static_cast<int64_t>(ev.attempt)}}, run_id);
      break;
    case CommEvent::Type::Connect:
      logger_.log(ev.quiet ? LogLevel::Debug : LogLevel::Info, "scpi", inst + ": connected to " + ev.text,
                  {{"instrument", inst}, {"duration_ms", ev.duration_ms}}, run_id);
      break;
    case CommEvent::Type::Disconnect:
      logger_.log(LogLevel::Info, "scpi", inst + ": connection closed", {{"instrument", inst}}, run_id);
      break;
  }
}

// ---------------------------------------------------------------- leasing
Lease InstrumentRegistry::acquire(const std::vector<std::string>& ids_in, const std::string& owner, LeaseKind kind,
                                  const std::atomic<bool>* cancel, int wait_ms) {
  std::vector<std::string> ids = ids_in;
  std::sort(ids.begin(), ids.end());
  ids.erase(std::unique(ids.begin(), ids.end()), ids.end());
  std::vector<Entry*> entries;
  for (const auto& id : ids) entries.push_back(find_entry(id));

  std::unique_lock<std::mutex> lock(mu_);
  const auto deadline = SteadyClock::now() + std::chrono::milliseconds(std::max(wait_ms, 0));
  while (true) {
    const Entry* blocker = nullptr;
    for (const Entry* e : entries) {
      if (e->leased) {
        blocker = e;
        break;
      }
    }
    if (!blocker) break;
    if (blocker->lease_is_run) {
      throw MfError(ErrorCode::InstrumentBusy, "instrument '" + blocker->cfg.id + "' is in use by run " + blocker->lease_owner, "id");
    }
    if (cv_.wait_until(lock, deadline) == std::cv_status::timeout && SteadyClock::now() >= deadline) {
      throw MfError(ErrorCode::InstrumentBusy, "instrument '" + blocker->cfg.id + "' is busy", "id");
    }
  }
  for (Entry* e : entries) {
    e->leased = true;
    e->lease_is_run = kind == LeaseKind::Run;
    e->lease_owner = owner;
  }
  lock.unlock();
  for (Entry* e : entries) e->client->set_cancel_flag(cancel);
  return Lease(this, std::move(ids), owner);
}

Lease InstrumentRegistry::acquire_all(const std::string& owner, LeaseKind kind, const std::atomic<bool>* cancel, int wait_ms) {
  return acquire(this->ids(), owner, kind, cancel, wait_ms);
}

void InstrumentRegistry::release_lease(const std::vector<std::string>& ids) {
  for (const auto& id : ids) find_entry(id)->client->set_cancel_flag(nullptr);
  {
    std::lock_guard<std::mutex> lock(mu_);
    for (const auto& id : ids) {
      Entry* e = find_entry(id);
      e->leased = false;
      e->lease_is_run = false;
      e->lease_owner.clear();
    }
  }
  cv_.notify_all();
}

// ---------------------------------------------------------------- connect / disconnect
InstrumentInfo InstrumentRegistry::connect_entry(Entry& e, const std::optional<std::string>& host,
                                                 const std::optional<uint16_t>& port) {
  if (host) require_loopback(*host);
  {
    std::lock_guard<std::mutex> lock(mu_);
    e.state = InstrumentState::Connecting;
    if (host) e.cfg.host = *host;
    if (port) e.cfg.port = *port;
  }
  if (host || port) e.client->set_endpoint(e.cfg.host, e.cfg.port);
  try {
    e.client->disconnect();
    e.client->connect();
    const Idn idn = e.adapter->identify();
    if (idn.manufacturer != "MeasureFlow") {
      logger_.warn("scpi", e.cfg.id + ": unexpected manufacturer '" + idn.manufacturer + "' in *IDN?", {{"instrument", e.cfg.id}});
    }
    Settings settings = e.adapter->read_settings();
    std::lock_guard<std::mutex> lock(mu_);
    e.state = InstrumentState::Connected;
    e.idn = idn.manufacturer + "," + idn.model + "," + idn.serial + "," + idn.firmware;
    e.firmware = idn.firmware;
    e.last_error.clear();
    e.last_seen = iso_now();
    e.settings = std::move(settings);
    e.settings_at = SteadyClock::now();
  } catch (const ScpiError& ex) {
    e.client->disconnect();
    {
      std::lock_guard<std::mutex> lock(mu_);
      e.state = InstrumentState::Error;
      e.last_error = ex.what();
      e.settings.reset();
    }
    logger_.error("scpi", e.cfg.id + ": connect failed: " + ex.what(), {{"instrument", e.cfg.id}, {"kind", to_string(ex.kind())}});
    throw;
  }
  std::lock_guard<std::mutex> lock(mu_);
  return snapshot_locked(e);
}

InstrumentInfo InstrumentRegistry::connect(const std::string& id, const std::optional<std::string>& host,
                                           const std::optional<uint16_t>& port) {
  Entry* e = find_entry(id);
  if (host) require_loopback(*host);
  Lease lease = acquire({id}, "api:connect", LeaseKind::Transient);
  return connect_entry(*e, host, port);
}

InstrumentInfo InstrumentRegistry::disconnect(const std::string& id) {
  Entry* e = find_entry(id);
  Lease lease;
  try {
    lease = acquire({id}, "api:disconnect", LeaseKind::Transient);
  } catch (const MfError& ex) {
    if (ex.code() == ErrorCode::InstrumentBusy) {
      throw MfError(ErrorCode::Conflict, "cannot disconnect '" + id + "' while a test is running", "id");
    }
    throw;
  }
  bool was_connected;
  {
    std::lock_guard<std::mutex> lock(mu_);
    was_connected = e->state == InstrumentState::Connected;
  }
  if (was_connected && e->cfg.kind == InstrumentKind::SignalGenerator) {
    try {
      CallOptions o;
      o.max_retries = 0;
      e->adapter->safe_state(o);
    } catch (const std::exception& ex) {
      logger_.warn("scpi", e->cfg.id + ": could not switch output off before disconnect: " + ex.what(), {{"instrument", e->cfg.id}});
    }
  }
  e->client->disconnect();
  {
    std::lock_guard<std::mutex> lock(mu_);
    e->state = InstrumentState::Disconnected;
    e->settings.reset();
    e->last_error.clear();
  }
  std::lock_guard<std::mutex> lock(mu_);
  return snapshot_locked(*e);
}

void InstrumentRegistry::refresh_stale(int max_age_ms) {
  for (const auto& id : ids()) {
    Entry* e = find_entry(id);
    {
      std::lock_guard<std::mutex> lock(mu_);
      if (e->leased) continue;
      const bool candidate = e->state == InstrumentState::Connected || e->state == InstrumentState::Error;
      if (!candidate) continue;
      const auto age = std::chrono::duration_cast<std::chrono::milliseconds>(SteadyClock::now() - e->settings_at).count();
      if (e->state == InstrumentState::Connected && e->settings && age < max_age_ms) continue;
    }
    if (!e->client->wants_connection()) continue;
    Lease lease;
    try {
      lease = acquire({id}, "api:refresh", LeaseKind::Transient, nullptr, 0);
    } catch (const MfError&) {
      continue;  // busy: the owner keeps the snapshot fresh
    }
    CallOptions o;
    o.max_retries = 0;
    o.quiet = true;
    o.explain_timeouts = false;
    o.timeout_ms = std::min(e->cfg.timeout_ms, 500);
    try {
      store_settings(*e, e->adapter->read_settings(o));
    } catch (const ScpiError&) {
      // state/last_error are updated by the communication hook
      std::lock_guard<std::mutex> lock(mu_);
      e->settings.reset();
    }
  }
}

void InstrumentRegistry::shutdown() {
  for (const auto& kv : entries_) {
    Entry* e = kv.second.get();
    bool connected;
    {
      std::lock_guard<std::mutex> lock(mu_);
      connected = e->state == InstrumentState::Connected || e->state == InstrumentState::Error;
    }
    if (connected && e->cfg.kind == InstrumentKind::SignalGenerator && e->client->is_open()) {
      try {
        CallOptions o;
        o.max_retries = 0;
        o.timeout_ms = 500;
        o.auto_reconnect = false;
        e->adapter->safe_state(o);
      } catch (const std::exception&) {
      }
    }
    e->client->disconnect();
    std::lock_guard<std::mutex> lock(mu_);
    e->state = InstrumentState::Disconnected;
    e->settings.reset();
  }
}

}  // namespace mf
