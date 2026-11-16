#include "measureflow/engine/runner.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <functional>
#include <thread>

#include "measureflow/instruments/settings.hpp"
#include "measureflow/util/errors.hpp"
#include "measureflow/util/ids.hpp"
#include "measureflow/util/strings.hpp"
#include "measureflow/util/time.hpp"

namespace mf {

struct TestRunner::Ctx {
  RunRecord rec;  // guarded by TestRunner::mu_
  const SequenceDef* seq = nullptr;
  ResolvedPlan plan;
  Lease lease;
  std::atomic<bool> cancel{false};
  std::atomic<bool> finished{false};
  std::thread worker;
  int completed_units = 0;  // guarded by mu_
  int task_counter = 0;     // guarded by mu_
};

namespace {

// Raised inside step functions for a failure with a stable error code.
class StepFailure : public std::runtime_error {
 public:
  StepFailure(std::string code, const std::string& msg, bool abort_run)
      : std::runtime_error(msg), code_(std::move(code)), abort_(abort_run) {}
  const std::string& code() const { return code_; }
  bool abort_run() const { return abort_; }

 private:
  std::string code_;
  bool abort_;
};

std::string code_of(const ScpiError& e) {
  switch (e.kind()) {
    case ScpiErrorKind::Timeout: return "COMM_TIMEOUT";
    case ScpiErrorKind::Disconnected: return "COMM_DISCONNECTED";
    case ScpiErrorKind::InvalidResponse: return "COMM_INVALID_RESPONSE";
    case ScpiErrorKind::ResponseTooLarge: return "COMM_RESPONSE_TOO_LARGE";
    case ScpiErrorKind::Instrument: return "INSTRUMENT_ERROR";
    case ScpiErrorKind::Cancelled: return "CANCELLED";
  }
  return "INTERNAL";
}

std::string describe(const std::vector<InstrumentError>& errs) {
  std::string s;
  for (const auto& e : errs) s += (s.empty() ? "" : "; ") + std::to_string(e.code) + " \"" + e.message + "\"";
  return s;
}

}  // namespace

// ================================================================================================
// RunExecutor: everything that happens on the worker thread of one run.
// ================================================================================================
class RunExecutor {
 public:
  RunExecutor(TestRunner& runner, TestRunner::Ctx& ctx)
      : r_(runner), c_(ctx), run_id_(ctx.rec.run_id), retries_(ctx.rec.retries) {
    dut_profile_ = ctx.rec.dut.profile;
    dut_firmware_ = ctx.rec.dut.firmware;
  }

  void run() {
    InstrumentGuard guard(*this);
    try {
      begin_run();
      execute_steps();
    } catch (const std::exception& e) {
      internal_error(e.what());
    } catch (...) {
      internal_error("unknown exception");
    }
    try {
      finish();
    } catch (const std::exception& e) {
      log(LogLevel::Error, std::string("finalisation failed: ") + e.what());
    } catch (...) {
      log(LogLevel::Error, "finalisation failed: unknown exception");
    }
  }

  void release_instruments() {
    if (released_) return;
    released_ = true;
    if (!c_.lease) return;
    c_.lease.detach_cancel();
    if (!cleanup_done_) cleanup_best_effort("guard");
    CallOptions o;
    o.max_retries = 0;
    o.quiet = true;
    o.explain_timeouts = false;
    o.timeout_ms = 500;
    for (const auto& id : c_.lease.ids()) {
      try {
        if (c_.lease.client(id).wants_connection()) c_.lease.refresh_settings(id, o);
      } catch (const std::exception&) {
      }
    }
    c_.lease.release();
    log(LogLevel::Debug, "instruments released");
  }

  // Last resort when finish() could not publish the final state.
  void ensure_published() {
    if (published_) return;
    RunRecord fin;
    {
      std::lock_guard<std::mutex> lk(r_.mu_);
      fin = c_.rec;
    }
    fin.status = Status::Error;
    fin.finished_at = iso_now();
    fin.current_step.clear();
    fin.running_tasks = 0;
    if (!fin.error) fin.error = RunError{"INTERNAL", "run terminated unexpectedly"};
    publish(fin);
  }

 private:
  struct InstrumentGuard {
    explicit InstrumentGuard(RunExecutor& e) : ex(e) {}
    ~InstrumentGuard() {
      try {
        ex.release_instruments();
      } catch (...) {
      }
      try {
        ex.ensure_published();
      } catch (...) {
      }
    }
    RunExecutor& ex;
  };

  struct StepOutcome {
    Status status = Status::Pass;
    std::string message;
  };

  struct TaskOutcome {
    Status status = Status::Pass;
    std::string message;
    std::string error_code;
    bool comm_failure = false;
  };

  // ---------------------------------------------------------------- helpers
  template <typename F>
  void with_rec(F&& f) {
    std::lock_guard<std::mutex> lk(r_.mu_);
    f(c_.rec);
  }

  void log(LogLevel lv, const std::string& msg, LogFields f = {}) { r_.logger_.log(lv, "engine", msg, std::move(f), run_id_); }
  bool cancelled() const { return c_.cancel.load(); }

  [[noreturn]] void throw_cancelled() { throw ScpiError(ScpiErrorKind::Cancelled, "", "", "run cancelled"); }

  // Sleeps `ms`, returns false when cancellation was requested meanwhile.
  bool sleep_ms(int ms) {
    const auto end = SteadyClock::now() + std::chrono::milliseconds(std::max(ms, 0));
    while (SteadyClock::now() < end) {
      if (cancelled()) return false;
      const auto left = std::chrono::duration_cast<std::chrono::milliseconds>(end - SteadyClock::now()).count();
      std::this_thread::sleep_for(std::chrono::milliseconds(std::max<long long>(1, std::min<long long>(left, 10))));
    }
    return !cancelled();
  }

  bool backoff(int attempt) { return sleep_ms(std::min(r_.options_.retry_backoff_ms * attempt, 1000)); }

  void update_progress_locked() {
    const int planned = std::max(c_.plan.planned_units, 1);
    c_.rec.progress = std::min(1.0, static_cast<double>(c_.completed_units) / planned);
  }

  // Updates the registry's settings snapshot of the instrument of `kind` (best effort).
  void refresh_kind(InstrumentKind kind) {
    CallOptions o;
    o.max_retries = 0;
    o.quiet = true;
    o.explain_timeouts = false;
    for (const auto& id : c_.lease.ids()) {
      if (c_.lease.kind_of(id) != kind) continue;
      try {
        c_.lease.refresh_settings(id, o);
      } catch (const std::exception&) {
      }
    }
  }

  // Read-back check of a generator configuration (a setter swallowed by a dropped connection shows up here).
  static void verify_signal(const SigGenState& st, const Settings& wanted) {
    auto close = [](double a, double b) { return std::fabs(a - b) <= 1e-6 * std::max(1.0, std::fabs(b)); };
    auto fail = [&](const std::string& what) {
      throw ScpiError(ScpiErrorKind::InvalidResponse, "siggen", "MF:SOUR:CONF?", "generator read-back differs from the requested " + what);
    };
    for (const auto& [key, value] : wanted) {
      const double* d = std::get_if<double>(&value);
      const bool* b = std::get_if<bool>(&value);
      const std::string* str = std::get_if<std::string>(&value);
      if (key == "frequency_hz" && d && !close(st.frequency_hz, *d)) fail(key);
      if (key == "amplitude_vpk" && d && !close(st.amplitude_vpk, *d)) fail(key);
      if (key == "sample_rate_hz" && d && !close(st.sample_rate_hz, *d)) fail(key);
      if (key == "output" && b && st.output != *b) fail(key);
      if (key == "function" && str && to_upper(st.function) != to_upper(*str)) fail(key);
    }
  }

  void require_connected() {
    for (const auto& id : c_.lease.ids()) {
      if (!c_.lease.client(id).wants_connection()) {
        throw StepFailure("NOT_CONNECTED", "instrument '" + id + "' is not connected (the sequence needs an init step)", true);
      }
    }
  }

  void reapply_state() {
    if (signal_known_) c_.lease.siggen().apply_settings(signal_state_);
    if (dut_known_) {
      c_.lease.dut().apply_settings(dut_selection_);
      if (!dut_extra_.empty()) c_.lease.dut().apply_settings(dut_extra_);
    }
  }

  // Reconnects the failed instrument (and any other whose socket is gone) and restores the known configuration.
  void recover(const std::string& failed_id) {
    for (const auto& id : c_.lease.ids()) {
      auto& cl = c_.lease.client(id);
      const bool wanted = cl.wants_connection();
      if (id == failed_id || (wanted && !cl.is_open())) {
        log(LogLevel::Info, "reconnecting instrument '" + id + "'", {{"instrument", id}});
        c_.lease.connect(id);
      }
    }
    reapply_state();
  }

  template <typename F>
  void with_retries(const std::string& what, F&& fn) {
    const int tries = retries_ + 1;
    std::string failed_id;
    for (int attempt = 1;; ++attempt) {
      try {
        if (attempt > 1) recover(failed_id);
        fn();
        return;
      } catch (const ScpiError& e) {
        if (e.kind() == ScpiErrorKind::Cancelled || !is_communication_kind(e.kind()) || attempt >= tries) throw;
        failed_id = e.instrument();
        log(LogLevel::Warn, what + ": " + e.what() + " - retrying (attempt " + std::to_string(attempt + 1) + " of " + std::to_string(tries) + ")",
            {{"kind", to_string(e.kind())}, {"attempt", static_cast<int64_t>(attempt)}});
        if (!backoff(attempt)) throw_cancelled();
      }
    }
  }

  // ---------------------------------------------------------------- run lifecycle
  void begin_run() {
    RunRecord copy;
    with_rec([&](RunRecord& r) {
      r.status = Status::Running;
      r.started_at = iso_now();
      copy = r;
    });
    run_clock_.restart();
    log(LogLevel::Info, "run started: " + copy.sequence_id,
        {{"sequence_id", copy.sequence_id}, {"label", copy.label}, {"retries", static_cast<int64_t>(copy.retries)},
         {"dut_profile", copy.dut.profile}, {"dut_firmware", copy.dut.firmware}});
    try {
      r_.store_.save_run(copy, false);
    } catch (const std::exception& e) {
      log(LogLevel::Error, std::string("cannot persist run start: ") + e.what());
    }
  }

  void internal_error(const std::string& msg) {
    aborted_ = true;
    if (!error_) error_ = RunError{"INTERNAL", msg};
    log(LogLevel::Error, "internal error: " + msg);
  }

  void execute_steps() {
    const size_t n = c_.plan.steps.size();
    for (size_t i = 0; i < n; ++i) {
      if (cancelled()) {
        interrupted_ = true;
        break;
      }
      if (aborted_) break;
      execute_step(i);
    }
    if (cancelled() || aborted_) {
      if (cancelled()) log(LogLevel::Warn, "run cancelled - executing cleanup");
      automatic_cleanup();
    }
    // Mark everything that did not run.
    const bool was_cancel = interrupted_;
    with_rec([&](RunRecord& r) {
      for (size_t i = 0; i < r.steps.size(); ++i) {
        StepRecord& s = r.steps[i];
        if (s.status != Status::Pending) continue;
        const StepType t = c_.plan.steps[i].def->type;
        if (t == StepType::Cleanup && cleanup_done_) {
          s.status = Status::Pass;
          s.message = was_cancel ? "executed automatically after cancellation" : "executed automatically after abort";
        } else if (t == StepType::Cleanup && !cleanup_failure_.empty()) {
          s.status = Status::Error;
          s.message = "cleanup failed, generator output state unknown: " + cleanup_failure_;
        } else if (t == StepType::Report) {
          // written by the finalisation below
        } else {
          s.status = Status::Cancelled;
          s.message = was_cancel ? "skipped: run cancelled" : "skipped: run aborted";
        }
      }
    });
  }

  void execute_step(size_t i) {
    const ResolvedStep& rs = c_.plan.steps[i];
    const StepType type = rs.def->type;
    with_rec([&](RunRecord& r) {
      r.steps[i].status = Status::Running;
      r.steps[i].started_at = iso_now();
      r.current_step = rs.def->id;
    });
    log(LogLevel::Info, "step '" + rs.def->id + "' (" + to_string(type) + ") started", {{"step", rs.def->id}});
    Stopwatch sw;
    StepOutcome out;
    try {
      switch (type) {
        case StepType::Init: out = step_init(rs); break;
        case StepType::ConfigureSignal: out = step_configure_signal(rs); break;
        case StepType::ConfigureDut: out = step_configure_dut(rs); break;
        case StepType::Measure: out = step_measure(rs); break;
        case StepType::Sweep: out = step_sweep(rs); break;
        case StepType::Cleanup: out = step_cleanup(); break;
        case StepType::Report: out.message = "report is written when the run completes"; break;
      }
    } catch (const StepFailure& f) {
      out.status = Status::Error;
      out.message = f.what();
      if (!error_) error_ = RunError{f.code(), f.what()};
      if (f.abort_run()) aborted_ = true;
    } catch (const ScpiError& e) {
      if (e.kind() == ScpiErrorKind::Cancelled) {
        out.status = Status::Cancelled;
        out.message = "cancelled";
        interrupted_ = true;
      } else {
        out.status = Status::Error;
        out.message = e.what();
        if (!error_) error_ = RunError{code_of(e), e.what()};
        aborted_ = true;
      }
    } catch (const MfError& e) {
      out.status = Status::Error;
      out.message = e.what();
      if (!error_) error_ = RunError{"INTERNAL", e.what()};
      aborted_ = true;
    }
    const bool measuring = type == StepType::Measure || type == StepType::Sweep;
    with_rec([&](RunRecord& r) {
      StepRecord& s = r.steps[i];
      s.status = out.status;
      s.message = out.message;
      s.duration_ms = sw.elapsed_ms();
      if (!measuring) {
        ++c_.completed_units;
        update_progress_locked();
      }
    });
    log(out.status == Status::Error ? LogLevel::Error : LogLevel::Info,
        "step '" + rs.def->id + "' finished: " + to_string(out.status) + (out.message.empty() ? "" : " - " + out.message),
        {{"step", rs.def->id}, {"status", to_string(out.status)}, {"duration_ms", sw.elapsed_ms()}});
  }

  // ---------------------------------------------------------------- steps
  StepOutcome step_init(const ResolvedStep& rs) {
    std::vector<std::string> ids;
    for (const auto& id : rs.def->instruments) {
      if (std::find(c_.lease.ids().begin(), c_.lease.ids().end(), id) == c_.lease.ids().end()) {
        throw StepFailure("NOT_CONNECTED", "init references unknown instrument '" + id + "'", true);
      }
      ids.push_back(id);
    }
    if (ids.empty()) ids = c_.lease.ids();
    std::string names;
    for (const auto& id : ids) {
      with_retries("init " + id, [&]() {
        if (cancelled()) throw_cancelled();
        auto& cl = c_.lease.client(id);
        if (!cl.is_open() || !cl.wants_connection()) c_.lease.connect(id);
        auto& ad = c_.lease.adapter(id);
        ad.reset_to_defaults();
        const Idn idn = ad.identify();
        if (ad.kind() == InstrumentKind::DeviceUnderTest) dut_firmware_ = idn.firmware;
        c_.lease.refresh_settings(id);
        log(LogLevel::Info, "instrument '" + id + "' ready: " + idn.model + " fw " + idn.firmware, {{"instrument", id}});
      });
      names += (names.empty() ? "" : ", ") + id;
    }
    // After *RST everything is at defaults: forget previously tracked configuration.
    signal_known_ = false;
    dut_known_ = false;
    return {Status::Pass, "instruments ready: " + names};
  }

  StepOutcome step_configure_signal(const ResolvedStep& rs) {
    require_connected();
    signal_state_ = rs.signal;
    signal_known_ = true;
    with_retries("configure_signal", [&]() {
      if (cancelled()) throw_cancelled();
      auto& gen = c_.lease.siggen();
      gen.apply_settings(rs.signal);
      verify_signal(gen.read_state(), rs.signal);
    });
    if (rs.settle_ms > 0 && !sleep_ms(rs.settle_ms)) throw_cancelled();
    refresh_kind(InstrumentKind::SignalGenerator);
    return {Status::Pass, "generator configured"};
  }

  StepOutcome step_configure_dut(const ResolvedStep& rs) {
    require_connected();
    dut_selection_ = Settings{{"profile", c_.rec.dut.profile}, {"firmware", c_.rec.dut.firmware}};
    dut_extra_ = rs.dut;
    dut_known_ = true;
    DutState state;
    with_retries("configure_dut", [&]() {
      if (cancelled()) throw_cancelled();
      auto& dut = c_.lease.dut();
      dut.apply_settings(dut_selection_);
      if (!dut_extra_.empty()) dut.apply_settings(dut_extra_);
      state = dut.read_state();
      // A setter lost to a dropped connection is invisible until read back: treat a mismatch as a
      // communication failure so that the task-level retry reconnects and re-applies the configuration.
      if (state.firmware != c_.rec.dut.firmware || state.profile != c_.rec.dut.profile) {
        throw ScpiError(ScpiErrorKind::InvalidResponse, "dut", "",
                        "DUT reports " + state.profile + " / firmware " + state.firmware + " but " + c_.rec.dut.profile + " / " +
                            c_.rec.dut.firmware + " was requested");
      }
    });
    dut_profile_ = c_.rec.dut.profile;
    dut_firmware_ = state.firmware;
    refresh_kind(InstrumentKind::DeviceUnderTest);
    return {Status::Pass, "DUT " + dut_profile_ + " firmware " + dut_firmware_};
  }

  StepOutcome step_measure(const ResolvedStep& rs) {
    require_connected();
    const TaskOutcome t = measure_task(rs.def->id, rs.name, rs.def->measurement, rs.limits, false, nullptr);
    return finish_measure_step(t);
  }

  StepOutcome step_sweep(const ResolvedStep& rs) {
    require_connected();
    Status worst = Status::Pass;
    std::string msg;
    bool first = true;
    int done = 0;
    for (double f : rs.points_hz) {
      if (cancelled()) {
        interrupted_ = true;
        worst = Status::Cancelled;
        msg = "cancelled after " + std::to_string(done) + " of " + std::to_string(rs.points_hz.size()) + " points";
        break;
      }
      const bool set_amp = first;
      first = false;
      auto prepare = [&, f, set_amp]() {
        signal_state_["frequency_hz"] = f;
        Settings s{{"frequency_hz", f}};
        if (set_amp) {
          signal_state_["amplitude_vpk"] = rs.sweep_amplitude_vpk;
          s["amplitude_vpk"] = rs.sweep_amplitude_vpk;
        }
        c_.lease.siggen().apply_settings(s);
        signal_known_ = true;
        if (rs.settle_ms > 0 && !sleep_ms(rs.settle_ms)) throw_cancelled();
      };
      const std::string name = rs.name + " @ " + format_g(f, 9) + " Hz";
      const TaskOutcome t = measure_task(rs.def->id, name, Measurement::Gain, rs.limits, true, prepare);
      ++done;
      if (t.status == Status::Cancelled) {
        worst = Status::Cancelled;
        interrupted_ = true;
        break;
      }
      if (t.status == Status::Error) worst = Status::Error;
      else if (t.status == Status::Fail && worst == Status::Pass) worst = Status::Fail;
      if (t.comm_failure) {
        aborted_ = true;
        if (!error_) error_ = RunError{t.error_code, t.message};
        msg = "aborted at " + format_g(f, 9) + " Hz: " + t.message;
        break;
      }
    }
    if (msg.empty()) msg = std::to_string(done) + " point(s) measured";
    return {worst, msg};
  }

  StepOutcome finish_measure_step(const TaskOutcome& t) {
    if (t.comm_failure) {
      aborted_ = true;
      if (!error_) error_ = RunError{t.error_code, t.message};
    }
    if (t.status == Status::Cancelled) interrupted_ = true;
    return {t.status, t.message};
  }

  StepOutcome step_cleanup() {
    c_.lease.detach_cancel();  // cleanup must not be interrupted by a late cancel request
    require_connected();
    with_retries("cleanup", [&]() {
      c_.lease.siggen().safe_state();
      for (const auto& id : c_.lease.ids()) {
        if (c_.lease.kind_of(id) != InstrumentKind::SignalGenerator) c_.lease.client(id).read_errors();
      }
    });
    signal_state_["output"] = false;
    cleanup_done_ = true;
    return {Status::Pass, "generator output off"};
  }

  // Cleanup after cancellation/abort: never throws.
  void automatic_cleanup() { cleanup_best_effort("automatic"); }

  void cleanup_best_effort(const char* origin) {
    if (!c_.lease) return;
    c_.lease.detach_cancel();
    CallOptions o;
    o.max_retries = 1;
    o.timeout_ms = 1000;
    try {
      auto& sg = c_.lease.siggen();
      if (!sg.client().wants_connection()) {
        cleanup_done_ = true;  // never connected -> nothing is switched on
        return;
      }
      sg.safe_state(o);
      signal_state_["output"] = false;
      cleanup_done_ = true;
      log(LogLevel::Info, std::string("cleanup (") + origin + "): generator output off");
    } catch (const std::exception& e) {
      cleanup_failure_ = e.what();
      log(LogLevel::Error, std::string("cleanup (") + origin + ") failed: " + e.what());
    }
  }

  // ---------------------------------------------------------------- measurement task
  TaskOutcome measure_task(const std::string& step_id, const std::string& name, Measurement m, const Limits& limits, bool sweep,
                           const std::function<void()>& prepare) {
    with_rec([&](RunRecord& r) { r.running_tasks = 1; });
    Stopwatch sw;
    const int tries = retries_ + 1;
    int attempts = 0;
    bool have_value = false;
    double value = 0.0;
    std::vector<InstrumentError> inst_errors;
    std::optional<ScpiError> failure;
    bool was_cancelled = false;
    std::string failed_id;
    for (int attempt = 1; attempt <= tries; ++attempt) {
      attempts = attempt;
      if (cancelled()) {
        was_cancelled = true;
        break;
      }
      failure.reset();
      have_value = false;
      inst_errors.clear();
      try {
        if (attempt > 1) recover(failed_id);
        if (prepare) prepare();
        auto& an = c_.lease.analyzer();
        an.acquire();
        value = an.measure(m);
        have_value = true;
        inst_errors = an.client().read_errors();
        break;
      } catch (const ScpiError& e) {
        if (e.kind() == ScpiErrorKind::Cancelled) {
          was_cancelled = true;
          break;
        }
        failure = e;
        failed_id = e.instrument();
        log(LogLevel::Warn, name + ": attempt " + std::to_string(attempt) + " of " + std::to_string(tries) + " failed: " + e.what(),
            {{"kind", to_string(e.kind())}, {"attempt", static_cast<int64_t>(attempt)}});
        if (!is_communication_kind(e.kind())) break;
        if (attempt < tries && !backoff(attempt)) {
          was_cancelled = true;
          break;
        }
      }
    }

    TaskResult t;
    TaskOutcome out;
    t.run_id = run_id_;
    t.step_id = step_id;
    t.test_name = name;
    t.kind = sweep ? "freq_sweep" : to_string(m);
    t.limits = limits;
    t.attempts = attempts;
    t.timestamp = iso_now();
    t.dut_profile = dut_profile_;
    t.dut_firmware = dut_firmware_;
    if (signal_known_) {
      const auto f = signal_state_.find("frequency_hz");
      const auto a = signal_state_.find("amplitude_vpk");
      const auto fn = signal_state_.find("function");
      if (f != signal_state_.end() && is_number(f->second)) t.inputs.frequency_hz = std::get<double>(f->second);
      if (a != signal_state_.end() && is_number(a->second)) t.inputs.amplitude_vpk = std::get<double>(a->second);
      if (fn != signal_state_.end() && is_string(fn->second)) t.inputs.function = std::get<std::string>(fn->second);
    }
    if (sweep) t.inputs.measurement = to_string(m);
    const std::string unit = limits.unit.empty() ? measurement_unit(m) : limits.unit;
    if (t.limits.unit.empty()) t.limits.unit = unit;

    if (was_cancelled) {
      t.status = Status::Cancelled;
      t.message = "cancelled";
    } else if (failure) {
      t.status = Status::Error;
      t.error_code = code_of(*failure);
      t.message = failure->what();
      out.comm_failure = is_communication_kind(failure->kind());
    } else if (have_value && std::isnan(value)) {
      t.status = Status::Error;
      t.error_code = "MEASUREMENT_NAN";
      t.message = "instrument returned NaN" + (inst_errors.empty() ? std::string() : " (instrument error: " + describe(inst_errors) + ")");
    } else if (have_value && std::isinf(value)) {
      t.status = Status::Error;
      t.error_code = "MEASUREMENT_INF";
      t.message = std::string("instrument returned ") + (value > 0 ? "+Inf" : "-Inf") +
                  (inst_errors.empty() ? std::string() : " (instrument error: " + describe(inst_errors) + ")");
    } else if (have_value && !inst_errors.empty()) {
      t.status = Status::Error;
      t.error_code = "INSTRUMENT_ERROR";
      t.message = "instrument reported error " + describe(inst_errors);
    } else if (have_value) {
      const double v = value;
      t.measured = Measured{v, unit};
      if (limits.min && v < *limits.min) {
        t.status = Status::Fail;
        t.error_code = "OUT_OF_TOLERANCE_LOW";
        t.message = format_g(v, 6) + " " + unit + " is below the lower limit " + format_g(*limits.min, 6) + " " + unit;
      } else if (limits.max && v > *limits.max) {
        t.status = Status::Fail;
        t.error_code = "OUT_OF_TOLERANCE_HIGH";
        t.message = format_g(v, 6) + " " + unit + " is above the upper limit " + format_g(*limits.max, 6) + " " + unit;
      } else {
        t.status = Status::Pass;
        t.message = "within limits";
      }
    } else {
      t.status = Status::Error;
      t.error_code = "INTERNAL";
      t.message = "no measurement value";
    }
    t.duration_ms = sw.elapsed_ms();

    with_rec([&](RunRecord& r) {
      t.task_id = make_task_id(run_id_, ++c_.task_counter);
      r.tasks.push_back(t);
      r.running_tasks = 0;
      ++c_.completed_units;
      update_progress_locked();
    });
    log(t.status == Status::Error ? LogLevel::Error : (t.status == Status::Fail ? LogLevel::Warn : LogLevel::Info),
        name + ": " + to_string(t.status) + " - " + t.message,
        {{"task_id", t.task_id}, {"status", to_string(t.status)}, {"attempts", static_cast<int64_t>(t.attempts)}});
    out.status = t.status;
    out.message = t.message;
    out.error_code = t.error_code;
    return out;
  }

  // ---------------------------------------------------------------- completion
  void publish(const RunRecord& fin) {
    {
      std::lock_guard<std::mutex> lk(r_.mu_);
      const bool cancel_flag = c_.rec.cancel_requested;
      c_.rec = fin;
      c_.rec.cancel_requested = cancel_flag;
      c_.finished.store(true);
      if (r_.active_.get() == &c_) {
        r_.last_ = r_.active_;
        r_.active_.reset();
      }
    }
    published_ = true;
    r_.idle_cv_.notify_all();
  }

  void finish() {
    release_instruments();  // output OFF + lease release before the final state becomes visible

    RunRecord fin;
    with_rec([&](RunRecord& r) { fin = r; });
    const bool cancelled_eff = c_.cancel.load() && interrupted_;
    fin.status = aggregate_status(cancelled_eff, aborted_, fin.tasks);
    fin.finished_at = iso_now();
    fin.duration_ms = run_clock_.elapsed_ms();
    fin.current_step.clear();
    fin.running_tasks = 0;
    fin.cancel_requested = fin.cancel_requested || c_.cancel.load();
    if (fin.status == Status::Pass || fin.status == Status::Fail) {
      fin.progress = 1.0;
    } else {
      const int planned = std::max(c_.plan.planned_units, 1);
      std::lock_guard<std::mutex> lk(r_.mu_);
      fin.progress = std::min(1.0, static_cast<double>(c_.completed_units) / planned);
    }
    if (fin.status == Status::Error) {
      if (error_) {
        fin.error = error_;
      } else {
        for (const auto& t : fin.tasks) {
          if (t.status == Status::Error) {
            fin.error = RunError{t.error_code.empty() ? "INTERNAL" : t.error_code, t.message};
            break;
          }
        }
      }
    }
    log(fin.status == Status::Pass ? LogLevel::Info : (fin.status == Status::Cancelled ? LogLevel::Warn : LogLevel::Error),
        "run finished: " + std::string(to_string(fin.status)),
        {{"status", to_string(fin.status)}, {"tasks", static_cast<int64_t>(fin.tasks.size())}, {"duration_ms", fin.duration_ms}});
    fin.log = r_.logger_.close_run_capture(run_id_);

    // The report is written for every finished run; the sequence's report step documents it.
    for (size_t i = 0; i < fin.steps.size(); ++i) {
      if (fin.steps[i].status == Status::Pending && c_.plan.steps[i].def->type == StepType::Report) {
        fin.steps[i].status = Status::Pass;
        fin.steps[i].message = "CSV, HTML and PDF reports generated";
      }
    }
    try {
      r_.reports_.generate(fin);
    } catch (const std::exception& e) {
      log(LogLevel::Error, std::string("report generation failed: ") + e.what());
      for (size_t i = 0; i < fin.steps.size(); ++i) {
        if (c_.plan.steps[i].def->type == StepType::Report) {
          fin.steps[i].status = Status::Error;
          fin.steps[i].message = std::string("report generation failed: ") + e.what();
        }
      }
    }
    try {
      r_.store_.save_run(fin, true);
    } catch (const std::exception& e) {
      log(LogLevel::Error, std::string("cannot persist run: ") + e.what());
    }
    publish(fin);
  }

  TestRunner& r_;
  TestRunner::Ctx& c_;
  const std::string run_id_;
  const int retries_;
  Stopwatch run_clock_;
  // tracked configuration (restored after a reconnect)
  Settings signal_state_;
  bool signal_known_ = false;
  Settings dut_selection_, dut_extra_;
  bool dut_known_ = false;
  std::string dut_profile_, dut_firmware_;
  bool cleanup_done_ = false;
  std::string cleanup_failure_;  // set when the automatic cleanup could not switch the generator off
  bool released_ = false;
  bool published_ = false;
  bool aborted_ = false;
  bool interrupted_ = false;
  std::optional<RunError> error_;
};

// ================================================================================================
// TestRunner
// ================================================================================================
TestRunner::TestRunner(InstrumentRegistry& registry, const SequenceLibrary& sequences, ResultStore& store, ReportService& reports,
                       Logger& logger, RunnerOptions options)
    : registry_(registry), sequences_(sequences), store_(store), reports_(reports), logger_(logger), options_(options) {}

TestRunner::~TestRunner() { shutdown(); }

void TestRunner::join_worker(const std::shared_ptr<Ctx>& ctx) {
  if (ctx && ctx->worker.joinable() && ctx->worker.get_id() != std::this_thread::get_id()) ctx->worker.join();
}

RunRecord TestRunner::start(const RunRequest& req) {
  std::lock_guard<std::mutex> start_lock(start_mu_);

  const SequenceDef* seq = sequences_.find(req.sequence_id);
  if (!seq) throw MfError(ErrorCode::NotFound, "unknown sequence '" + req.sequence_id + "'", "sequence_id");
  if (req.retries < 0 || req.retries > 5) throw MfError(ErrorCode::InvalidArgument, "retries must be within [0, 5]", "retries");
  if (req.label.size() > 64) throw MfError(ErrorCode::InvalidArgument, "label must be at most 64 characters", "label");
  for (char ch : req.label) {
    if (static_cast<unsigned char>(ch) < 0x20 || ch == 0x7F) throw MfError(ErrorCode::InvalidArgument, "label must not contain control characters", "label");
  }
  DutSelection dut = seq->dut;
  {
    Settings probe;
    if (req.dut_profile) probe["profile"] = *req.dut_profile;
    if (req.dut_firmware) probe["firmware"] = *req.dut_firmware;
    if (!probe.empty()) {
      try {
        validate_settings(InstrumentKind::DeviceUnderTest, probe);
      } catch (const MfError& e) {
        throw MfError(ErrorCode::InvalidArgument, e.what(), "dut." + e.field());
      }
      if (req.dut_profile) dut.profile = std::get<std::string>(probe["profile"]);
      if (req.dut_firmware) dut.firmware = std::get<std::string>(probe["firmware"]);
    }
  }
  const auto params = resolve_parameters(*seq, req.parameters);
  ResolvedPlan plan = build_plan(*seq, params);

  std::shared_ptr<Ctx> previous;
  {
    std::lock_guard<std::mutex> lk(mu_);
    if (shutting_down_) throw MfError(ErrorCode::Conflict, "the backend is shutting down");
    if (active_) throw MfError(ErrorCode::Conflict, "a test run is already active (" + active_->rec.run_id + ")");
    previous = last_;
  }
  join_worker(previous);

  auto ctx = std::make_shared<Ctx>();
  ctx->seq = seq;
  ctx->plan = std::move(plan);
  std::string run_id;
  for (int i = 0; i < 20; ++i) {
    run_id = make_run_id();
    if (!store_.contains(run_id) && !std::filesystem::exists(store_.run_dir(run_id))) break;
  }
  ctx->lease = registry_.acquire_all(run_id, LeaseKind::Run, &ctx->cancel, options_.lease_wait_ms);

  RunRecord& rec = ctx->rec;
  rec.run_id = run_id;
  rec.sequence_id = seq->id;
  rec.sequence_name = seq->name;
  rec.sequence_version = seq->version;
  rec.label = req.label;
  rec.status = Status::Pending;
  rec.created_at = iso_now();
  rec.dut = dut;
  rec.retries = req.retries;
  rec.parameters = params;
  rec.planned_tasks = ctx->plan.planned_tasks;
  for (const auto& rs : ctx->plan.steps) {
    StepRecord s;
    s.id = rs.def->id;
    s.name = rs.name;
    s.type = to_string(rs.def->type);
    rec.steps.push_back(std::move(s));
  }
  logger_.open_run_capture(run_id);
  logger_.info("engine", "run " + run_id + " accepted: " + seq->id, {{"sequence_id", seq->id}, {"label", req.label}}, run_id);

  {
    std::lock_guard<std::mutex> lk(mu_);
    active_ = ctx;
  }
  ctx->worker = std::thread([this, ctx]() {
    RunExecutor ex(*this, *ctx);
    ex.run();
  });
  return snapshot(ctx, 0);
}

RunRecord TestRunner::snapshot(const std::shared_ptr<Ctx>& ctx, size_t log_tail) const {
  RunRecord copy;
  bool finished;
  {
    std::lock_guard<std::mutex> lk(mu_);
    copy = ctx->rec;
    finished = ctx->finished.load();
  }
  if (!finished) {
    copy.log = logger_.run_tail(copy.run_id, log_tail);
  } else if (log_tail > 0 && copy.log.size() > log_tail) {
    copy.log.erase(copy.log.begin(), copy.log.begin() + static_cast<std::ptrdiff_t>(copy.log.size() - log_tail));
  }
  return copy;
}

RunRecord TestRunner::cancel(const std::string& run_id) {
  std::shared_ptr<Ctx> ctx;
  {
    std::lock_guard<std::mutex> lk(mu_);
    if (active_ && (run_id.empty() || active_->rec.run_id == run_id)) {
      ctx = active_;
      ctx->rec.cancel_requested = true;
    }
  }
  if (ctx) {
    ctx->cancel.store(true);
    logger_.warn("engine", "cancellation requested", {}, ctx->rec.run_id);
    return snapshot(ctx, 0);
  }
  if (run_id.empty()) throw MfError(ErrorCode::NotFound, "no test run is active", "run_id");
  bool known = store_.contains(run_id);
  {
    std::lock_guard<std::mutex> lk(mu_);
    known = known || (last_ && last_->rec.run_id == run_id);
  }
  if (known) throw MfError(ErrorCode::Conflict, "run " + run_id + " has already finished", "run_id");
  throw MfError(ErrorCode::NotFound, "unknown run '" + run_id + "'", "run_id");
}

std::optional<RunRecord> TestRunner::status(const std::string& run_id, size_t log_tail) {
  std::shared_ptr<Ctx> ctx;
  {
    std::lock_guard<std::mutex> lk(mu_);
    if (active_ && (run_id.empty() || active_->rec.run_id == run_id)) ctx = active_;
    else if (last_ && (run_id.empty() || last_->rec.run_id == run_id)) ctx = last_;
  }
  if (ctx) return snapshot(ctx, log_tail);
  if (run_id.empty()) {
    RunFilter f;
    f.limit = 1;
    const auto page = store_.list_runs(f);
    if (page.runs.empty()) return std::nullopt;
    auto r = store_.get_run(page.runs.front().run_id, true);
    if (r && log_tail > 0 && r->log.size() > log_tail) r->log.erase(r->log.begin(), r->log.begin() + static_cast<std::ptrdiff_t>(r->log.size() - log_tail));
    return r;
  }
  auto r = store_.get_run(run_id, true);
  if (r && log_tail > 0 && r->log.size() > log_tail) r->log.erase(r->log.begin(), r->log.begin() + static_cast<std::ptrdiff_t>(r->log.size() - log_tail));
  return r;
}

std::optional<std::string> TestRunner::active_run_id() const {
  std::lock_guard<std::mutex> lk(mu_);
  if (!active_) return std::nullopt;
  return active_->rec.run_id;
}

bool TestRunner::wait_idle(int timeout_ms) {
  std::unique_lock<std::mutex> lk(mu_);
  return idle_cv_.wait_for(lk, std::chrono::milliseconds(timeout_ms), [&] { return !active_; });
}

void TestRunner::shutdown() {
  std::shared_ptr<Ctx> active, last;
  {
    std::lock_guard<std::mutex> lk(mu_);
    shutting_down_ = true;
    active = active_;
    last = last_;
  }
  if (active) {
    active->cancel.store(true);
    {
      std::lock_guard<std::mutex> lk(mu_);
      active->rec.cancel_requested = true;
    }
    join_worker(active);
  }
  join_worker(last);
}

}  // namespace mf
