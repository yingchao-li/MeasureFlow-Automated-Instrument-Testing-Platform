import { useState } from 'react';
import { api } from '@/api';
import { ApiError, errorMessage } from '@/api/errors';
import type { AnalyzerInstrument, DutInstrument, Instrument, SigGenInstrument } from '@/api/types';
import { SelectField, Switch, TextField } from '@/components/ui';
import { useToast } from '@/context/ToastContext';
import { ANALYZER_POINTS, DUT_FIRMWARES, DUT_PROFILES, DUT_RANGES, SIGGEN_FUNCTIONS, SIGGEN_RANGES, type Range } from '@/lib/ranges';
import { checkNumber, numberToText } from '@/lib/validation';
import { FormShell } from './FormShell';
import { useEditedFields } from './useEditedFields';

interface CommonProps<T extends Instrument> {
  instrument: T;
  /** reason the form cannot be applied (not connected, leased, offline), or null */
  blockedReason: string | null;
  onApplied: (instrument: Instrument) => void;
}

/** Submit helper: sends only changed keys, maps backend errors onto fields or the form. */
function useSubmit(instrumentId: string, onApplied: (i: Instrument) => void, label: string) {
  const toast = useToast();
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const submit = async (settings: Record<string, string | number | boolean>, onSuccess: () => void) => {
    setSubmitting(true);
    setFormError(null);
    setFieldErrors({});
    try {
      const res = await api.configure(instrumentId, settings);
      onApplied(res.instrument);
      onSuccess();
      toast.success(`${label} updated`, Object.keys(settings).join(', '));
    } catch (e) {
      if (e instanceof ApiError && e.code === 'INVALID_ARGUMENT' && e.field) setFieldErrors({ [e.field]: e.message });
      else setFormError(errorMessage(e));
    } finally {
      setSubmitting(false);
    }
  };
  return { submit, submitting, formError, fieldErrors, clearErrors: () => (setFormError(null), setFieldErrors({})) };
}

function numField(
  key: string,
  label: string,
  range: Range,
  ctx: { values: Record<string, string>; set: (k: string, v: string) => void; fieldErrors: Record<string, string>; disabled: boolean },
  opts: { hint?: string; integer?: boolean } = {},
) {
  const text = ctx.values[key] ?? '';
  const check = checkNumber(text, { ...range, integer: opts.integer });
  return {
    check,
    node: (
      <TextField
        key={key}
        label={label}
        unit={range.unit}
        mono
        inputMode="decimal"
        value={text}
        onChange={(v) => ctx.set(key, v)}
        error={check.error ?? ctx.fieldErrors[key] ?? null}
        hint={opts.hint ?? `${range.min} … ${range.max}${range.unit ? ` ${range.unit}` : ''}`}
        disabled={ctx.disabled}
      />
    ),
  };
}

/* ------------------------------------------------------------------ Signal generator */

export function SigGenForm({ instrument, blockedReason, onApplied }: CommonProps<SigGenInstrument>) {
  const s = instrument.settings;
  const server = {
    function: s?.function ?? 'SIN',
    frequency_hz: numberToText(s?.frequency_hz),
    amplitude_vpk: numberToText(s?.amplitude_vpk),
    sample_rate_hz: numberToText(s?.sample_rate_hz),
    output: s?.output ? 'on' : 'off',
  };
  const f = useEditedFields(server);
  const sub = useSubmit(instrument.id, onApplied, 'Signal generator');
  const ctx = { values: f.values, set: f.set, fieldErrors: sub.fieldErrors, disabled: Boolean(blockedReason) };

  const freq = numField('frequency_hz', 'Frequency', SIGGEN_RANGES.frequency_hz, ctx);
  const amp = numField('amplitude_vpk', 'Amplitude (peak)', SIGGEN_RANGES.amplitude_vpk, ctx);
  const srate = numField('sample_rate_hz', 'Sample rate', SIGGEN_RANGES.sample_rate_hz, ctx, { integer: true });
  const invalid = [freq, amp, srate].some((x) => x.check.error);

  const apply = () => {
    if (invalid || !s) return;
    const body: Record<string, string | number | boolean> = {};
    if (f.dirtyKeys.includes('function')) body['function'] = f.values['function'] as string;
    if (f.dirtyKeys.includes('frequency_hz') && freq.check.value !== null) body['frequency_hz'] = freq.check.value;
    if (f.dirtyKeys.includes('amplitude_vpk') && amp.check.value !== null) body['amplitude_vpk'] = amp.check.value;
    if (f.dirtyKeys.includes('sample_rate_hz') && srate.check.value !== null) body['sample_rate_hz'] = srate.check.value;
    if (f.dirtyKeys.includes('output')) body['output'] = f.values['output'] === 'on';
    void sub.submit(body, f.clear);
  };

  return (
    <FormShell onSubmit={apply} onRevert={() => (f.clear(), sub.clearErrors())} dirty={f.isDirty} submitting={sub.submitting} blockedReason={blockedReason ?? (invalid ? 'Fix the highlighted values to apply' : null)} formError={sub.formError}>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <SelectField label="Waveform" value={f.values['function'] as string} onChange={(v) => f.set('function', v)} options={SIGGEN_FUNCTIONS.map((o) => ({ value: o.value, label: `${o.label} (${o.value})` }))} disabled={ctx.disabled} hint={f.values['function'] === 'CHIR' ? 'Chirp sweeps from its start frequency up to the frequency below' : undefined} />
        <div>
          <span className="mb-1 block text-xs font-medium text-ink-2">Output</span>
          <label className="flex h-8 items-center gap-2 text-sm text-ink">
            <Switch label="Generator output" checked={f.values['output'] === 'on'} onChange={(v) => f.set('output', v ? 'on' : 'off')} disabled={ctx.disabled} />
            {f.values['output'] === 'on' ? 'On' : 'Off'}
          </label>
        </div>
        {freq.node}
        {amp.node}
        {srate.node}
      </div>
    </FormShell>
  );
}

/* ------------------------------------------------------------------ DUT */

const DUT_PARAMS: Array<{ key: keyof typeof DUT_RANGES; label: string }> = [
  { key: 'gain_db', label: 'Gain' },
  { key: 'hpf_hz', label: 'High-pass cutoff' },
  { key: 'lpf_hz', label: 'Low-pass cutoff' },
  { key: 'noise_dbv', label: 'Output noise' },
  { key: 'hd2', label: 'HD2 coefficient' },
  { key: 'hd3', label: 'HD3 coefficient' },
  { key: 'clip_vpk', label: 'Clip level' },
];

export function DutForm({ instrument, blockedReason, onApplied }: CommonProps<DutInstrument>) {
  const s = instrument.settings;
  const server: Record<string, string> = {
    profile: s?.profile ?? 'NORMAL',
    firmware: s?.firmware ?? '1.0.0',
    gain_db: numberToText(s?.gain_db),
    hpf_hz: numberToText(s?.hpf_hz),
    lpf_hz: numberToText(s?.lpf_hz),
    noise_dbv: numberToText(s?.noise_dbv),
    hd2: numberToText(s?.hd2),
    hd3: numberToText(s?.hd3),
    clip_vpk: numberToText(s?.clip_vpk),
  };
  const f = useEditedFields(server);
  const sub = useSubmit(instrument.id, onApplied, 'DUT');
  const profileChanged = f.dirtyKeys.includes('profile');
  const disabled = Boolean(blockedReason);
  const ctx = { values: f.values, set: f.set, fieldErrors: sub.fieldErrors, disabled: disabled || profileChanged };

  const fields = DUT_PARAMS.map((p) => numField(p.key, p.label, DUT_RANGES[p.key], ctx, p.key === 'hd2' || p.key === 'hd3' ? { hint: '0 … 1 (polynomial coefficient)' } : {}));
  const invalid = !profileChanged && fields.some((x) => x.check.error);

  const profileOptions = [
    ...(s?.profile === 'CUSTOM' ? [{ value: 'CUSTOM', label: 'CUSTOM (modified parameters)', disabled: true }] : []),
    ...DUT_PROFILES.map((p) => ({ value: p, label: p })),
  ];
  const firmwareOptions = Array.from(new Set<string>([...DUT_FIRMWARES, ...(s?.firmware ? [s.firmware] : [])])).map((v) => ({ value: v, label: v }));

  const apply = () => {
    if (invalid || !s) return;
    const body: Record<string, string | number | boolean> = {};
    if (profileChanged) body['profile'] = f.values['profile'] as string;
    if (f.dirtyKeys.includes('firmware')) body['firmware'] = f.values['firmware'] as string;
    if (!profileChanged) {
      DUT_PARAMS.forEach((p, i) => {
        const v = fields[i]?.check.value;
        if (f.dirtyKeys.includes(p.key) && v !== null && v !== undefined) body[p.key] = v;
      });
    }
    void sub.submit(body, f.clear);
  };

  return (
    <FormShell onSubmit={apply} onRevert={() => (f.clear(), sub.clearErrors())} dirty={f.isDirty} submitting={sub.submitting} blockedReason={blockedReason ?? (invalid ? 'Fix the highlighted values to apply' : null)} formError={sub.formError}>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <SelectField label="Profile" value={f.values['profile'] as string} onChange={(v) => f.set('profile', v)} options={profileOptions} disabled={disabled} hint={profileChanged ? 'The preset loads all parameters when applied' : 'Presets: NORMAL, LOWGAIN, HIGHTHD, NOISY, CLIPPING'} />
        <SelectField label="Firmware" value={f.values['firmware'] as string} onChange={(v) => f.set('firmware', v)} options={firmwareOptions} disabled={disabled} hint="1.2.0 is the regression build" />
      </div>
      <fieldset className="space-y-3 border-t border-border pt-3" disabled={disabled || profileChanged}>
        <legend className="eyebrow float-left mb-2 w-full">Parameters{profileChanged ? ' — will be replaced by the preset' : ''}</legend>
        <div className="grid clear-both grid-cols-2 gap-x-4 gap-y-3">{fields.map((x) => x.node)}</div>
      </fieldset>
    </FormShell>
  );
}

/* ------------------------------------------------------------------ Analyzer */

export function AnalyzerForm({ instrument, blockedReason, onApplied }: CommonProps<AnalyzerInstrument>) {
  const s = instrument.settings;
  const server = { points: String(s?.points ?? 16384) };
  const f = useEditedFields(server);
  const sub = useSubmit(instrument.id, onApplied, 'Analyzer');
  const apply = () => {
    void sub.submit({ points: Number(f.values['points']) }, f.clear);
  };
  return (
    <FormShell onSubmit={apply} onRevert={() => (f.clear(), sub.clearErrors())} dirty={f.isDirty} submitting={sub.submitting} blockedReason={blockedReason} formError={sub.formError}>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <SelectField
          label="Acquisition length"
          value={f.values['points'] as string}
          onChange={(v) => f.set('points', v)}
          options={ANALYZER_POINTS.map((p) => ({ value: String(p), label: `${p.toLocaleString('en-US')} points` }))}
          disabled={Boolean(blockedReason)}
          error={sub.fieldErrors['points'] ?? null}
          hint="Power of two, 1024 … 65536. Longer buffers give finer spectral resolution."
        />
        <div>
          <span className="mb-1 block text-xs font-medium text-ink-2">Sample rate</span>
          <p className="mono flex h-8 items-center text-sm text-ink">{s ? `${s.sample_rate_hz.toLocaleString('en-US')} Hz` : '—'}</p>
          <p className="mt-1 text-xs text-ink-3">Read-only, follows the signal generator</p>
        </div>
        <div>
          <span className="mb-1 block text-xs font-medium text-ink-2">Stored acquisition</span>
          <p className="flex h-8 items-center text-sm text-ink">{s?.acquisition_stored ? 'Yes - measurements reuse the stored buffer' : 'No - next measurement acquires one'}</p>
        </div>
      </div>
    </FormShell>
  );
}
