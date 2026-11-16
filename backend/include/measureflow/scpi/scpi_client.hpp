// SCPI-over-TCP client: write/query with framing, timeouts, bounded retries with backoff for idempotent
// commands, automatic reconnect, response validation, error-queue draining and a communication log hook.
//
// Locking: `io_mu_` serialises every operation on the connection (a command/response pair is atomic with
// respect to other callers). The communication hook is invoked while `io_mu_` is held, therefore a hook
// may take leaf locks (Registry::mu_, Logger::mu_) but must never call back into the same client.
// Lock order (outermost first):  TestRunner::mu_  >  InstrumentRegistry::mu_  >  ScpiClient::io_mu_ (never
// held while acquiring Registry::mu_ except through the hook, which only takes leaf locks)  >  Logger::mu_.
#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

#include "measureflow/net/tcp_connection.hpp"
#include "measureflow/scpi/scpi_error.hpp"

namespace mf {

struct ScpiConfig {
  std::string id;  // instrument id used in logs and errors
  std::string host = "127.0.0.1";
  uint16_t port = 0;
  int timeout_ms = 1000;           // max silence while waiting for a response (per read)
  int total_timeout_ms = 0;        // max time for the entire response; 0 -> 2 * timeout_ms
  int connect_timeout_ms = 500;
  int max_retries = 2;             // for idempotent commands
  size_t max_response_bytes = 1u << 20;
  int backoff_base_ms = 20;        // backoff = base * 2^attempt, capped
  int backoff_max_ms = 250;
};

struct CommEvent {
  enum class Type { Tx, Rx, Error, Connect, Disconnect, Retry };
  Type type = Type::Tx;
  std::string instrument;
  std::string text;
  double duration_ms = 0.0;
  ScpiErrorKind kind = ScpiErrorKind::Timeout;  // for Type::Error
  bool quiet = false;                           // background polling: log at debug level
  int attempt = 0;                              // for Retry
};
using CommHook = std::function<void(const CommEvent&)>;
using ResponseValidator = std::function<bool(const std::string&)>;

struct CallOptions {
  bool idempotent = true;  // may be re-sent after a communication failure
  int max_retries = -1;    // -1 = ScpiConfig::max_retries
  int timeout_ms = 0;      // 0 = ScpiConfig::timeout_ms
  bool quiet = false;
  bool auto_reconnect = true;
  // A query that times out is followed (on a fresh connection) by SYST:ERR?: when the instrument's error queue
  // explains the silence (a failed query sends no response line) the call fails with ScpiErrorKind::Instrument
  // instead of Timeout and is not retried.
  bool explain_timeouts = true;
};

struct ScpiStats {
  uint64_t commands = 0;
  uint64_t retries = 0;
  uint64_t reconnects = 0;
  uint64_t errors = 0;
};

class ScpiClient {
 public:
  explicit ScpiClient(ScpiConfig cfg, CommHook hook = {});
  ~ScpiClient();
  ScpiClient(const ScpiClient&) = delete;
  ScpiClient& operator=(const ScpiClient&) = delete;

  ScpiConfig config() const;
  // Changes host/port (only meaningful while disconnected).
  void set_endpoint(const std::string& host, uint16_t port);

  // Opens the connection and arms automatic reconnection. Throws ScpiError(Disconnected|Timeout).
  void connect();
  // Closes the connection and disarms automatic reconnection. Safe to call from any thread.
  void disconnect();
  // Re-establishes the connection (keeps the instrument "wanted").
  void reconnect();
  bool is_open() const { return conn_.is_open(); }
  // Number of connections opened so far. A setter has no response, so a connection that dropped (and was
  // transparently re-established) between a setter and the following SYST:ERR? may have lost the setter:
  // callers snapshot the epoch before a batch of setters and compare it afterwards (see ConnectionEpoch).
  uint64_t epoch() const { return epoch_.load(); }
  // Re-opens the connection if it is wanted but closed; returns the epoch. Throws ScpiError(Disconnected)
  // when the instrument is not connected (not wanted).
  uint64_t ensure_connected(bool quiet = false);
  bool wants_connection() const { return desired_.load(); }
  // Wakes up a blocked command from another thread (the command then fails with Disconnected/Cancelled).
  void interrupt() { conn_.interrupt(); }
  // While set to true, waits are aborted with ScpiErrorKind::Cancelled. The pointer must outlive its use.
  void set_cancel_flag(const std::atomic<bool>* flag) { cancel_.store(flag); }
  void set_hook(CommHook hook);

  // Setter: no response is expected. Retried (after reconnect) only when `opts.idempotent`.
  void write(const std::string& cmd, const CallOptions& opts = {});
  // Query: exactly one response line. `validate` (optional) rejects unexpected content -> InvalidResponse.
  std::string query(const std::string& cmd, const CallOptions& opts = {}, const ResponseValidator& validate = {});
  // Numeric query; "NAN"/"INF"/"-INF" are valid responses and returned as such, anything else
  // non-numeric throws InvalidResponse.
  double query_double(const std::string& cmd, const CallOptions& opts = {});
  // Reads SYST:ERR? until "0,..." (at most `max_entries`). Empty vector = queue empty.
  std::vector<InstrumentError> read_errors(size_t max_entries = 16, const CallOptions& opts = {});
  // write() followed by read_errors(); throws ScpiError(Instrument) with the first queued error.
  void write_checked(const std::string& cmd, const CallOptions& opts = {});

  ScpiStats stats() const;

 private:
  std::string execute(const std::string& cmd, bool is_query, const CallOptions& opts,
                      const ResponseValidator& validate);
  std::string attempt_once(const ScpiConfig& cfg, const std::string& cmd, bool is_query, const CallOptions& opts,
                           const ResponseValidator& validate);
  void open_locked(const ScpiConfig& cfg, bool quiet);
  // Called with io_mu_ held and the connection closed after a query timeout. Returns the Instrument error that
  // explains the missing response, or nullopt if the error queue is empty / unreachable.
  std::optional<ScpiError> explain_timeout(const ScpiConfig& cfg, const std::string& cmd, const CallOptions& opts);
  void sleep_cancellable(int ms);
  void check_cancel(const std::string& cmd);
  void emit(CommEvent::Type type, const std::string& text, double duration_ms, bool quiet,
            ScpiErrorKind kind = ScpiErrorKind::Timeout, int attempt = 0);

  mutable std::mutex cfg_mu_;  // leaf lock
  ScpiConfig cfg_;
  std::mutex io_mu_;
  TcpConnection conn_;
  std::atomic<bool> desired_{false};
  std::atomic<const std::atomic<bool>*> cancel_{nullptr};
  mutable std::mutex hook_mu_;  // leaf lock guarding hook_ replacement
  CommHook hook_;
  std::atomic<uint64_t> epoch_{0};
  std::atomic<uint64_t> n_commands_{0}, n_retries_{0}, n_reconnects_{0}, n_errors_{0};
};

// Detects a connection that was re-established while a batch of setters was in flight.
class ConnectionEpoch {
 public:
  explicit ConnectionEpoch(ScpiClient& c) : client_(c), epoch_(c.ensure_connected()) {}
  // Throws ScpiError(Disconnected) when the connection changed since construction: the setters' state is unknown.
  void verify(const std::string& what) const;

 private:
  ScpiClient& client_;
  uint64_t epoch_;
};

// One-shot helpers for health checks (separate short-lived connection, no retries, no hook).
bool probe_tcp(const std::string& host, uint16_t port, int timeout_ms, std::string* detail = nullptr);
bool probe_query(const std::string& host, uint16_t port, const std::string& cmd, int timeout_ms, std::string* response);

}  // namespace mf
