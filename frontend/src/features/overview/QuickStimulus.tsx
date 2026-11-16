import { useState, type FormEvent } from 'react';
import { api } from '@/api';
import { errorMessage } from '@/api/errors';
import type { Instrument, SigGenInstrument } from '@/api/types';
import { Button, Panel, Switch, TextField } from '@/components/ui';
import { useToast } from '@/context/ToastContext';
import { checkNumber, numberToText } from '@/lib/validation';
import { SIGGEN_RANGES } from '@/lib/ranges';

interface QuickStimulusProps {
  siggen: SigGenInstrument | undefined;
  /** Why the controls are unavailable (shown inline); null when usable. */
  blockedReason: string | null;
  onApplied: (instrument: Instrument) => void;
}

/** Frequency / amplitude / output of the signal generator via POST /api/instruments/configure. */
export function QuickStimulus({ siggen, blockedReason, onApplied }: QuickStimulusProps) {
  const toast = useToast();
  const settings = siggen?.settings ?? null;
  const [edited, setEdited] = useState<{ freq?: string; amp?: string }>({});
  const [submitting, setSubmitting] = useState(false);
  const [outputBusy, setOutputBusy] = useState(false);

  const freqText = edited.freq ?? numberToText(settings?.frequency_hz);
  const ampText = edited.amp ?? numberToText(settings?.amplitude_vpk);
  const freq = checkNumber(freqText, SIGGEN_RANGES.frequency_hz);
  const amp = checkNumber(ampText, SIGGEN_RANGES.amplitude_vpk);
  const dirty = edited.freq !== undefined || edited.amp !== undefined;
  const disabled = Boolean(blockedReason) || !settings;

  const apply = async (e: FormEvent) => {
    e.preventDefault();
    if (disabled || !dirty || freq.error || amp.error || freq.value === null || amp.value === null) return;
    const body: Record<string, number> = {};
    if (freq.value !== settings?.frequency_hz) body['frequency_hz'] = freq.value;
    if (amp.value !== settings?.amplitude_vpk) body['amplitude_vpk'] = amp.value;
    if (Object.keys(body).length === 0) {
      setEdited({});
      return;
    }
    setSubmitting(true);
    try {
      const res = await api.configure('siggen', body);
      onApplied(res.instrument);
      setEdited({});
      toast.success('Stimulus updated');
    } catch (err) {
      toast.error('Could not update the stimulus', errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const toggleOutput = async (on: boolean) => {
    setOutputBusy(true);
    try {
      const res = await api.configure('siggen', { output: on });
      onApplied(res.instrument);
    } catch (err) {
      toast.error(`Could not switch the output ${on ? 'on' : 'off'}`, errorMessage(err));
    } finally {
      setOutputBusy(false);
    }
  };

  return (
    <Panel title="Stimulus" description="Signal generator">
      <form onSubmit={apply} noValidate className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Frequency"
            unit="Hz"
            mono
            inputMode="decimal"
            value={freqText}
            onChange={(v) => setEdited((s) => ({ ...s, freq: v }))}
            error={dirty && edited.freq !== undefined ? freq.error : null}
            disabled={disabled}
          />
          <TextField
            label="Amplitude"
            unit="Vpk"
            mono
            inputMode="decimal"
            value={ampText}
            onChange={(v) => setEdited((s) => ({ ...s, amp: v }))}
            error={dirty && edited.amp !== undefined ? amp.error : null}
            disabled={disabled}
          />
        </div>
        <div className="flex items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm text-ink">
            <Switch
              label="Generator output"
              checked={settings?.output ?? false}
              onChange={(v) => void toggleOutput(v)}
              disabled={disabled || outputBusy}
              busy={outputBusy}
            />
            Output {settings?.output ? 'on' : 'off'}
          </label>
          <div className="flex items-center gap-2">
            {dirty && (
              <Button size="sm" variant="ghost" onClick={() => setEdited({})} disabled={submitting}>
                Revert
              </Button>
            )}
            <Button type="submit" size="sm" variant="primary" loading={submitting} disabledReason={!dirty ? 'No changes to apply' : freq.error || amp.error ? 'Fix the highlighted values first' : disabled ? blockedReason : null}>
              Apply
            </Button>
          </div>
        </div>
        {blockedReason && <p className="text-xs text-ink-3">{blockedReason}</p>}
      </form>
    </Panel>
  );
}
