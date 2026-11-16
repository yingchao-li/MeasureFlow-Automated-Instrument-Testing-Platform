import type { InstrumentKind } from '@/api/types';

export interface ScpiCheck {
  ok: boolean;
  error: string | null;
}

/** Client-side mirror of the backend rule: 1-512 printable ASCII characters, no newline (INTERFACE 5.6). */
export function checkScpiCommand(command: string): ScpiCheck {
  const c = command.trim();
  if (c.length === 0) return { ok: false, error: 'Enter a command' };
  if (c.length > 512) return { ok: false, error: 'Command is longer than 512 characters' };
  if (!/^[\x20-\x7e]+$/.test(c)) return { ok: false, error: 'Only printable ASCII characters are allowed' };
  return { ok: true, error: null };
}

export function isQuery(command: string): boolean {
  return command.trim().endsWith('?');
}

export interface QuickCommand {
  label: string;
  command: string;
  hint?: string;
}

const COMMON: QuickCommand[] = [
  { label: '*IDN?', command: '*IDN?', hint: 'Identification' },
  { label: 'SYST:ERR?', command: 'SYST:ERR?', hint: 'Read the error queue' },
  { label: '*CLS', command: '*CLS', hint: 'Clear the error queue' },
  { label: '*RST', command: '*RST', hint: 'Restore defaults' },
  { label: '*OPC?', command: '*OPC?', hint: 'Operation complete' },
];

const BY_KIND: Record<InstrumentKind, QuickCommand[]> = {
  signal_generator: [
    { label: 'MF:SOUR:CONF?', command: 'MF:SOUR:CONF?', hint: 'Function, frequency, amplitude, sample rate, output' },
    { label: 'SOUR:FREQ ', command: 'SOUR:FREQ ', hint: 'Set frequency in Hz (10 to 20000)' },
    { label: 'SOUR:VOLT ', command: 'SOUR:VOLT ', hint: 'Set peak amplitude in V (0 to 5)' },
    { label: 'OUTP ON', command: 'OUTP ON', hint: 'Enable output' },
    { label: 'OUTP OFF', command: 'OUTP OFF', hint: 'Disable output' },
  ],
  audio_analyzer: [
    { label: 'MF:ACQ:INIT', command: 'MF:ACQ:INIT', hint: 'Acquire and store a buffer' },
    { label: 'MF:ACQ:CONF?', command: 'MF:ACQ:CONF?', hint: 'Points, sample rate, stored, counter' },
    { label: 'MEAS:RMS?', command: 'MEAS:RMS?' },
    { label: 'MEAS:GAIN?', command: 'MEAS:GAIN?' },
    { label: 'MEAS:THD?', command: 'MEAS:THD?' },
    { label: 'MEAS:SNR?', command: 'MEAS:SNR?' },
    { label: 'MEAS:NOIS?', command: 'MEAS:NOIS?' },
  ],
  device_under_test: [
    { label: 'MF:DUT:CONF?', command: 'MF:DUT:CONF?', hint: 'Profile and all parameters' },
    { label: 'MF:DUT:PROF?', command: 'MF:DUT:PROF?' },
    { label: 'MF:DUT:FW?', command: 'MF:DUT:FW?' },
    { label: 'MF:DUT:GAIN ', command: 'MF:DUT:GAIN ', hint: 'Set gain in dB (-20 to 60)' },
  ],
};

export function quickCommands(kind: InstrumentKind): QuickCommand[] {
  return [...COMMON.slice(0, 3), ...BY_KIND[kind], ...COMMON.slice(3)];
}
