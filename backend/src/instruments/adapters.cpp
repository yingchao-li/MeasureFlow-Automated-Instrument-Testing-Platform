#include "measureflow/instruments/adapters.hpp"

#include "measureflow/util/strings.hpp"

namespace mf {

std::string scpi_number(double v) { return format_g(v, 12); }

namespace {

template <typename T>
const T* find_in(const Settings& s, const std::string& key) {
  const auto it = s.find(key);
  if (it == s.end()) return nullptr;
  return std::get_if<T>(&it->second);
}

}  // namespace

// ---------------------------------------------------------------- base
Idn InstrumentAdapter::identify(const CallOptions& opts) {
  const std::string r = client_.query("*IDN?", opts, [](const std::string& s) { return parse_idn(s).has_value(); });
  return *parse_idn(r);
}

void InstrumentAdapter::check_error_queue(const std::string& context, const CallOptions& opts) {
  const auto errs = client_.read_errors(16, opts);
  if (!errs.empty()) {
    throw ScpiError(ScpiErrorKind::Instrument, client_.config().id, context,
                    "instrument error " + std::to_string(errs.front().code) + " \"" + errs.front().message + "\" (" + context + ")",
                    errs.front().code, errs.front().message);
  }
}

void InstrumentAdapter::check_error_queue(const std::string& context, const CallOptions& opts, const ConnectionEpoch& epoch) {
  check_error_queue(context, opts);
  epoch.verify(context);
}

void InstrumentAdapter::reset_to_defaults() {
  const ConnectionEpoch epoch(client_);
  client_.write("*CLS");  // *RST does not clear the error queue
  client_.write("*RST");
  check_error_queue("*RST", {}, epoch);
}

// ---------------------------------------------------------------- siggen
SigGenState SignalGeneratorAdapter::read_state(const CallOptions& opts) {
  SigGenState st;
  const std::string r = client().query("MF:SOUR:CONF?", opts, [](const std::string& s) {
    const auto f = split_fields(s);
    return f.size() == 5 && parse_finite_strict(f[1]) && parse_finite_strict(f[2]) && parse_finite_strict(f[3]) &&
           parse_bool_response(f[4]);
  });
  const auto f = split_fields(r);
  st.function = to_upper(f[0]);
  st.frequency_hz = *parse_finite_strict(f[1]);
  st.amplitude_vpk = *parse_finite_strict(f[2]);
  st.sample_rate_hz = *parse_finite_strict(f[3]);
  st.output = *parse_bool_response(f[4]);
  return st;
}

Settings SignalGeneratorAdapter::read_settings(const CallOptions& opts) {
  const SigGenState s = read_state(opts);
  return Settings{{"function", s.function},
                  {"frequency_hz", s.frequency_hz},
                  {"amplitude_vpk", s.amplitude_vpk},
                  {"sample_rate_hz", s.sample_rate_hz},
                  {"output", s.output}};
}

void SignalGeneratorAdapter::apply_settings(const Settings& settings, const CallOptions& opts) {
  const ConnectionEpoch epoch(client());
  if (const auto* v = find_in<std::string>(settings, "function")) client().write("SOUR:FUNC " + *v, opts);
  if (const auto* v = find_in<double>(settings, "sample_rate_hz")) client().write("MF:SOUR:SRAT " + scpi_number(*v), opts);
  if (const auto* v = find_in<double>(settings, "frequency_hz")) client().write("SOUR:FREQ " + scpi_number(*v), opts);
  if (const auto* v = find_in<double>(settings, "amplitude_vpk")) client().write("SOUR:VOLT " + scpi_number(*v), opts);
  if (const auto* v = find_in<bool>(settings, "output")) client().write(std::string("OUTP ") + (*v ? "ON" : "OFF"), opts);
  check_error_queue("siggen configure", opts, epoch);
}

void SignalGeneratorAdapter::set_output(bool on, const CallOptions& opts) {
  const ConnectionEpoch epoch(client());
  client().write(std::string("OUTP ") + (on ? "ON" : "OFF"), opts);
  check_error_queue("OUTP", opts, epoch);
}

// ---------------------------------------------------------------- analyzer
const char* to_string(Measurement m) {
  switch (m) {
    case Measurement::Rms: return "rms";
    case Measurement::Gain: return "gain";
    case Measurement::Thd: return "thd";
    case Measurement::Snr: return "snr";
    case Measurement::NoiseFloor: return "noise_floor";
  }
  return "rms";
}

const char* measurement_unit(Measurement m) {
  switch (m) {
    case Measurement::Rms: return "V";
    case Measurement::Gain: return "dB";
    case Measurement::Thd: return "%";
    case Measurement::Snr: return "dB";
    case Measurement::NoiseFloor: return "dBV";
  }
  return "";
}

const char* measurement_command(Measurement m) {
  switch (m) {
    case Measurement::Rms: return "MEAS:RMS?";
    case Measurement::Gain: return "MEAS:GAIN?";
    case Measurement::Thd: return "MEAS:THD?";
    case Measurement::Snr: return "MEAS:SNR?";
    case Measurement::NoiseFloor: return "MEAS:NOIS?";
  }
  return "MEAS:RMS?";
}

std::optional<Measurement> parse_measurement(const std::string& s) {
  if (s == "rms") return Measurement::Rms;
  if (s == "gain") return Measurement::Gain;
  if (s == "thd") return Measurement::Thd;
  if (s == "snr") return Measurement::Snr;
  if (s == "noise_floor") return Measurement::NoiseFloor;
  return std::nullopt;
}

AnalyzerState AudioAnalyzerAdapter::read_state(const CallOptions& opts) {
  const std::string r = client().query("MF:ACQ:CONF?", opts, [](const std::string& s) {
    const auto f = split_fields(s);
    return f.size() == 4 && parse_finite_strict(f[0]) && parse_finite_strict(f[1]) && parse_bool_response(f[2]) &&
           parse_finite_strict(f[3]);
  });
  const auto f = split_fields(r);
  AnalyzerState st;
  st.points = static_cast<int>(*parse_finite_strict(f[0]));
  st.sample_rate_hz = *parse_finite_strict(f[1]);
  st.stored = *parse_bool_response(f[2]);
  st.counter = static_cast<long long>(*parse_finite_strict(f[3]));
  return st;
}

Settings AudioAnalyzerAdapter::read_settings(const CallOptions& opts) {
  const AnalyzerState s = read_state(opts);
  return Settings{{"points", static_cast<double>(s.points)}, {"sample_rate_hz", s.sample_rate_hz}, {"acquisition_stored", s.stored}};
}

void AudioAnalyzerAdapter::apply_settings(const Settings& settings, const CallOptions& opts) {
  const ConnectionEpoch epoch(client());
  if (const auto* v = find_in<double>(settings, "points")) client().write("MF:ACQ:POIN " + scpi_number(*v), opts);
  check_error_queue("analyzer configure", opts, epoch);
}

void AudioAnalyzerAdapter::acquire(const CallOptions& opts) {
  client().write("MF:ACQ:INIT", opts);
  client().query("*OPC?", opts, [](const std::string& s) { return trim(s) == "1"; });
}

double AudioAnalyzerAdapter::measure(Measurement m, const CallOptions& opts) { return client().query_double(measurement_command(m), opts); }

std::vector<double> AudioAnalyzerAdapter::waveform(int points, const CallOptions& opts) {
  const std::string r = client().query("MF:ACQ:WAV? " + std::to_string(points), opts,
                                       [](const std::string& s) { return parse_number_list(s).has_value(); });
  const std::vector<ParsedNumber> numbers = *parse_number_list(r);
  std::vector<double> out;
  out.reserve(numbers.size());
  for (const auto& n : numbers) out.push_back(n.value);
  return out;
}

SpectrumData AudioAnalyzerAdapter::spectrum(const CallOptions& opts) {
  const std::string r = client().query("MF:ACQ:FFT?", opts, [](const std::string& s) {
    const auto l = parse_number_list(s);
    return l && l->size() >= 3 && (*l)[0].is_finite() && (*l)[1].is_finite();
  });
  const auto l = *parse_number_list(r);
  SpectrumData sd;
  sd.sample_rate_hz = l[0].value;
  sd.nfft = static_cast<int>(l[1].value);
  sd.magnitude_dbv.reserve(l.size() - 2);
  for (size_t i = 2; i < l.size(); ++i) sd.magnitude_dbv.push_back(l[i].value);
  return sd;
}

// ---------------------------------------------------------------- DUT
DutState DutAdapter::read_state(const CallOptions& opts) {
  const std::string r = client().query("MF:DUT:CONF?", opts, [](const std::string& s) {
    const auto f = split_fields(s);
    if (f.size() != 9 || f[0].empty() || f[8].empty()) return false;
    for (size_t i = 1; i <= 7; ++i) {
      if (!parse_finite_strict(f[i])) return false;
    }
    return true;
  });
  const auto f = split_fields(r);
  DutState st;
  st.profile = to_upper(f[0]);
  st.gain_db = *parse_finite_strict(f[1]);
  st.hpf_hz = *parse_finite_strict(f[2]);
  st.lpf_hz = *parse_finite_strict(f[3]);
  st.noise_dbv = *parse_finite_strict(f[4]);
  st.hd2 = *parse_finite_strict(f[5]);
  st.hd3 = *parse_finite_strict(f[6]);
  st.clip_vpk = *parse_finite_strict(f[7]);
  st.firmware = f[8];
  return st;
}

Settings DutAdapter::read_settings(const CallOptions& opts) {
  const DutState s = read_state(opts);
  return Settings{{"profile", s.profile}, {"gain_db", s.gain_db}, {"hpf_hz", s.hpf_hz},     {"lpf_hz", s.lpf_hz},
                  {"noise_dbv", s.noise_dbv}, {"hd2", s.hd2},     {"hd3", s.hd3},           {"clip_vpk", s.clip_vpk},
                  {"firmware", s.firmware}};
}

void DutAdapter::apply_settings(const Settings& settings, const CallOptions& opts) {
  const ConnectionEpoch epoch(client());
  if (const auto* v = find_in<std::string>(settings, "profile")) client().write("MF:DUT:PROF " + *v, opts);
  if (const auto* v = find_in<std::string>(settings, "firmware")) client().write("MF:DUT:FW " + *v, opts);
  static const std::pair<const char*, const char*> numeric[] = {
      {"gain_db", "MF:DUT:GAIN"}, {"hpf_hz", "MF:DUT:HPF"}, {"lpf_hz", "MF:DUT:LPF"}, {"noise_dbv", "MF:DUT:NOISE"},
      {"hd2", "MF:DUT:HD2"},      {"hd3", "MF:DUT:HD3"},    {"clip_vpk", "MF:DUT:CLIP"}};
  for (const auto& n : numeric) {
    if (const auto* v = find_in<double>(settings, n.first)) client().write(std::string(n.second) + " " + scpi_number(*v), opts);
  }
  check_error_queue("dut configure", opts, epoch);
}

}  // namespace mf
