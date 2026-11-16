# MeasureFlow — Interface Contract (v1.0)

This document is the **single source of truth** shared by the simulator, the C++ backend, the
frontend and the QA suite. If an implementation needs to deviate, change this file first and
tell the Lead. All numbers below are normative unless marked *(guideline)*.

```
React Frontend ──REST/JSON──▶ C++ Backend ──SCPI/TCP──▶ Python Virtual Instruments
 (Vite, :5173 dev)            (cpp-httplib, :8080)       siggen :5025 · analyzer :5026 · dut :5027
```

* All processes bind to `127.0.0.1` only. The backend **refuses** instrument hosts that are not
  loopback (`127.0.0.1`, `localhost`, `::1`) with `FORBIDDEN_HOST` and refuses to bind a non-loopback
  address unless `--unsafe-bind` is passed.
* Everything is simulated. Nothing here is certified for real hardware or medical devices.

## 1. Repository layout and ownership

| Path | Owner | Notes |
|---|---|---|
| `backend/` | C++ Engineer | CMake project, `third_party/` is vendored (do not edit) |
| `simulator/` | Simulation Engineer | Python package `mfsim`, tests in `simulator/tests/` |
| `frontend/` | Frontend Engineer | Vite app, Vitest component tests in `frontend/src/**/*.test.tsx` |
| `configs/` | Lead | `instruments.json`, `calibration.json`, `sequences/*.json` — read-only for others |
| `scripts/`, `.github/`, `docs/INTERFACE.md`, root files | Lead | |
| `tests/`, `experiments/`, `docs/EXPERIMENT_REPORT.md`, `screenshots/` | QA Engineer | integration/API/regression/E2E tests and E01–E10 |
| `results/`, `reports/` | runtime output | git-ignored except `.gitkeep` and the committed experiment results under `results/experiments/` |

Do not edit files owned by someone else; ask the Lead (write the request into your final report).
Do not run `git` commands (the Lead commits).

## 2. Ports and processes

| Process | Command | Port |
|---|---|---|
| Simulator | `python3 -m mfsim --host 127.0.0.1 --base-port 5025 --seed 12345` (run from `simulator/`) | siggen 5025, analyzer 5026, dut 5027 |
| Backend | `backend/build/measureflow_backend --root <repo> --port 8080` | 8080 (REST + static `frontend/dist`) |
| Frontend dev | `npm run dev` (Vite, proxies `/api` → `127.0.0.1:8080`) | 5173 |

The three simulated instruments share one in-process **Bench** (signal path
`SigGen → DUT → Analyzer`) so measurements are computed from really generated samples.
The simulator prints one line `READY siggen=5025 analyzer=5026 dut=5027` to stdout when all
sockets listen, and exits cleanly on SIGINT/SIGTERM.

## 3. SCPI protocol

Transport: TCP, ASCII, one command per line, terminator `\n` (a trailing `\r` is tolerated on
input; responses end with `\n` only). Commands are case-insensitive; SCPI long/short forms are
accepted (`SOURce:FREQuency` ≡ `SOUR:FREQ`). Queries end with `?` and produce exactly one response
line; setters produce **no** response. Errors never produce a response line; they are pushed on the
instrument's error queue and read with `SYST:ERR?` (`0,"No error"` when empty).
Numeric arguments are plain decimal/exponent floats. Response numbers use `%.9g`.
`NAN` / `INF` / `-INF` are valid textual responses (used by fault injection and by failed math).

Classification (documented in README — we do **not** claim compatibility with commercial instruments):

* **IEEE 488.2** — `*IDN? *RST *CLS *OPC? *TST?`
* **SCPI-style** — names follow SCPI conventions but semantics are simplified (e.g. `SOUR:VOLT` is the
  peak amplitude in volts, not Vpp).
* **Custom** — everything with the `MF:` prefix. Project specific.

Error codes used: `-102 Syntax error`, `-113 Undefined header`, `-104 Data type error`,
`-222 Data out of range`, `-221 Settings conflict`, `-230 Data corrupt or stale`, `-200 Execution error`,
`-350 Queue overflow`.

### 3.1 Common to all three instruments

| Command | Class | Response / effect |
|---|---|---|
| `*IDN?` | IEEE | `MeasureFlow,<model>,<serial>,<firmware>` — models `VSG-1000` (siggen), `VAA-2000` (analyzer), `VDUT-HA1` (dut); serials `SN-SIM-0001/2/3`; firmware `1.0.0` (siggen/analyzer) and the DUT firmware version for the dut |
| `*RST` | IEEE | restore defaults (below), clear fault injections, reset RNG seed/counter, invalidate stored acquisition |
| `*CLS` | IEEE | clear the error queue |
| `*OPC?` | IEEE | `1` |
| `*TST?` | IEEE | `0` (self-test OK) |
| `SYST:ERR?` | SCPI | `<code>,"<message>"`, oldest first, then `0,"No error"` |
| `SYST:VERS?` | SCPI | `1999.0` |
| `MF:SIM:VERS?` | Custom | simulator package version, e.g. `0.1.0` |
| `MF:FAULT:TIMEOUT <n>[,<delay_ms>]` | Custom | next `n` commands on **this** instrument server are answered only after `delay_ms` (default 5000) |
| `MF:FAULT:DISCONNECT <n>` | Custom | next `n` commands: close the connection without responding |
| `MF:FAULT:GARBAGE <n>` | Custom | next `n` *query responses* are replaced by non-parsable text (`#!GARBAGE~~`) |
| `MF:FAULT:FRAGMENT <n>[,<chunk>,<delay_ms>]` | Custom | next `n` responses are valid but sent in chunks (default 3 bytes, 15 ms apart) — exercises partial reads |
| `MF:FAULT:NAN <n>` / `MF:FAULT:INF <n>` | Custom | next `n` numeric query responses are replaced by `NAN` / `INF` |
| `MF:FAULT:OVERSIZE <n>` | Custom | next `n` query responses are padded to > 2 MiB (exercises the client response-length limit) |
| `MF:FAULT:CLEAR` | Custom | clear all injections |
| `MF:FAULT?` | Custom | e.g. `TIMEOUT=0,DISCONNECT=0,GARBAGE=0,FRAGMENT=0,NAN=0,INF=0,OVERSIZE=0` |

Fault counters are per instrument server, decrement per command, and are always evaluated
*after* the command has been parsed, except that `MF:FAULT:*` commands themselves are never faulted.

### 3.2 Signal generator (`siggen`, port 5025)

Defaults after `*RST`: `SIN`, 1000 Hz, 0.05 Vpk, 48000 Hz sample rate, output OFF.

| Command | Class | Range / meaning |
|---|---|---|
| `SOUR:FUNC SIN\|SQU\|CHIR\|NOIS` / `SOUR:FUNC?` | SCPI-style | waveform. `CHIR`: linear chirp `MF:SOUR:CHIR:START` (default 20 Hz) → `SOUR:FREQ`, once per acquisition window. `NOIS`: Gaussian white noise, σ = amplitude/3, clipped at ±amplitude |
| `SOUR:FREQ <Hz>` / `SOUR:FREQ?` | SCPI-style | 10 … 20000 Hz (−222 otherwise) |
| `SOUR:VOLT <Vpk>` / `SOUR:VOLT?` | SCPI-style | peak amplitude 0 … 5 V |
| `OUTP ON\|OFF\|1\|0` / `OUTP?` | SCPI-style | `OUTP?` → `1`/`0` |
| `MF:SOUR:SRAT <Hz>` / `MF:SOUR:SRAT?` | Custom | sample rate 8000 … 192000, default 48000 |
| `MF:SOUR:CHIR:START <Hz>` / `?` | Custom | chirp start frequency |
| `MF:SOUR:CONF?` | Custom | `<func>,<freq_hz>,<amp_vpk>,<srate_hz>,<output 0/1>` e.g. `SIN,1000,0.05,48000,0` |

### 3.3 Audio analyzer (`analyzer`, port 5026)

Defaults after `*RST`: `points = 16384`. The analyzer measures the **DUT output** (signal path
`SigGen → DUT → Analyzer`). When the generator output is OFF the DUT sees silence (only DUT noise appears).

Acquisition model: `MF:ACQ:INIT` renders a fresh buffer of `points` samples (new noise realization,
derived deterministically from seed + acquisition counter) and stores it together with the stimulus
reference. `MEAS:*?`, `MF:ACQ:WAV?`, `MF:ACQ:FFT?` all operate on the **stored** acquisition; if none is stored
(first query after `*RST` or after any generator/DUT/analyzer configuration change) they auto-acquire once.
Repeated `MEAS:*?` without `MF:ACQ:INIT` therefore return identical values.

| Command | Class | Response |
|---|---|---|
| `MF:ACQ:POIN <n>` / `?` | Custom | 1024 … 65536 (power of two), default 16384 |
| `MF:ACQ:SEED <int>` / `?` | Custom | RNG seed (default 12345); also resets the acquisition counter |
| `MF:ACQ:INIT` | Custom | acquire and store a buffer (use `*OPC?` after to synchronise) |
| `MF:ACQ:CONF?` | Custom | `<points>,<srate_hz>,<stored 0/1>,<acq_counter>` |
| `MF:ACQ:WAV? [n]` | Custom | first `n` samples (default 512, max `points`) of the stored DUT output in volts, comma separated, 6 significant digits |
| `MF:ACQ:FFT? [m]` | Custom | single-sided amplitude spectrum of the stored buffer: `<srate_hz>,<nfft>,<d0>,<d1>,…` where `d_k` = dBV (peak amplitude, coherent-gain-compensated) of bin `k`, bin width = `srate/nfft`, `m` caps the number of bins returned (default `nfft/2+1`) |
| `MEAS:RMS?` | SCPI-style | time-domain RMS of the DUT output in V (all spectral content) |
| `MEAS:GAIN?` | SCPI-style | dB = 20·log10(V_fund_out / V_fund_in) from windowed-FFT fundamental estimates; needs `SIN` + output ON, else `-221` and `NAN` |
| `MEAS:THD?` | SCPI-style | **percent**: √(Σ H2…H10 amplitude²) / fundamental × 100; same preconditions |
| `MEAS:SNR?` | SCPI-style | dB = fundamental power / in-band noise power (20 Hz … 20 kHz, tone and harmonics H2–H10 excluded); same preconditions |
| `MEAS:NOIS?` | Custom-name | in-band (20 Hz … 20 kHz) noise level in **dBV RMS**, tone ± window and harmonics excluded (if the output is OFF nothing is excluded). Works for any stimulus |
| `MEAS:FREQ?` | SCPI-style | estimated fundamental frequency (Hz) of the DUT output |
| `MF:ANAL:WIN?` | Custom | window name, e.g. `FLATTOP` |

Accuracy target *(guideline, QA verifies and reports the real numbers)*: gain error < 0.05 dB, THD within
±2 % relative (or ±0.005 %-points), SNR/noise within ±0.5 dB, for default settings.

### 3.4 Device under test (`dut`, port 5027) — simplified hearing-aid chain

Signal chain (applied to the generator samples): `input → gain → polynomial nonlinearity
y = u + hd2·u² + hd3·u³ → hard clip at ±clip_vpk → high-pass (2nd order Butterworth) → low-pass (4th order
Butterworth) → + white Gaussian output noise`. Noise RMS = 10^(noise_dbv/20) V over the **full Nyquist band**
(so in-band 20 Hz–20 kHz noise at fs=48 kHz is `noise_dbv + 10·log10(19980/24000)` dBV).

Defaults after `*RST`: profile `NORMAL`, firmware `1.0.0`.

| Profile | gain_db | hpf_hz | lpf_hz | noise_dbv | hd2 | hd3 | clip_vpk | Expected symptom @1 kHz, 0.05 Vpk |
|---|---|---|---|---|---|---|---|---|
| `NORMAL` | 20 | 100 | 8000 | −80 | 0.004 | 0.01 | 1.5 | gain ≈ 20 dB, THD ≈ 0.1–0.2 %, SNR ≈ 70 dB, noise ≈ −81 dBV |
| `LOWGAIN` | 14 | 100 | 8000 | −80 | 0.004 | 0.01 | 1.5 | gain ≈ 14 dB → FAIL gain/RMS |
| `HIGHTHD` | 20 | 100 | 8000 | −80 | 0.10 | 0.30 | 1.5 | THD ≈ 3 % → FAIL THD |
| `NOISY` | 20 | 100 | 8000 | −50 | 0.004 | 0.01 | 1.5 | SNR ≈ 41 dB, noise ≈ −51 dBV → FAIL SNR/noise |
| `CLIPPING` | 20 | 100 | 8000 | −80 | 0.004 | 0.01 | 0.3 | output hard-clipped → large THD, low RMS |

Firmware versions (`MF:DUT:FW <ver>`, accepted: `1.0.0`, `1.1.0`, `1.2.0`; anything else → `-224`/`-222`):
`1.0.0` baseline; `1.1.0` maintenance release (slightly lower noise, hd2 × 0.8); `1.2.0` **regression build**
(NORMAL profile must give THD between 1.5 % and 3 % and noise ≈ +4…6 dB vs 1.0.0 → fails the 1 % THD limit
while gain still passes). Firmware modifies the *effective* parameters on top of the profile; the
configured values reported by `MF:DUT:CONF?` stay those of the profile.

| Command | Class | Range / meaning |
|---|---|---|
| `MF:DUT:PROF NORMAL\|LOWGAIN\|HIGHTHD\|NOISY\|CLIPPING` / `?` | Custom | load preset (keeps firmware); `?` returns `CUSTOM` after any individual parameter change |
| `MF:DUT:GAIN <dB>` / `?` | Custom | −20 … 60 |
| `MF:DUT:HPF <Hz>` / `?` | Custom | 20 … 1000 |
| `MF:DUT:LPF <Hz>` / `?` | Custom | 1000 … 20000 |
| `MF:DUT:NOISE <dBV>` / `?` | Custom | −140 … 0 |
| `MF:DUT:HD2 <c>` / `?`, `MF:DUT:HD3 <c>` / `?` | Custom | 0 … 1 |
| `MF:DUT:CLIP <Vpk>` / `?` | Custom | 0.01 … 10 |
| `MF:DUT:FW <ver>` / `MF:DUT:FW?` | Custom | simulated firmware version |
| `MF:DUT:FAULT NONE\|NAN\|INF` / `?` | Custom | inject NaN/Inf samples into the DUT output (analyzer then answers `NAN` and queues `-230`) |
| `MF:DUT:CONF?` | Custom | `<profile>,<gain_db>,<hpf_hz>,<lpf_hz>,<noise_dbv>,<hd2>,<hd3>,<clip_vpk>,<firmware>` |

### 3.5 Analytic truth (for QA experiment E02)

The simulator package exposes `mfsim.truth` with pure-formula expectations (independent of the FFT
estimators): fundamental amplitude `U·(1+¾·hd3·U²)` (no clipping), `HD2 = hd2·U²/2`, `HD3 = hd3·U³/4`,
filter magnitude responses from `scipy.signal`, noise in-band level, etc.

### 3.6 Simulator behaviour as implemented (normative clarifications, added after the simulator landed)

1. A query that **fails** (syntax, undefined header, range, …) sends **no** response line, so a client waits for its read timeout and then reads `SYST:ERR?`.
   Only the `MEAS:*?` preconditions (`-221`) and non-finite DUT output (`-230`) answer `NAN`. `MF:ACQ:WAV?`/`FFT?` also queue `-230` when non-finite samples are returned.
2. Unknown keyword → `-224`; a number where a keyword is expected → `-222`; wrong argument count → `-102`. A tab is accepted as separator; `;` command chaining is **not** supported.
3. `MF:FAULT:DISCONNECT` closes the connection *without executing* the command. `MF:FAULT:TIMEOUT` executes the command, then delays the response (and everything behind it on that connection).
4. `*RST` resets that instrument's defaults, clears its fault injections, restores the seed given at start-up (`--seed`), zeroes the acquisition counter and drops the stored acquisition; it does **not** clear the error queue (use `*CLS`). The analyzer's `*RST` also restores 16384 points.
5. NORMAL profile @ 1 kHz / 0.05 Vpk gives SNR ≈ 71.8 dB, in-band noise ≈ −80.8 dBV, THD ≈ 0.118 %, gain ≈ 20.02 dB. Firmware 1.2.0 multipliers: hd2 ×20, hd3 ×3, noise +5 dB (NORMAL THD ≈ 2.0 %). Firmware multipliers are applied to *every* profile, so e.g. HIGHTHD + 1.2.0 is extreme (THD ≈ 43 %) — use firmware regression tests with NORMAL.
6. The in-band noise estimate compensates for the bins excluded around the tone and H2–H10. Window: 7-term flat-top (HFT144D), reported by `MF:ANAL:WIN?` as `FLATTOP`.
7. `mfsim.truth` raises `ClippingError` when the hard clip is reached (no closed form).
8. The server sets `TCP_NODELAY`/`TCP_QUICKACK`; clients should set `TCP_NODELAY` too. Simulator CLI extras: `--base-port 0` (free ports), `--unsafe-bind`.

## 4. Configuration files (Lead-owned)

* `configs/instruments.json` — instrument list (`id`, `name`, `kind`, `host`, `port`, `timeout_ms`,
  `connect_timeout_ms`, `max_retries`), plus `max_response_bytes` (default 1 048 576) and `config_version`.
* `configs/calibration.json` — simulated calibration records (`instrument_id`, `certificate`,
  `calibrated_on` ISO date, `valid_days`, `simulated: true`). Status: `valid` (> 30 days left),
  `due_soon` (≤ 30), `expired`. Expired calibration → health `degraded` + warning log, never blocks runs.
* `configs/sequences/*.json` — test sequences (schema in §6).

## 5. REST API (backend, `http://127.0.0.1:8080`)

JSON, UTF-8, `Content-Type: application/json`. Timestamps are ISO-8601 UTC with milliseconds
(`2026-11-16T17:21:29.043Z`). Durations are milliseconds (number). Unknown JSON fields in request bodies
are rejected with `INVALID_ARGUMENT` (strict validation). CORS allows `http://127.0.0.1:5173` and
`http://localhost:5173` only.

**Unified error body** (all non-2xx):

```json
{"error":{"code":"INVALID_ARGUMENT","message":"frequency_hz must be within [10, 20000]","details":{"field":"frequency_hz"}}}
```

| `code` | HTTP | Meaning |
|---|---|---|
| `INVALID_ARGUMENT` | 400 | malformed JSON, missing/unknown/out-of-range fields |
| `FORBIDDEN_HOST` | 403 | non-loopback host requested |
| `NOT_FOUND` | 404 | unknown instrument/sequence/run/report |
| `NOT_CONNECTED` | 409 | instrument not connected |
| `INSTRUMENT_BUSY` | 409 | instrument leased by a running test |
| `CONFLICT` | 409 | e.g. a test is already running; disconnect during a run |
| `COMMUNICATION_ERROR` | 502 | SCPI error: disconnected, invalid response, too large (`details.kind`) |
| `TIMEOUT` | 504 | SCPI timeout after retries |
| `INTERNAL` | 500 | unexpected |

### 5.1 `GET /api/health`
```json
{"status":"ok","version":"0.1.0","time":"…","uptime_s":12.3,
 "instruments_online":3,"instruments_total":3,"running_test":null,
 "software":{"backend":"0.1.0","simulator":"0.1.0","config_version":"1.0.0"},
 "checks":[{"name":"results_dir_writable","status":"ok","detail":"…"}]}
```
`status`: `ok` (all checks ok), `degraded` (any warning: instrument offline, calibration due/expired, simulator not
reachable), `down` (results dir not writable or configs unreadable). Cheap (cached ≤ 2 s). `running_test` is a run id or `null`.

### 5.2 `GET /api/environment`
Full Test Environment Manager report (runs the checks now):
```json
{"software":{"backend":"0.1.0","simulator":"0.1.0","config_version":"1.0.0","compiler":"GNU 13.3.0","api_version":"1.0"},
 "instruments":[{"id":"dut","idn":"MeasureFlow,VDUT-HA1,SN-SIM-0003,1.0.0","firmware":"1.0.0","state":"connected"}],
 "calibration":[{"instrument_id":"siggen","certificate":"SIM-CAL-0001","calibrated_on":"2026-10-01","due":"2027-10-01","days_remaining":319,"status":"valid","simulated":true}],
 "dependencies":[{"name":"simulator_siggen_port","status":"ok","detail":"127.0.0.1:5025 reachable"}],
 "history":{"runs":12,"tasks":340,"first_run":"…","last_run":"…"},
 "config":{"instruments_version":"1.0.0","sequences":7}}
```
`status` ∈ `ok|warn|fail`.

### 5.3 `GET /api/instruments`
```json
{"instruments":[{"id":"siggen","name":"Virtual Signal Generator","kind":"signal_generator",
  "host":"127.0.0.1","port":5025,"state":"connected","idn":"MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0",
  "firmware":"1.0.0","last_error":null,"last_seen":"…","latency_ms":0.8,"leased_by":null,
  "calibration":{"status":"valid","due":"2027-10-01","days_remaining":319},
  "settings":{"function":"SIN","frequency_hz":1000,"amplitude_vpk":0.05,"sample_rate_hz":48000,"output":false}}]}
```
`kind` ∈ `signal_generator|audio_analyzer|device_under_test`; `state` ∈ `disconnected|connecting|connected|error`.
`settings` is `null` unless connected. Analyzer settings: `{"points":16384,"sample_rate_hz":48000,"acquisition_stored":false}`.
DUT settings: `{"profile":"NORMAL","gain_db":20,"hpf_hz":100,"lpf_hz":8000,"noise_dbv":-80,"hd2":0.004,"hd3":0.01,"clip_vpk":1.5,"firmware":"1.0.0"}`.
`leased_by` = run id while a test owns the instrument.

### 5.4 `POST /api/instruments/connect` — body `{"id":"siggen"}` (`id` may be `"all"`; optional `host`, `port` override, loopback only)
→ `200 {"instruments":[…]}` (same objects as above, only the affected ones). Connect failure → 502/504 and state `error` with `last_error`.

### 5.5 `POST /api/instruments/disconnect` — body `{"id":"siggen"|"all"}`
Best effort: switches the generator output OFF before closing. `409 CONFLICT` while a test runs. → `200 {"instruments":[…]}`.

### 5.6 `POST /api/instruments/command` — body `{"id":"siggen","command":"SOUR:FREQ 1000"}`
`command`: 1–512 printable ASCII chars, no newline. Query iff it ends with `?`.
→ `200 {"id":"siggen","command":"…","is_query":true,"response":"1000","duration_ms":1.7,"timestamp":"…","error":null}`
(`response` is `null` for setters; a response longer than 4096 chars is truncated in the JSON and `"truncated":true` is added).
`error` = first entry of `SYST:ERR?` read after a setter when non-zero, e.g. `{"code":-222,"message":"Data out of range"}`.
Errors: `NOT_CONNECTED`, `INSTRUMENT_BUSY`, `TIMEOUT`, `COMMUNICATION_ERROR`.

### 5.7 `POST /api/instruments/configure` — typed configuration (validated, mapped to SCPI by the backend)
Body: `{"id":"siggen","settings":{"function":"SIN","frequency_hz":1000,"amplitude_vpk":0.05,"output":true}}` or
`{"id":"dut","settings":{"profile":"HIGHTHD","firmware":"1.2.0","gain_db":18}}` or `{"id":"analyzer","settings":{"points":8192}}`.
Allowed keys = the keys of the `settings` objects in §5.3 (read-only ones excluded); ranges as in §3. → `200 {"instrument":{…}}`.

### 5.8 `GET /api/measurements/live?points=512&bins=1024`
One coherent acquisition (`MF:ACQ:INIT` + `WAV?` + `FFT?` + scalar `MEAS:*`) through the analyzer.
```json
{"timestamp":"…","stimulus":{"function":"SIN","frequency_hz":1000,"amplitude_vpk":0.05,"output":true},
 "waveform":{"sample_rate_hz":48000,"unit":"V","samples":[0.0,…]},
 "spectrum":{"sample_rate_hz":48000,"nfft":16384,"df_hz":2.93,"unit":"dBV","freq_hz":[…],"magnitude":[…]},
 "metrics":{"rms_v":0.353,"gain_db":19.98,"thd_percent":0.12,"snr_db":70.1,"noise_floor_dbv":-80.9},
 "duration_ms":6.2,"warnings":[]}
```
`points` 16…4096 (default 512), `bins` 16…8192 (default 1024; spectrum decimated by max-hold to ≤ `bins` points).
A metric that is not available (generator off, non-sine stimulus, NaN) is `null` and a human readable `warnings[]` entry is added.
`409 NOT_CONNECTED` if siggen/analyzer/dut is not connected, `409 INSTRUMENT_BUSY` while a test runs.

### 5.9 `GET /api/sequences`
```json
{"sequences":[{"id":"gain_verification","name":"Gain Verification","version":"1.0.0","description":"…",
  "parameters":[{"key":"frequency_hz","label":"Frequency","unit":"Hz","default":1000,"min":20,"max":20000}],
  "dut":{"profile":"NORMAL","firmware":"1.0.0"},
  "steps":[{"id":"init","type":"init","name":"Initialize instruments"}]}]}
```
`parameters[]` is the declared parameter list of the sequence (§6) — tolerance parameters included.

### 5.10 `POST /api/tests/run`
```json
{"sequence_id":"gain_verification",
 "parameters":{"frequency_hz":1000,"gain_min_db":19.0},
 "dut":{"profile":"LOWGAIN","firmware":"1.2.0"},
 "retries":2,"label":"nightly"}
```
All but `sequence_id` optional. `parameters` keys must be declared by the sequence and within [min,max]; `retries` 0…5
(task-level retries on communication ERROR, default 1); `label` ≤ 64 chars. `dut` overrides the sequence default.
→ `202 {"run":<run summary>}`. `409 CONFLICT` if a run is active (**only one run at a time; instruments are leased exclusively**).
`409 NOT_CONNECTED` is **not** returned — the run's init step connects (and fails with run status `ERROR` if it cannot).

### 5.11 `POST /api/tests/cancel` — body `{"run_id":"…"}` (optional, default = active run)
→ `200 {"run":{…}}` immediately with `status` `RUNNING` and `"cancel_requested":true`; the run reaches `CANCELLED` shortly after
(cleanup always executes: output OFF, lease released). `404` if no such run, `409 CONFLICT` if already finished.

### 5.12 `GET /api/tests/status?run_id=…&log_tail=100`
`run_id` default = active run, else the most recently finished one. → `200 {"run":<run detail>|null}`.

Run summary: `{"run_id","sequence_id","sequence_name","label","status","progress","current_step","cancel_requested",
"created_at","started_at","finished_at","duration_ms","dut":{"profile","firmware"},"retries","counts":{"PASS":0,"FAIL":0,"ERROR":0,"CANCELLED":0,"PENDING":0,"RUNNING":0},"error":null|{"code","message"}}`.
`progress` ∈ [0,1] = completed measurement tasks (+ non-measure steps) / planned.
Run detail = summary + `"parameters":{…}`, `"steps":[{"id","name","type","status","started_at","duration_ms","message"}]`,
`"tasks":[<task>…]` (so far), `"log":[<log entry>…]` (last `log_tail` entries of this run).
Run status: `PENDING|RUNNING|PASS|FAIL|ERROR|CANCELLED`. Precedence at completion: `CANCELLED` (if cancelled) > `ERROR` (any task ERROR or aborted step) > `FAIL` (any task FAIL) > `PASS`.

Task:
```json
{"task_id":"run-20261116-172129-a1b2-T003","run_id":"…","step_id":"thd","test_name":"THD @ 1000 Hz","kind":"thd",
 "status":"PASS","inputs":{"frequency_hz":1000,"amplitude_vpk":0.05,"function":"SIN"},
 "measured":{"value":0.123,"unit":"%"},"limits":{"min":null,"max":1.0,"unit":"%"},
 "duration_ms":14.2,"timestamp":"…","attempts":1,"message":"within limits","error_code":null,
 "dut_profile":"NORMAL","dut_firmware":"1.0.0"}
```
`kind` ∈ `rms|gain|thd|snr|noise_floor|freq_sweep` (sweep points have kind `freq_sweep` and `inputs.measurement` = `gain`).
`measured` is `null` when status is `ERROR`/`CANCELLED`. `error_code` for ERROR ∈ `COMM_TIMEOUT|COMM_DISCONNECTED|COMM_INVALID_RESPONSE|COMM_RESPONSE_TOO_LARGE|MEASUREMENT_NAN|MEASUREMENT_INF|INSTRUMENT_ERROR|NOT_CONNECTED|INTERNAL`;
for FAIL ∈ `OUT_OF_TOLERANCE_LOW|OUT_OF_TOLERANCE_HIGH`; otherwise `null`.
`FAIL` = a valid finite measurement outside limits. `ERROR` = communication or software problem, or a non-finite/invalid measurement. These must never be conflated.

Log entry: `{"seq":123,"ts":"…","level":"info","source":"engine","message":"…","fields":{…}}`.

### 5.13 `GET /api/tests/results?limit=100&offset=0&run_id=&sequence_id=&status=&kind=&firmware=&profile=`
Persisted history (newest first). → `{"total":340,"limit":100,"offset":0,"results":[<task>…]}`. `limit` 1…1000.
Also `GET /api/tests/runs?limit=50&offset=0&status=&sequence_id=` → `{"total":12,"runs":[<run summary>…]}`.

### 5.14 `GET /api/reports` , `GET /api/reports/{run_id}.{csv|html|pdf}` , `GET /api/reports/summary`
* `GET /api/reports` → `{"reports":[{"run_id","sequence_id","sequence_name","status","created_at","counts":{…},"files":{"csv":"/api/reports/<id>.csv","html":"…","pdf":"…"}}]}` (newest first). A report is generated for every finished run (also when `report` step is absent) — CSV, HTML (self-contained, inline CSS) and PDF (hand-written minimal PDF, text + tables).
* Download endpoints return `text/csv`, `text/html; charset=utf-8`, `application/pdf` with `Content-Disposition: attachment; filename="<run_id>.<ext>"`. `404` for unknown ids; `run_id` must match `^[A-Za-z0-9._-]{1,64}$` (no path traversal).
* `GET /api/reports/summary?sequence_id=&limit=…` aggregated statistics over persisted history:
```json
{"generated_at":"…","runs":{"total":12,"PASS":8,"FAIL":2,"ERROR":1,"CANCELLED":1},
 "tasks":{"total":340,"PASS":300,"FAIL":30,"ERROR":10,"CANCELLED":0,"pass_rate":0.882},
 "by_kind":{"gain":{"count":40,"pass":36,"fail":4,"error":0,"mean":19.96,"std":0.31,"min":14.0,"max":20.1,"unit":"dB"}},
 "by_firmware":[{"firmware":"1.0.0","tasks":120,"pass":118,"fail":1,"error":1,"pass_rate":0.983,
                 "by_kind":{"thd":{"count":10,"mean":0.12,"std":0.01,"min":0.1,"max":0.14,"unit":"%"}}}],
 "failure_reasons":[{"reason":"OUT_OF_TOLERANCE_HIGH","count":12},{"reason":"COMM_TIMEOUT","count":3}],
 "recovery":{"tasks_with_retry":5,"recovered":4,"unrecovered":1,"recovery_rate":0.8},
 "trend":[{"timestamp":"…","run_id":"…","kind":"gain","value":19.96,"unit":"dB","status":"PASS","firmware":"1.0.0"}]}
```
`trend` holds at most the last 500 measured tasks (oldest first).

### 5.15 `GET /api/logs?limit=200&level=&source=&since_seq=0`
Ring buffer of the structured log (also persisted as JSON lines in `results/logs/measureflow.jsonl`).
→ `{"logs":[{"seq","ts","level","source","message","fields"}],"last_seq":123}`; oldest-first within the page; when more than `limit` entries match, the **newest** `limit` are returned (older ones are cut); `source` ∈
`api|scpi|engine|env|system`; `level` ∈ `debug|info|warn|error`. SCPI traffic is logged with `source:"scpi"`,
`fields:{"instrument":"siggen","direction":"TX"|"RX","text":"SOUR:FREQ 1000","duration_ms":0.4}`; communication errors have
`level:"error"` and `fields.kind`.

## 6. Test sequence files (`configs/sequences/*.json`)

```json
{"id":"gain_verification","name":"Gain Verification","version":"1.0.0","description":"…",
 "dut":{"profile":"NORMAL","firmware":"1.0.0"},
 "parameters":{"frequency_hz":{"label":"Frequency","unit":"Hz","default":1000,"min":20,"max":20000}},
 "steps":[ … ]}
```
`${name}` anywhere a **whole JSON string value** is a template referencing a declared parameter is replaced by the
(numeric) parameter value. Step types:

| `type` | Fields | Behaviour |
|---|---|---|
| `init` | `instruments` | connect if needed (with retries) → `*CLS`, `*RST`, `*IDN?` (record firmware), drain `SYST:ERR?` |
| `configure_signal` | `function`, `frequency_hz`, `amplitude_vpk`, `sample_rate_hz?`, `output` (bool), `settle_ms?` | sets generator, optional output ON |
| `configure_dut` | `settings?` (same keys as §5.7 dut, applied *after* profile/firmware) | applies the effective `dut.profile`/`dut.firmware` (sequence default overridden by the run request), then `settings` |
| `measure` | `measurement` (`rms|gain|thd|snr|noise_floor`), `name`, `limits{min,max,unit}` | `MF:ACQ:INIT`, `*OPC?`, `MEAS:*?`, validation → one task |
| `sweep` | `measurement` (`gain`), `points_hz[]`, `amplitude_vpk`, `limits{min,max,unit}`, `name` | one task per point (sets frequency, acquires, measures) |
| `cleanup` | – | generator output OFF, drain `SYST:ERR?`; also executed automatically on cancel/error/exception |
| `report` | – | write CSV/HTML/PDF report for the run |

`limits.min`/`limits.max` may be `null` (open bound) or a template. Units: rms `V`, gain `dB`, thd `%`, snr `dB`, noise_floor `dBV`.
Validation order per measurement: response must be a finite number (else ERROR `MEASUREMENT_NAN/INF`); after
`SYST:ERR?` non-empty → ERROR `INSTRUMENT_ERROR`; then limits (FAIL) else PASS.
Retry policy: a communication ERROR is retried up to `retries` times at task level after an automatic reconnect
(`attempts` counts tries); the SCPI client additionally retries idempotent commands `max_retries` times with short backoff.
FAIL results are never retried.

## 7. Persistence (no database)

```
results/runs/<run_id>/run.json        full run detail incl. tasks, steps, parameters
results/runs/<run_id>/results.csv     one row per task
results/runs/<run_id>/run.log         per-run log (text)
results/logs/measureflow.jsonl        structured global log (JSON lines, rotated at 5 MiB, keep 3)
reports/<run_id>.csv|html|pdf         generated reports
```
`run_id = run-YYYYMMDD-HHMMSS-xxxx` (UTC, 4 hex chars); `task_id = <run_id>-T<3-digit index>`.
Writes are atomic (temp file + rename). The history index is rebuilt by scanning `results/runs/` at startup.
`results.csv` header: `task_id,run_id,sequence_id,step_id,test_name,kind,status,value,unit,limit_min,limit_max,frequency_hz,amplitude_vpk,attempts,duration_ms,timestamp,dut_profile,dut_firmware,error_code,message`.

## 8. Build / quality bars

* C++17, `-Wall -Wextra -Wpedantic -Wshadow -Wconversion` clean; CMake options `MF_SANITIZE` (ASan+UBSan), `MF_COVERAGE` (gcov), `MF_WERROR`.
* Catch2 unit tests must run without external network or simulator (use in-process fake TCP servers).
* Python: `pytest -q simulator/tests`. Frontend: `npm run build` (tsc strict + vite), `npm test` (Vitest).
* Never fabricate results; never claim a test passed that was not run.
