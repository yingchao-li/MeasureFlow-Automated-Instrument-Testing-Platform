import type { CalibrationStatus, HealthStatus, InstrumentState, LogLevel, RunStatus, TaskStatus } from '@/api/types';

export type Tone = 'success' | 'warn' | 'danger' | 'neutral' | 'info' | 'primary';

export interface StatusMeta {
  tone: Tone;
  label: string;
}

/** PASS green, FAIL amber (out of tolerance), ERROR red (communication / software), CANCELLED gray, RUNNING blue. */
export const RUN_STATUS: Record<RunStatus | TaskStatus, StatusMeta> = {
  PASS: { tone: 'success', label: 'PASS' },
  FAIL: { tone: 'warn', label: 'FAIL' },
  ERROR: { tone: 'danger', label: 'ERROR' },
  CANCELLED: { tone: 'neutral', label: 'CANCELLED' },
  RUNNING: { tone: 'info', label: 'RUNNING' },
  PENDING: { tone: 'neutral', label: 'PENDING' },
};

export const INSTRUMENT_STATE: Record<InstrumentState, StatusMeta> = {
  connected: { tone: 'success', label: 'Connected' },
  connecting: { tone: 'info', label: 'Connecting' },
  disconnected: { tone: 'neutral', label: 'Disconnected' },
  error: { tone: 'danger', label: 'Error' },
};

export const HEALTH_STATUS: Record<HealthStatus, StatusMeta> = {
  ok: { tone: 'success', label: 'Operational' },
  degraded: { tone: 'warn', label: 'Degraded' },
  down: { tone: 'danger', label: 'Down' },
};

export const CALIBRATION_STATUS: Record<CalibrationStatus, StatusMeta> = {
  valid: { tone: 'success', label: 'Calibration valid' },
  due_soon: { tone: 'warn', label: 'Calibration due soon' },
  expired: { tone: 'danger', label: 'Calibration expired' },
};

export const LEVEL_ORDER: Record<LogLevel, number> = { debug: 0, info: 1, warn: 2, error: 3 };

export function isRunActive(status: RunStatus | undefined | null): boolean {
  return status === 'RUNNING' || status === 'PENDING';
}

export const ERROR_CODE_HELP: Record<string, string> = {
  OUT_OF_TOLERANCE_LOW: 'Measured value is below the lower limit',
  OUT_OF_TOLERANCE_HIGH: 'Measured value is above the upper limit',
  COMM_TIMEOUT: 'The instrument did not answer in time',
  COMM_DISCONNECTED: 'The instrument connection was lost',
  COMM_INVALID_RESPONSE: 'The instrument answered with unparsable data',
  COMM_RESPONSE_TOO_LARGE: 'The instrument response exceeded the length limit',
  MEASUREMENT_NAN: 'The measurement returned NaN',
  MEASUREMENT_INF: 'The measurement returned infinity',
  INSTRUMENT_ERROR: 'The instrument reported an error in its queue',
  NOT_CONNECTED: 'The instrument was not connected',
  INTERNAL: 'Internal software error',
};
