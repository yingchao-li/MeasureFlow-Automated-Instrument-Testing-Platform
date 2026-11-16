#include <algorithm>
#include <cmath>

#include "measureflow/api/api_errors.hpp"
#include "measureflow/api/json_convert.hpp"
#include "measureflow/api/routes.hpp"
#include "measureflow/api/validation.hpp"
#include "measureflow/engine/serialize.hpp"
#include "measureflow/instruments/settings.hpp"
#include "measureflow/util/strings.hpp"
#include "measureflow/util/time.hpp"

namespace mf {

using nlohmann::json;

namespace {

void require_known(InstrumentRegistry& reg, const std::string& id) {
  if (!reg.contains(id)) throw MfError(ErrorCode::NotFound, "unknown instrument '" + id + "'", "id");
}

void require_wanted(Lease& lease, const std::string& id) {
  if (!lease.client(id).wants_connection()) throw MfError(ErrorCode::NotConnected, "instrument '" + id + "' is not connected", "id");
}

json instruments_json(const std::vector<InstrumentInfo>& v) {
  json a = json::array();
  for (const auto& i : v) a.push_back(instrument_to_json(i));
  return json{{"instruments", a}};
}

// Commands that change instrument-side state when merely read: never re-sent automatically.
bool is_retry_unsafe(const std::string& cmd) {
  const std::string u = to_upper(cmd);
  return starts_with(u, "SYST:ERR") || starts_with(u, "MF:FAULT");
}

// Settings from a JSON object (numbers, strings, booleans only).
Settings settings_from_json(const json& o) {
  Settings s;
  for (auto it = o.begin(); it != o.end(); ++it) {
    const std::string field = "settings." + it.key();
    if (it.value().is_boolean()) s[it.key()] = it.value().get<bool>();
    else if (it.value().is_number()) s[it.key()] = it.value().get<double>();
    else if (it.value().is_string()) s[it.key()] = it.value().get<std::string>();
    else throw MfError(ErrorCode::InvalidArgument, "setting '" + it.key() + "' must be a number, string or boolean", field);
  }
  return s;
}

}  // namespace

void register_instrument_routes(Router& router, AppServices& svc) {
  auto& reg = svc.registry;

  router.add("GET", "/api/instruments", [&reg](const HttpRequest&, HttpResponse& res) {
    reg.refresh_stale(2000);
    send_json(res, 200, instruments_json(reg.list()));
  });

  router.add("POST", "/api/instruments/connect", [&svc, &reg](const HttpRequest& req, HttpResponse& res) {
    BodyReader b(req);
    const std::string id = b.req_string("id", 1, 64);
    const auto host = b.opt_string("host", 1, 255);
    const auto port = b.opt_int("port", 1, 65535);
    b.finish();
    if (host) require_loopback(*host);
    std::vector<std::string> ids;
    if (id == "all") {
      if (host || port) throw MfError(ErrorCode::InvalidArgument, "host/port overrides require a single instrument id", "id");
      ids = reg.ids();
    } else {
      require_known(reg, id);
      ids.push_back(id);
    }
    std::vector<InstrumentInfo> done;
    std::exception_ptr first_error;
    json failed = json::array();
    for (const auto& one : ids) {
      try {
        done.push_back(reg.connect(one, host, port ? std::optional<uint16_t>(static_cast<uint16_t>(*port)) : std::nullopt));
      } catch (const MfError& e) {
        if (ids.size() == 1) throw;
        if (!first_error) first_error = std::current_exception();
        failed.push_back(json{{"id", one}, {"code", to_string(e.code())}, {"message", e.what()}});
      } catch (const ScpiError& e) {
        if (ids.size() == 1) throw;
        if (!first_error) first_error = std::current_exception();
        failed.push_back(json{{"id", one}, {"kind", to_string(e.kind())}, {"message", e.what()}});
      }
    }
    svc.logger.info("api", "connect " + id + ": " + std::to_string(done.size()) + " of " + std::to_string(ids.size()) + " connected");
    if (first_error) {
      write_exception(res, first_error);
      // enrich with the per-instrument outcome
      json body = json::parse(res.body);
      body["error"]["details"]["failed"] = failed;
      res.body = body.dump();
      return;
    }
    send_json(res, 200, instruments_json(done));
  });

  router.add("POST", "/api/instruments/disconnect", [&svc, &reg](const HttpRequest& req, HttpResponse& res) {
    BodyReader b(req);
    const std::string id = b.req_string("id", 1, 64);
    b.finish();
    std::vector<std::string> ids;
    if (id == "all") {
      ids = reg.ids();
      if (const auto running = reg.run_leasing()) throw MfError(ErrorCode::Conflict, "cannot disconnect while run " + *running + " is active");
    } else {
      require_known(reg, id);
      ids.push_back(id);
    }
    std::vector<InstrumentInfo> done;
    for (const auto& one : ids) done.push_back(reg.disconnect(one));
    svc.logger.info("api", "disconnect " + id);
    send_json(res, 200, instruments_json(done));
  });

  router.add("POST", "/api/instruments/command", [&reg](const HttpRequest& req, HttpResponse& res) {
    BodyReader b(req);
    const std::string id = b.req_string("id", 1, 64);
    std::string command = b.req_string("command", 1, 512);
    b.finish();
    command = trim(command);
    if (command.empty() || !is_printable_ascii(command)) {
      throw MfError(ErrorCode::InvalidArgument, "command must be 1-512 printable ASCII characters without line breaks", "command");
    }
    require_known(reg, id);
    Lease lease = reg.acquire({id}, "api:command", LeaseKind::Transient);
    require_wanted(lease, id);
    ScpiClient& cl = lease.client(id);
    const bool is_query = command.back() == '?';
    CallOptions opts;
    opts.idempotent = is_query && !is_retry_unsafe(command);
    Stopwatch sw;
    std::optional<std::string> response;
    json error = nullptr;
    bool explained = false;
    try {
      if (is_query) response = cl.query(command, opts);
      else cl.write(command, opts);
    } catch (const ScpiError& e) {
      // A failed query sends no response line; the client explained the silence with the instrument's error queue.
      if (!is_query || e.kind() != ScpiErrorKind::Instrument) throw;
      error = json{{"code", e.instrument_code()}, {"message", e.instrument_message()}};
      explained = true;
    }
    const double duration = sw.elapsed_ms();
    const std::string upper = to_upper(command);
    if (!explained && !starts_with(upper, "SYST:ERR") && upper != "*CLS") {
      CallOptions eo;
      eo.idempotent = false;
      const auto errs = cl.read_errors(16, eo);
      if (!errs.empty()) error = json{{"code", errs.front().code}, {"message", errs.front().message}};
    }
    if (!is_query) {
      try {
        CallOptions qo;
        qo.max_retries = 0;
        qo.quiet = true;
        lease.refresh_settings(id, qo);
      } catch (const ScpiError&) {
      }
    }
    json out = json{{"id", id}, {"command", command}, {"is_query", is_query}, {"response", nullptr},
                    {"duration_ms", round_to(duration, 2)}, {"timestamp", iso_now()}, {"error", error}};
    if (response) {
      if (response->size() > 4096) {
        out["response"] = response->substr(0, 4096);
        out["truncated"] = true;
      } else {
        out["response"] = *response;
      }
    }
    send_json(res, 200, out);
  });

  router.add("POST", "/api/instruments/configure", [&svc, &reg](const HttpRequest& req, HttpResponse& res) {
    BodyReader b(req);
    const std::string id = b.req_string("id", 1, 64);
    const json* settings_json = b.opt_object("settings");
    b.finish();
    if (!settings_json) throw MfError(ErrorCode::InvalidArgument, "missing required field 'settings'", "settings");
    require_known(reg, id);
    Settings settings = settings_from_json(*settings_json);
    try {
      validate_settings(reg.kind_of(id), settings);
    } catch (const MfError& e) {
      throw MfError(ErrorCode::InvalidArgument, e.what(), e.field().empty() || e.field() == "settings" ? "settings" : "settings." + e.field());
    }
    Lease lease = reg.acquire({id}, "api:configure", LeaseKind::Transient);
    require_wanted(lease, id);
    // Settings are idempotent: one automatic retry when the connection dropped while the setters were in flight.
    for (int attempt = 1;; ++attempt) {
      try {
        lease.adapter(id).apply_settings(settings);
        break;
      } catch (const ScpiError& e) {
        if (attempt >= 2 || !is_communication_kind(e.kind())) throw;
        svc.logger.warn("api", "configure " + id + " failed (" + e.what() + "); retrying once");
      }
    }
    lease.refresh_settings(id);
    svc.logger.info("api", "configured " + id);
    send_json(res, 200, json{{"instrument", instrument_to_json(reg.info(id))}});
  });

  router.add("GET", "/api/measurements/live", [&reg](const HttpRequest& req, HttpResponse& res) {
    const int points = static_cast<int>(query_int(req, "points", 512, 16, 4096));
    const int bins = static_cast<int>(query_int(req, "bins", 1024, 16, 8192));
    for (const auto& id : reg.ids()) {
      const InstrumentInfo i = reg.info(id);
      if (!i.leased_by.empty()) throw MfError(ErrorCode::InstrumentBusy, "instrument '" + id + "' is in use by run " + i.leased_by, "id");
    }
    Lease lease = reg.acquire_all("api:live", LeaseKind::Transient, nullptr, 3000);
    for (const auto& id : lease.ids()) require_wanted(lease, id);
    Stopwatch sw;
    auto& sg = lease.siggen();
    auto& an = lease.analyzer();
    json warnings = json::array();

    const SigGenState st = sg.read_state();
    an.acquire();
    const AnalyzerState as = an.read_state();
    const int n = std::min(points, as.points);
    const std::vector<double> wave = an.waveform(n);
    const SpectrumData sp = an.spectrum();

    json samples = json::array();
    bool wave_nonfinite = false;
    for (double v : wave) {
      samples.push_back(finite_or_null(v));
      wave_nonfinite = wave_nonfinite || !std::isfinite(v);
    }
    if (wave_nonfinite) warnings.push_back("waveform contains non-finite samples");

    // Spectrum: decimate by max-hold to <= bins points.
    const size_t nbins = sp.magnitude_dbv.size();
    const double df = sp.nfft > 0 ? sp.sample_rate_hz / sp.nfft : 0.0;
    const size_t group = std::max<size_t>(1, (nbins + static_cast<size_t>(bins) - 1) / static_cast<size_t>(bins));
    json freq = json::array(), mag = json::array();
    bool spec_nonfinite = false;
    for (size_t i = 0; i < nbins; i += group) {
      size_t best = i;
      for (size_t k = i; k < std::min(nbins, i + group); ++k) {
        if (!std::isfinite(sp.magnitude_dbv[k])) {
          spec_nonfinite = true;
          continue;
        }
        if (!std::isfinite(sp.magnitude_dbv[best]) || sp.magnitude_dbv[k] > sp.magnitude_dbv[best]) best = k;
      }
      freq.push_back(round_to(static_cast<double>(best) * df, 3));
      mag.push_back(finite_or_null(sp.magnitude_dbv[best]));
    }
    if (spec_nonfinite) warnings.push_back("spectrum contains non-finite bins");

    auto metric = [&](Measurement m, const std::string& key, const std::string& why_missing) -> json {
      if (!why_missing.empty()) {
        warnings.push_back(key + " unavailable: " + why_missing);
        return nullptr;
      }
      const double v = an.measure(m);
      if (!std::isfinite(v)) {
        warnings.push_back(key + " unavailable: instrument returned " + (std::isnan(v) ? "NaN" : "Inf"));
        return nullptr;
      }
      return v;
    };
    std::string why;
    if (!st.output) why = "generator output is OFF";
    else if (st.function != "SIN") why = "needs a sine stimulus (function is " + st.function + ")";
    json metrics = json::object();
    metrics["rms_v"] = metric(Measurement::Rms, "rms_v", "");
    metrics["gain_db"] = metric(Measurement::Gain, "gain_db", why);
    metrics["thd_percent"] = metric(Measurement::Thd, "thd_percent", why);
    metrics["snr_db"] = metric(Measurement::Snr, "snr_db", why);
    metrics["noise_floor_dbv"] = metric(Measurement::NoiseFloor, "noise_floor_dbv", "");
    const auto errs = an.client().read_errors();
    for (const auto& e : errs) warnings.push_back("instrument error " + std::to_string(e.code) + ": " + e.message);

    json out = json{
        {"timestamp", iso_now()},
        {"stimulus", json{{"function", st.function}, {"frequency_hz", st.frequency_hz}, {"amplitude_vpk", st.amplitude_vpk}, {"output", st.output}}},
        {"waveform", json{{"sample_rate_hz", as.sample_rate_hz}, {"unit", "V"}, {"samples", samples}}},
        {"spectrum", json{{"sample_rate_hz", sp.sample_rate_hz}, {"nfft", sp.nfft}, {"df_hz", round_to(df, 4)}, {"unit", "dBV"},
                          {"freq_hz", freq}, {"magnitude", mag}}},
        {"metrics", metrics},
        {"duration_ms", round_to(sw.elapsed_ms(), 2)},
        {"warnings", warnings}};
    send_json(res, 200, out);
  });
}

}  // namespace mf
