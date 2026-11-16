// Instrument adapters: the seam between the engine and the physical (here: simulated) instruments.
// Everything above this layer talks to `InstrumentAdapter`s; everything below is SCPI over `ScpiClient`.
// A real instrument driver would implement the same interface with its own command set.
#pragma once

#include <string>
#include <vector>

#include "measureflow/instruments/instrument_types.hpp"
#include "measureflow/scpi/scpi_client.hpp"
#include "measureflow/scpi/scpi_parse.hpp"
#include "measureflow/util/value.hpp"

namespace mf {

class InstrumentAdapter {
 public:
  InstrumentAdapter(InstrumentKind kind, ScpiClient& client) : kind_(kind), client_(client) {}
  virtual ~InstrumentAdapter() = default;
  InstrumentAdapter(const InstrumentAdapter&) = delete;
  InstrumentAdapter& operator=(const InstrumentAdapter&) = delete;

  InstrumentKind kind() const { return kind_; }
  ScpiClient& client() { return client_; }

  // *IDN? parsed (throws InvalidResponse when it does not have 4 fields)
  Idn identify(const CallOptions& opts = {});
  // *CLS, *RST, error-queue drain. Throws ScpiError(Instrument) when the queue is not empty after reset.
  void reset_to_defaults();
  // Reads the current configuration from the instrument.
  virtual Settings read_settings(const CallOptions& opts = {}) = 0;
  // Applies validated settings (see validate_settings) and checks the error queue once at the end.
  virtual void apply_settings(const Settings& settings, const CallOptions& opts = {}) = 0;
  // Bring the instrument into a safe state (generator output OFF). May throw ScpiError.
  virtual void safe_state(const CallOptions& opts = {}) { (void)opts; }

 protected:
  void check_error_queue(const std::string& context, const CallOptions& opts);
  // check_error_queue() plus verification that the connection was not re-established since `epoch` was taken.
  void check_error_queue(const std::string& context, const CallOptions& opts, const ConnectionEpoch& epoch);

 private:
  InstrumentKind kind_;
  ScpiClient& client_;
};

struct SigGenState {
  std::string function = "SIN";
  double frequency_hz = 1000;
  double amplitude_vpk = 0.05;
  double sample_rate_hz = 48000;
  bool output = false;
};

class SignalGeneratorAdapter : public InstrumentAdapter {
 public:
  explicit SignalGeneratorAdapter(ScpiClient& c) : InstrumentAdapter(InstrumentKind::SignalGenerator, c) {}
  SigGenState read_state(const CallOptions& opts = {});
  Settings read_settings(const CallOptions& opts = {}) override;
  void apply_settings(const Settings& settings, const CallOptions& opts = {}) override;
  void set_output(bool on, const CallOptions& opts = {});
  void safe_state(const CallOptions& opts = {}) override { set_output(false, opts); }
};

enum class Measurement { Rms, Gain, Thd, Snr, NoiseFloor };
const char* to_string(Measurement m);                       // "rms" "gain" "thd" "snr" "noise_floor"
const char* measurement_unit(Measurement m);                // "V" "dB" "%" "dB" "dBV"
const char* measurement_command(Measurement m);             // "MEAS:RMS?" ...
std::optional<Measurement> parse_measurement(const std::string& s);

struct AnalyzerState {
  int points = 16384;
  double sample_rate_hz = 48000;
  bool stored = false;
  long long counter = 0;
};

struct SpectrumData {
  double sample_rate_hz = 0;
  int nfft = 0;
  std::vector<double> magnitude_dbv;  // single-sided bins 0..nfft/2
};

class AudioAnalyzerAdapter : public InstrumentAdapter {
 public:
  explicit AudioAnalyzerAdapter(ScpiClient& c) : InstrumentAdapter(InstrumentKind::AudioAnalyzer, c) {}
  AnalyzerState read_state(const CallOptions& opts = {});
  Settings read_settings(const CallOptions& opts = {}) override;
  void apply_settings(const Settings& settings, const CallOptions& opts = {}) override;
  // MF:ACQ:INIT then *OPC? (must answer "1")
  void acquire(const CallOptions& opts = {});
  // Raw numeric response of MEAS:*? (NaN/Inf are returned as such, never thrown)
  double measure(Measurement m, const CallOptions& opts = {});
  std::vector<double> waveform(int points, const CallOptions& opts = {});
  SpectrumData spectrum(const CallOptions& opts = {});
};

struct DutState {
  std::string profile = "NORMAL";
  double gain_db = 20, hpf_hz = 100, lpf_hz = 8000, noise_dbv = -80, hd2 = 0.004, hd3 = 0.01, clip_vpk = 1.5;
  std::string firmware = "1.0.0";
};

class DutAdapter : public InstrumentAdapter {
 public:
  explicit DutAdapter(ScpiClient& c) : InstrumentAdapter(InstrumentKind::DeviceUnderTest, c) {}
  DutState read_state(const CallOptions& opts = {});
  Settings read_settings(const CallOptions& opts = {}) override;
  // Order: profile, firmware, then individual parameters (a profile load resets them).
  void apply_settings(const Settings& settings, const CallOptions& opts = {}) override;
};

// SCPI number formatting used for setters ("%.12g", locale independent).
std::string scpi_number(double v);

}  // namespace mf
