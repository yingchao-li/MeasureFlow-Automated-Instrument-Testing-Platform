// InstrumentRegistry: owns one ScpiClient + adapter per configured instrument, tracks connection state,
// and hands out exclusive RAII leases so that two runs / API calls never control one instrument at the
// same time.
//
// Locking (see also scpi_client.hpp):
//   Registry::mu_ is held only for short, non-blocking sections (state bookkeeping and lease hand-over).
//   It is NEVER held while performing instrument I/O. The communication hook runs under a client's io mutex
//   and takes Registry::mu_ then (after releasing it) Logger::mu_. Hence the order is always
//   io_mu_ -> mu_ -> logger.mu_ ; code holding mu_ must not call into a ScpiClient.
//   Leases are acquired all-or-nothing under mu_ with ids sorted, so lease acquisition cannot deadlock.
#pragma once

#include <atomic>
#include <condition_variable>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

#include "measureflow/instruments/adapters.hpp"
#include "measureflow/instruments/calibration.hpp"
#include "measureflow/instruments/instrument_types.hpp"
#include "measureflow/util/logger.hpp"
#include "measureflow/util/time.hpp"

namespace mf {

struct InstrumentInfo {
  std::string id;
  std::string name;
  InstrumentKind kind = InstrumentKind::SignalGenerator;
  std::string host;
  uint16_t port = 0;
  InstrumentState state = InstrumentState::Disconnected;
  std::string idn;       // empty when unknown
  std::string firmware;  // empty when unknown
  std::string last_error;  // empty when none
  std::string last_seen;   // ISO, empty when never
  std::optional<double> latency_ms;
  std::string leased_by;   // run id while a test owns the instrument, else empty
  CalibrationStatus calibration;
  std::optional<Settings> settings;  // only while connected
};

enum class LeaseKind { Transient, Run };

class InstrumentRegistry;

class Lease {
 public:
  Lease() = default;
  ~Lease();
  Lease(Lease&& other) noexcept;
  Lease& operator=(Lease&& other) noexcept;
  Lease(const Lease&) = delete;
  Lease& operator=(const Lease&) = delete;

  explicit operator bool() const { return reg_ != nullptr; }
  const std::string& owner() const { return owner_; }
  const std::vector<std::string>& ids() const { return ids_; }

  InstrumentAdapter& adapter(const std::string& id) const;
  ScpiClient& client(const std::string& id) const;
  SignalGeneratorAdapter& siggen() const;
  AudioAnalyzerAdapter& analyzer() const;
  DutAdapter& dut() const;
  InstrumentKind kind_of(const std::string& id) const;

  // Connects (or reconnects) a leased instrument: TCP connect, *IDN?, settings snapshot, state bookkeeping.
  InstrumentInfo connect(const std::string& id, const std::optional<std::string>& host = std::nullopt,
                         const std::optional<uint16_t>& port = std::nullopt) const;
  // Stores a fresh settings snapshot for the instrument (reads it from the device).
  void refresh_settings(const std::string& id, const CallOptions& opts = {}) const;
  // Stops the clients from observing the cancel flag (cleanup must run even when the run was cancelled).
  void detach_cancel() const;
  void release();

 private:
  friend class InstrumentRegistry;
  Lease(InstrumentRegistry* reg, std::vector<std::string> ids, std::string owner)
      : reg_(reg), ids_(std::move(ids)), owner_(std::move(owner)) {}
  void check_member(const std::string& id) const;

  InstrumentRegistry* reg_ = nullptr;
  std::vector<std::string> ids_;
  std::string owner_;
};

class InstrumentRegistry {
 public:
  InstrumentRegistry(InstrumentsFile file, Logger& logger, std::shared_ptr<const CalibrationBook> calibration);
  ~InstrumentRegistry();
  InstrumentRegistry(const InstrumentRegistry&) = delete;
  InstrumentRegistry& operator=(const InstrumentRegistry&) = delete;

  std::vector<std::string> ids() const;
  bool contains(const std::string& id) const;
  InstrumentKind kind_of(const std::string& id) const;
  const std::string& config_version() const { return config_version_; }

  // Cached snapshot (no I/O). Throws NotFound.
  InstrumentInfo info(const std::string& id) const;
  std::vector<InstrumentInfo> list() const;
  size_t connected_count() const;
  std::optional<std::string> run_leasing() const;  // run id that currently leases instruments

  // API-level operations (each takes a short transient lease).
  InstrumentInfo connect(const std::string& id, const std::optional<std::string>& host = std::nullopt,
                         const std::optional<uint16_t>& port = std::nullopt);
  // INSTRUMENT leased by a run -> MfError(Conflict). Switches the generator output OFF first (best effort).
  InstrumentInfo disconnect(const std::string& id);
  // Re-reads settings of idle connected instruments whose snapshot is older than `max_age_ms` (quiet, no retries).
  void refresh_stale(int max_age_ms);

  // Exclusive lease on all `ids` (all-or-nothing). A lease held by a run fails immediately with
  // INSTRUMENT_BUSY; transient leases are waited for up to `wait_ms`.
  Lease acquire(const std::vector<std::string>& ids, const std::string& owner, LeaseKind kind,
                const std::atomic<bool>* cancel = nullptr, int wait_ms = 2000);
  Lease acquire_all(const std::string& owner, LeaseKind kind, const std::atomic<bool>* cancel = nullptr, int wait_ms = 2000);

  // Graceful shutdown: generator output OFF (best effort), close all sockets.
  void shutdown();

  // Test hooks.
  ScpiStats client_stats(const std::string& id) const;

 private:
  friend class Lease;
  struct Entry {
    InstrumentConfig cfg;
    std::unique_ptr<ScpiClient> client;
    std::unique_ptr<InstrumentAdapter> adapter;
    // --- guarded by mu_ ---
    InstrumentState state = InstrumentState::Disconnected;
    std::string idn, firmware, last_error, last_seen;
    std::optional<double> latency_ms;
    bool leased = false;
    bool lease_is_run = false;
    std::string lease_owner;
    std::optional<Settings> settings;
    SteadyClock::time_point settings_at{};
  };

  Entry& entry_locked(const std::string& id) const;
  Entry* find_entry(const std::string& id) const;
  InstrumentInfo snapshot_locked(const Entry& e) const;
  InstrumentInfo connect_entry(Entry& e, const std::optional<std::string>& host, const std::optional<uint16_t>& port);
  void on_comm(Entry& e, const CommEvent& ev);
  void release_lease(const std::vector<std::string>& ids);
  void store_settings(Entry& e, Settings s);

  Logger& logger_;
  std::shared_ptr<const CalibrationBook> calibration_;
  std::string config_version_;
  mutable std::mutex mu_;
  std::condition_variable cv_;
  std::map<std::string, std::unique_ptr<Entry>> entries_;
};

}  // namespace mf
