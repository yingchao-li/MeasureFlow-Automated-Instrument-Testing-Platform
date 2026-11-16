#include "measureflow/scpi/scpi_client.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <thread>

#include "measureflow/scpi/scpi_parse.hpp"
#include "measureflow/util/strings.hpp"
#include "measureflow/util/time.hpp"

namespace mf {

namespace {

bool printable_response(const std::string& s) {
  return std::all_of(s.begin(), s.end(), [](char c) {
    const auto u = static_cast<unsigned char>(c);
    return (u >= 0x20 && u <= 0x7E) || u == '\t';
  });
}

std::string clip(const std::string& s, size_t n = 120) { return s.size() <= n ? s : s.substr(0, n) + "...(" + std::to_string(s.size()) + " bytes)"; }

}  // namespace

ScpiClient::ScpiClient(ScpiConfig cfg, CommHook hook) : cfg_(std::move(cfg)), hook_(std::move(hook)) {}

ScpiClient::~ScpiClient() {
  desired_ = false;
  conn_.interrupt();
  std::lock_guard<std::mutex> lk(io_mu_);
  conn_.close();
}

ScpiConfig ScpiClient::config() const {
  std::lock_guard<std::mutex> lock(cfg_mu_);
  return cfg_;
}

void ScpiClient::set_endpoint(const std::string& host, uint16_t port) {
  std::lock_guard<std::mutex> lock(cfg_mu_);
  cfg_.host = host;
  cfg_.port = port;
}

void ScpiClient::set_hook(CommHook hook) {
  std::lock_guard<std::mutex> lock(hook_mu_);
  hook_ = std::move(hook);
}

ScpiStats ScpiClient::stats() const {
  return ScpiStats{n_commands_.load(), n_retries_.load(), n_reconnects_.load(), n_errors_.load()};
}

void ScpiClient::emit(CommEvent::Type type, const std::string& text, double duration_ms, bool quiet,
                      ScpiErrorKind kind, int attempt) {
  CommHook h;
  {
    std::lock_guard<std::mutex> lock(hook_mu_);
    h = hook_;
  }
  if (!h) return;
  CommEvent ev;
  ev.type = type;
  ev.instrument = config().id;
  ev.text = text;
  ev.duration_ms = duration_ms;
  ev.kind = kind;
  ev.quiet = quiet;
  ev.attempt = attempt;
  h(ev);
}

void ScpiClient::open_locked(const ScpiConfig& cfg, bool quiet) {
  Stopwatch sw;
  try {
    conn_.connect(cfg.host, cfg.port, cfg.connect_timeout_ms);
  } catch (const NetError& e) {
    const ScpiErrorKind kind = e.kind() == NetErrorKind::ConnectTimeout ? ScpiErrorKind::Timeout : ScpiErrorKind::Disconnected;
    throw ScpiError(kind, cfg.id, "", std::string("connect failed: ") + e.what());
  }
  ++epoch_;
  emit(CommEvent::Type::Connect, cfg.host + ":" + std::to_string(cfg.port), sw.elapsed_ms(), quiet);
}

uint64_t ScpiClient::ensure_connected(bool quiet) {
  std::lock_guard<std::mutex> lk(io_mu_);
  if (!conn_.is_open()) {
    const ScpiConfig cfg = config();
    if (!desired_.load()) throw ScpiError(ScpiErrorKind::Disconnected, cfg.id, "", "instrument is not connected");
    ++n_reconnects_;
    open_locked(cfg, quiet);
  }
  return epoch_.load();
}

void ConnectionEpoch::verify(const std::string& what) const {
  if (client_.epoch() != epoch_) {
    throw ScpiError(ScpiErrorKind::Disconnected, client_.config().id, what,
                    "connection was re-established while '" + what + "' was being sent: the instrument state is unknown");
  }
}

void ScpiClient::connect() {
  std::lock_guard<std::mutex> lk(io_mu_);
  const ScpiConfig cfg = config();
  desired_ = true;
  try {
    open_locked(cfg, false);
  } catch (const ScpiError& e) {
    ++n_errors_;
    emit(CommEvent::Type::Error, e.what(), 0.0, false, e.kind());
    throw;
  }
}

void ScpiClient::disconnect() {
  desired_ = false;
  conn_.interrupt();
  std::lock_guard<std::mutex> lk(io_mu_);
  const bool was_open = conn_.is_open();
  conn_.close();
  if (was_open) emit(CommEvent::Type::Disconnect, "closed", 0.0, false);
}

void ScpiClient::reconnect() {
  std::lock_guard<std::mutex> lk(io_mu_);
  const ScpiConfig cfg = config();
  conn_.close();
  desired_ = true;
  ++n_reconnects_;
  try {
    open_locked(cfg, false);
  } catch (const ScpiError& e) {
    ++n_errors_;
    emit(CommEvent::Type::Error, e.what(), 0.0, false, e.kind());
    throw;
  }
}

void ScpiClient::check_cancel(const std::string& cmd) {
  const auto* flag = cancel_.load();
  if (flag && flag->load(std::memory_order_relaxed)) {
    throw ScpiError(ScpiErrorKind::Cancelled, config().id, cmd, "operation cancelled");
  }
}

void ScpiClient::sleep_cancellable(int ms) {
  const auto end = SteadyClock::now() + std::chrono::milliseconds(ms);
  while (SteadyClock::now() < end) {
    const auto* flag = cancel_.load();
    if (flag && flag->load(std::memory_order_relaxed)) return;  // caller re-checks via check_cancel
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
}

std::string ScpiClient::attempt_once(const ScpiConfig& cfg, const std::string& cmd, bool is_query,
                                     const CallOptions& opts, const ResponseValidator& validate) {
  const auto* cancel = cancel_.load();
  const int timeout = opts.timeout_ms > 0 ? opts.timeout_ms : cfg.timeout_ms;
  const int total = opts.timeout_ms > 0 ? opts.timeout_ms * 2 : (cfg.total_timeout_ms > 0 ? cfg.total_timeout_ms : cfg.timeout_ms * 2);
  Stopwatch sw;
  emit(CommEvent::Type::Tx, cmd, 0.0, opts.quiet);
  try {
    conn_.send_all(cmd + "\n", timeout, cancel);
    if (!is_query) return {};
    std::string line = conn_.recv_line(cfg.max_response_bytes, timeout, total, cancel);
    if (line.empty()) {
      throw ScpiError(ScpiErrorKind::InvalidResponse, cfg.id, cmd, "empty response");
    }
    if (!printable_response(line)) {
      throw ScpiError(ScpiErrorKind::InvalidResponse, cfg.id, cmd, "response contains non-printable bytes");
    }
    if (validate && !validate(line)) {
      throw ScpiError(ScpiErrorKind::InvalidResponse, cfg.id, cmd, "unexpected response '" + clip(line, 60) + "'");
    }
    emit(CommEvent::Type::Rx, line.size() > 400 ? clip(line, 400) : line, sw.elapsed_ms(), opts.quiet);
    return line;
  } catch (const NetError& e) {
    switch (e.kind()) {
      case NetErrorKind::Timeout:
        throw ScpiError(ScpiErrorKind::Timeout, cfg.id, cmd, "timeout waiting for response to '" + clip(cmd, 60) + "': " + e.what());
      case NetErrorKind::TooLarge:
        throw ScpiError(ScpiErrorKind::ResponseTooLarge, cfg.id, cmd, e.what());
      case NetErrorKind::Cancelled:
        throw ScpiError(ScpiErrorKind::Cancelled, cfg.id, cmd, "operation cancelled");
      default:
        throw ScpiError(ScpiErrorKind::Disconnected, cfg.id, cmd, std::string("connection lost: ") + e.what());
    }
  }
}

std::optional<ScpiError> ScpiClient::explain_timeout(const ScpiConfig& cfg, const std::string& cmd, const CallOptions& opts) {
  try {
    check_cancel(cmd);
    open_locked(cfg, opts.quiet);
    CallOptions probe = opts;
    probe.timeout_ms = std::min(opts.timeout_ms > 0 ? opts.timeout_ms : cfg.timeout_ms, 500);
    probe.explain_timeouts = false;
    std::vector<InstrumentError> errs;
    for (int i = 0; i < 16; ++i) {
      InstrumentError parsed;
      attempt_once(cfg, "SYST:ERR?", true, probe, [&parsed](const std::string& s) {
        const auto e = parse_error_response(s);
        if (!e) return false;
        parsed = *e;
        return true;
      });
      if (parsed.code == 0) break;
      errs.push_back(parsed);
    }
    if (errs.empty()) return std::nullopt;
    return ScpiError(ScpiErrorKind::Instrument, cfg.id, cmd,
                     "instrument error " + std::to_string(errs.front().code) + " \"" + errs.front().message + "\" for '" +
                         clip(cmd, 60) + "' (no response line)",
                     errs.front().code, errs.front().message);
  } catch (const ScpiError&) {
    conn_.close();  // desynchronised or unreachable: the retry loop reconnects
    return std::nullopt;
  }
}

std::string ScpiClient::execute(const std::string& cmd, bool is_query, const CallOptions& opts,
                                const ResponseValidator& validate) {
  std::lock_guard<std::mutex> lk(io_mu_);
  const ScpiConfig cfg = config();
  const int retries = opts.idempotent ? (opts.max_retries >= 0 ? opts.max_retries : cfg.max_retries) : 0;
  ++n_commands_;
  for (int attempt = 0;; ++attempt) {
    check_cancel(cmd);  // no I/O has happened yet: the connection stays usable
    try {
      if (!conn_.is_open()) {
        if (!desired_.load() || !opts.auto_reconnect) {
          throw ScpiError(ScpiErrorKind::Disconnected, cfg.id, cmd, "instrument is not connected");
        }
        ++n_reconnects_;
        open_locked(cfg, opts.quiet);
      }
      return attempt_once(cfg, cmd, is_query, opts, validate);
    } catch (const ScpiError& e) {
      // The stream may be desynchronised (late response, partial line): never reuse it.
      if (e.kind() != ScpiErrorKind::Instrument) conn_.close();
      if (is_query && e.kind() == ScpiErrorKind::Timeout && opts.explain_timeouts && desired_.load()) {
        if (auto explained = explain_timeout(cfg, cmd, opts)) {
          ++n_errors_;
          emit(CommEvent::Type::Error, explained->what(), 0.0, opts.quiet, explained->kind());
          throw *explained;
        }
      }
      if (e.kind() != ScpiErrorKind::Cancelled) {
        ++n_errors_;
        emit(CommEvent::Type::Error, e.what(), 0.0, opts.quiet, e.kind());
      }
      if (!is_communication_kind(e.kind()) || attempt >= retries || !desired_.load()) throw;
      ++n_retries_;
      emit(CommEvent::Type::Retry, cmd, 0.0, opts.quiet, e.kind(), attempt + 1);
      const long long backoff = std::min<long long>(static_cast<long long>(cfg.backoff_base_ms) << std::min(attempt, 8), cfg.backoff_max_ms);
      sleep_cancellable(static_cast<int>(backoff));
    }
  }
}

void ScpiClient::write(const std::string& cmd, const CallOptions& opts) { execute(cmd, false, opts, {}); }

std::string ScpiClient::query(const std::string& cmd, const CallOptions& opts, const ResponseValidator& validate) {
  return execute(cmd, true, opts, validate);
}

double ScpiClient::query_double(const std::string& cmd, const CallOptions& opts) {
  const std::string r = execute(cmd, true, opts, [](const std::string& s) { return parse_number_strict(s).has_value(); });
  return parse_number_strict(r)->value;
}

std::vector<InstrumentError> ScpiClient::read_errors(size_t max_entries, const CallOptions& opts) {
  std::vector<InstrumentError> out;
  for (size_t i = 0; i < max_entries; ++i) {
    InstrumentError parsed;
    CallOptions o = opts;
    o.explain_timeouts = false;
    const std::string r = execute("SYST:ERR?", true, o, [&parsed](const std::string& s) {
      const auto e = parse_error_response(s);
      if (!e) return false;
      parsed = *e;
      return true;
    });
    (void)r;
    if (parsed.code == 0) break;
    out.push_back(parsed);
  }
  return out;
}

void ScpiClient::write_checked(const std::string& cmd, const CallOptions& opts) {
  write(cmd, opts);
  const auto errs = read_errors(16, opts);
  if (!errs.empty()) {
    throw ScpiError(ScpiErrorKind::Instrument, config().id, cmd,
                    "instrument error " + std::to_string(errs.front().code) + " \"" + errs.front().message + "\" after '" + clip(cmd, 60) + "'",
                    errs.front().code, errs.front().message);
  }
}

bool probe_tcp(const std::string& host, uint16_t port, int timeout_ms, std::string* detail) {
  TcpConnection c;
  try {
    c.connect(host, port, timeout_ms);
    if (detail) *detail = host + ":" + std::to_string(port) + " reachable";
    return true;
  } catch (const NetError& e) {
    if (detail) *detail = e.what();
    return false;
  }
}

bool probe_query(const std::string& host, uint16_t port, const std::string& cmd, int timeout_ms, std::string* response) {
  ScpiConfig cfg;
  cfg.id = "probe";
  cfg.host = host;
  cfg.port = port;
  cfg.timeout_ms = timeout_ms;
  cfg.connect_timeout_ms = timeout_ms;
  cfg.max_retries = 0;
  cfg.max_response_bytes = 4096;
  ScpiClient c(cfg);
  try {
    c.connect();
    const std::string r = c.query(cmd);
    if (response) *response = r;
    c.disconnect();
    return true;
  } catch (const ScpiError& e) {
    if (response) *response = e.what();
    return false;
  }
}

}  // namespace mf
