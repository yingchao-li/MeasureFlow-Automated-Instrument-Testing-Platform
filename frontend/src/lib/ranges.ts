/** Instrument setting ranges: INTERFACE.md section 3 (normative). */
export interface Range {
  min: number;
  max: number;
  unit: string;
}

export const SIGGEN_RANGES = {
  frequency_hz: { min: 10, max: 20000, unit: 'Hz' },
  amplitude_vpk: { min: 0, max: 5, unit: 'Vpk' },
  sample_rate_hz: { min: 8000, max: 192000, unit: 'Hz' },
} satisfies Record<string, Range>;

export const DUT_RANGES = {
  gain_db: { min: -20, max: 60, unit: 'dB' },
  hpf_hz: { min: 20, max: 1000, unit: 'Hz' },
  lpf_hz: { min: 1000, max: 20000, unit: 'Hz' },
  noise_dbv: { min: -140, max: 0, unit: 'dBV' },
  hd2: { min: 0, max: 1, unit: '' },
  hd3: { min: 0, max: 1, unit: '' },
  clip_vpk: { min: 0.01, max: 10, unit: 'Vpk' },
} satisfies Record<string, Range>;

export const SIGGEN_FUNCTIONS = [
  { value: 'SIN', label: 'Sine' },
  { value: 'SQU', label: 'Square' },
  { value: 'CHIR', label: 'Chirp' },
  { value: 'NOIS', label: 'Noise' },
] as const;

export const DUT_PROFILES = ['NORMAL', 'LOWGAIN', 'HIGHTHD', 'NOISY', 'CLIPPING'] as const;
export const DUT_FIRMWARES = ['1.0.0', '1.1.0', '1.2.0'] as const;
export const ANALYZER_POINTS = [1024, 2048, 4096, 8192, 16384, 32768, 65536] as const;

export const RUN_RETRIES = { min: 0, max: 5 } as const;
export const RUN_LABEL_MAX = 64;
