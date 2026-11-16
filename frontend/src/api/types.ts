/**
 * TypeScript mirror of the REST contract in docs/INTERFACE.md section 5.
 * Keep this file in lock-step with that document; do not add fields that the backend does not send.
 */

/* ----------------------------------------------------------------------------------------------
 * Errors (5, unified error body)
 * -------------------------------------------------------------------------------------------- */

export type BackendErrorCode =
  | 'INVALID_ARGUMENT'
  | 'FORBIDDEN_HOST'
  | 'NOT_FOUND'
  | 'NOT_CONNECTED'
  | 'INSTRUMENT_BUSY'
  | 'CONFLICT'
  | 'COMMUNICATION_ERROR'
  | 'TIMEOUT'
  | 'INTERNAL';

/** Codes that only the client can produce (no usable response from the backend). */
export type ClientErrorCode = 'NETWORK_ERROR' | 'CLIENT_TIMEOUT' | 'ABORTED' | 'BAD_RESPONSE';

export type ApiErrorCode = BackendErrorCode | ClientErrorCode;

export interface ErrorBody {
  error: {
    code: BackendErrorCode;
    message: string;
    details?: Record<string, unknown> | null;
  };
}

/* ----------------------------------------------------------------------------------------------
 * Health / environment (5.1, 5.2)
 * -------------------------------------------------------------------------------------------- */

export type HealthStatus = 'ok' | 'degraded' | 'down';
export type CheckStatus = 'ok' | 'warn' | 'fail';

export interface HealthCheck {
  name: string;
  status: CheckStatus;
  detail: string;
}

export interface SoftwareVersions {
  backend: string;
  simulator: string;
  config_version: string;
}

export interface Health {
  status: HealthStatus;
  version: string;
  time: string;
  uptime_s: number;
  instruments_online: number;
  instruments_total: number;
  running_test: string | null;
  software: SoftwareVersions;
  checks: HealthCheck[];
}

export interface Environment {
  software: SoftwareVersions & { compiler: string; api_version: string };
  instruments: Array<{ id: string; idn: string; firmware: string; state: InstrumentState }>;
  calibration: Array<{
    instrument_id: string;
    certificate: string;
    calibrated_on: string;
    due: string;
    days_remaining: number;
    status: CalibrationStatus;
    simulated: boolean;
  }>;
  dependencies: Array<{ name: string; status: CheckStatus; detail: string }>;
  history: { runs: number; tasks: number; first_run: string | null; last_run: string | null };
  config: { instruments_version: string; sequences: number };
}

/* ----------------------------------------------------------------------------------------------
 * Instruments (5.3 - 5.7)
 * -------------------------------------------------------------------------------------------- */

export type InstrumentKind = 'signal_generator' | 'audio_analyzer' | 'device_under_test';
export type InstrumentState = 'disconnected' | 'connecting' | 'connected' | 'error';
export type CalibrationStatus = 'valid' | 'due_soon' | 'expired';

export type SigGenFunction = 'SIN' | 'SQU' | 'CHIR' | 'NOIS';
export type DutProfile = 'NORMAL' | 'LOWGAIN' | 'HIGHTHD' | 'NOISY' | 'CLIPPING';
/** `MF:DUT:PROF?` answers CUSTOM after any individual parameter change (INTERFACE 3.4). */
export type DutProfileState = DutProfile | 'CUSTOM';
export type DutFirmware = '1.0.0' | '1.1.0' | '1.2.0';

export interface SigGenSettings {
  function: SigGenFunction;
  frequency_hz: number;
  amplitude_vpk: number;
  sample_rate_hz: number;
  output: boolean;
}

export interface AnalyzerSettings {
  points: number;
  sample_rate_hz: number;
  acquisition_stored: boolean;
}

export interface DutSettings {
  profile: DutProfileState;
  gain_db: number;
  hpf_hz: number;
  lpf_hz: number;
  noise_dbv: number;
  hd2: number;
  hd3: number;
  clip_vpk: number;
  firmware: string;
}

/**
 * Contract (5.3): `{status: valid|due_soon|expired, due, days_remaining}`.
 * MISMATCH handled here: for an instrument without a calibration record (the DUT) the backend sends
 * `{status:"none", due:null, days_remaining:null}` instead of omitting / nulling the object.
 */
export interface Calibration {
  status: CalibrationStatus | 'none';
  due: string | null;
  days_remaining: number | null;
}

interface InstrumentBase {
  id: string;
  name: string;
  host: string;
  port: number;
  state: InstrumentState;
  idn: string | null;
  firmware: string | null;
  last_error: string | null;
  last_seen: string | null;
  latency_ms: number | null;
  leased_by: string | null;
  calibration: Calibration | null;
}

export interface SigGenInstrument extends InstrumentBase {
  kind: 'signal_generator';
  settings: SigGenSettings | null;
}
export interface AnalyzerInstrument extends InstrumentBase {
  kind: 'audio_analyzer';
  settings: AnalyzerSettings | null;
}
export interface DutInstrument extends InstrumentBase {
  kind: 'device_under_test';
  settings: DutSettings | null;
}
export type Instrument = SigGenInstrument | AnalyzerInstrument | DutInstrument;

export interface InstrumentsResponse {
  instruments: Instrument[];
}

export interface ConnectRequest {
  id: string; // an instrument id or "all"
  host?: string;
  port?: number;
}
export interface DisconnectRequest {
  id: string;
}

export interface CommandRequest {
  id: string;
  command: string;
}
export interface CommandResponse {
  id: string;
  command: string;
  is_query: boolean;
  response: string | null;
  duration_ms: number;
  timestamp: string;
  error: { code: number; message: string } | null;
  truncated?: boolean;
}

export interface ConfigureRequest {
  id: string;
  settings: Record<string, string | number | boolean>;
}
export interface ConfigureResponse {
  instrument: Instrument;
}

/* ----------------------------------------------------------------------------------------------
 * Live measurement (5.8)
 * -------------------------------------------------------------------------------------------- */

export interface LiveMeasurement {
  timestamp: string;
  stimulus: { function: SigGenFunction; frequency_hz: number; amplitude_vpk: number; output: boolean };
  waveform: { sample_rate_hz: number; unit: string; samples: number[] };
  spectrum: {
    sample_rate_hz: number;
    nfft: number;
    df_hz: number;
    unit: string;
    freq_hz: number[];
    magnitude: number[];
  };
  metrics: {
    rms_v: number | null;
    gain_db: number | null;
    thd_percent: number | null;
    snr_db: number | null;
    noise_floor_dbv: number | null;
  };
  duration_ms: number;
  warnings: string[];
}

/* ----------------------------------------------------------------------------------------------
 * Sequences and runs (5.9 - 5.13)
 * -------------------------------------------------------------------------------------------- */

export interface SequenceParameter {
  key: string;
  label: string;
  unit: string;
  default: number;
  min: number;
  max: number;
}

export type StepType =
  | 'init'
  | 'configure_signal'
  | 'configure_dut'
  | 'measure'
  | 'sweep'
  | 'cleanup'
  | 'report';

export interface SequenceStep {
  id: string;
  type: StepType;
  name: string;
}

export interface Sequence {
  id: string;
  name: string;
  version: string;
  description: string;
  parameters: SequenceParameter[];
  dut: { profile: DutProfile; firmware: string };
  steps: SequenceStep[];
}
export interface SequencesResponse {
  sequences: Sequence[];
}

export interface RunRequest {
  sequence_id: string;
  parameters?: Record<string, number>;
  dut?: { profile?: DutProfile; firmware?: string };
  retries?: number;
  label?: string;
}

export type RunStatus = 'PENDING' | 'RUNNING' | 'PASS' | 'FAIL' | 'ERROR' | 'CANCELLED';
export type TaskStatus = 'PENDING' | 'RUNNING' | 'PASS' | 'FAIL' | 'ERROR' | 'CANCELLED';
/** The contract does not enumerate step statuses; they use the task status vocabulary. */
export type StepStatus = TaskStatus;

export interface RunCounts {
  PASS: number;
  FAIL: number;
  ERROR: number;
  CANCELLED: number;
  PENDING: number;
  RUNNING: number;
}

export interface RunSummary {
  run_id: string;
  sequence_id: string;
  sequence_name: string;
  label: string | null;
  status: RunStatus;
  progress: number;
  current_step: string | null;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  dut: { profile: string; firmware: string };
  retries: number;
  counts: RunCounts;
  error: { code: string; message: string } | null;
}

export interface RunStep {
  id: string;
  name: string;
  type: StepType;
  status: StepStatus;
  started_at: string | null;
  duration_ms: number | null;
  message: string | null;
}

export type MeasurementKind = 'rms' | 'gain' | 'thd' | 'snr' | 'noise_floor' | 'freq_sweep';

export type TaskErrorCode =
  | 'COMM_TIMEOUT'
  | 'COMM_DISCONNECTED'
  | 'COMM_INVALID_RESPONSE'
  | 'COMM_RESPONSE_TOO_LARGE'
  | 'MEASUREMENT_NAN'
  | 'MEASUREMENT_INF'
  | 'INSTRUMENT_ERROR'
  | 'NOT_CONNECTED'
  | 'INTERNAL'
  | 'OUT_OF_TOLERANCE_LOW'
  | 'OUT_OF_TOLERANCE_HIGH';

export interface TaskLimits {
  min: number | null;
  max: number | null;
  unit: string;
}

export interface Task {
  task_id: string;
  run_id: string;
  step_id: string;
  test_name: string;
  kind: MeasurementKind;
  status: TaskStatus;
  inputs: { frequency_hz?: number; amplitude_vpk?: number; function?: string; measurement?: string; [key: string]: unknown };
  measured: { value: number; unit: string } | null;
  limits: TaskLimits | null;
  duration_ms: number;
  timestamp: string;
  attempts: number;
  message: string | null;
  error_code: TaskErrorCode | null;
  dut_profile: string;
  dut_firmware: string;
}

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';
export type LogSource = 'api' | 'scpi' | 'engine' | 'env' | 'system';

export interface LogEntry {
  seq: number;
  ts: string;
  level: LogLevel;
  source: LogSource;
  message: string;
  fields?: Record<string, unknown> | null;
}

export interface RunDetail extends RunSummary {
  parameters: Record<string, number>;
  steps: RunStep[];
  tasks: Task[];
  log: LogEntry[];
}

export interface RunResponse {
  run: RunSummary;
}
export interface RunDetailResponse {
  run: RunDetail | null;
}

export interface TaskResultsResponse {
  total: number;
  limit: number;
  offset: number;
  results: Task[];
}
export interface RunsResponse {
  total: number;
  runs: RunSummary[];
}

export interface TaskResultsQuery {
  limit?: number;
  offset?: number;
  run_id?: string;
  sequence_id?: string;
  status?: string;
  kind?: string;
  firmware?: string;
  profile?: string;
}
export interface RunsQuery {
  limit?: number;
  offset?: number;
  status?: string;
  sequence_id?: string;
}

/* ----------------------------------------------------------------------------------------------
 * Reports and logs (5.14, 5.15)
 * -------------------------------------------------------------------------------------------- */

export interface ReportEntry {
  run_id: string;
  sequence_id: string;
  sequence_name: string;
  status: RunStatus;
  created_at: string;
  counts: RunCounts;
  files: { csv: string; html: string; pdf: string };
}
export interface ReportsResponse {
  reports: ReportEntry[];
}

export interface KindStats {
  count: number;
  pass: number;
  fail: number;
  error: number;
  mean: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
  unit: string;
}

export interface FirmwareKindStats {
  count: number;
  mean: number | null;
  std: number | null;
  min: number | null;
  max: number | null;
  unit: string;
}

export interface FirmwareStats {
  firmware: string;
  tasks: number;
  pass: number;
  fail: number;
  error: number;
  pass_rate: number;
  by_kind: Record<string, FirmwareKindStats>;
}

export interface TrendPoint {
  timestamp: string;
  run_id: string;
  kind: MeasurementKind;
  value: number;
  unit: string;
  status: TaskStatus;
  firmware: string;
}

export interface ReportSummary {
  generated_at: string;
  runs: { total: number; PASS: number; FAIL: number; ERROR: number; CANCELLED: number };
  tasks: { total: number; PASS: number; FAIL: number; ERROR: number; CANCELLED: number; pass_rate: number | null };
  by_kind: Record<string, KindStats>;
  by_firmware: FirmwareStats[];
  failure_reasons: Array<{ reason: string; count: number }>;
  recovery: {
    tasks_with_retry: number;
    recovered: number;
    unrecovered: number;
    recovery_rate: number | null;
  };
  trend: TrendPoint[];
}

export interface LogsResponse {
  logs: LogEntry[];
  last_seq: number;
}

export interface LogsQuery {
  limit?: number;
  level?: LogLevel;
  source?: LogSource;
  since_seq?: number;
}
