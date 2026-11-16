import { Play, RotateCcw, Square } from 'lucide-react';
import type { Sequence } from '@/api/types';
import { Button, Panel, SelectField, TextField } from '@/components/ui';
import { DUT_FIRMWARES, DUT_PROFILES, RUN_LABEL_MAX, RUN_RETRIES } from '@/lib/ranges';
import { checkNumber } from '@/lib/validation';
import type { ParameterValidation } from '@/lib/parameters';
import { ParameterForm } from './ParameterForm';

export interface RunSettings {
  values: Record<string, string>;
  profile: string;
  firmware: string;
  retries: string;
  label: string;
}

interface RunSetupProps {
  sequence: Sequence;
  settings: RunSettings;
  validation: ParameterValidation;
  onChange: (patch: Partial<RunSettings>) => void;
  onParam: (key: string, value: string) => void;
  onResetParam: (key: string) => void;
  onResetAll: () => void;
  onStart: () => void;
  onCancel: () => void;
  starting: boolean;
  cancelling: boolean;
  startBlocked: string | null;
  cancelBlocked: string | null;
  formError: string | null;
  locked: boolean;
}

export function retriesCheck(text: string) {
  return checkNumber(text, { min: RUN_RETRIES.min, max: RUN_RETRIES.max, integer: true });
}

export function RunSetup({ sequence, settings, validation, onChange, onParam, onResetParam, onResetAll, onStart, onCancel, starting, cancelling, startBlocked, cancelBlocked, formError, locked }: RunSetupProps) {
  const retries = retriesCheck(settings.retries);
  const labelError = settings.label.length > RUN_LABEL_MAX ? `At most ${RUN_LABEL_MAX} characters (${settings.label.length})` : null;
  const firmwareOptions = Array.from(new Set<string>([...DUT_FIRMWARES, sequence.dut.firmware, settings.firmware])).map((v) => ({ value: v, label: v }));
  const modifiedCount = sequence.parameters.filter((p) => settings.values[p.key] !== undefined && Number(settings.values[p.key]) !== p.default).length;

  return (
    <Panel
      title={`Configure ${sequence.name}`}
      description={`v${sequence.version}`}
      actions={
        <Button size="sm" variant="ghost" icon={<RotateCcw aria-hidden className="h-3.5 w-3.5" />} onClick={onResetAll} disabled={locked || modifiedCount === 0}>
          Reset all to defaults
        </Button>
      }
    >
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          onStart();
        }}
        className="space-y-5"
      >
        <ParameterForm parameters={sequence.parameters} values={settings.values} validation={validation} onChange={onParam} onReset={onResetParam} disabled={locked} />

        <fieldset className="border-t border-border pt-4">
          <legend className="eyebrow mb-2">Device under test and run</legend>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 xl:grid-cols-4">
            <SelectField
              label="DUT profile"
              value={settings.profile}
              onChange={(profile) => onChange({ profile })}
              options={DUT_PROFILES.map((p) => ({ value: p, label: p }))}
              disabled={locked}
              hint={`Sequence default ${sequence.dut.profile}`}
            />
            <SelectField label="DUT firmware" value={settings.firmware} onChange={(firmware) => onChange({ firmware })} options={firmwareOptions} disabled={locked} hint={`Sequence default ${sequence.dut.firmware}`} />
            <TextField label="Retries" mono inputMode="numeric" value={settings.retries} onChange={(retriesText) => onChange({ retries: retriesText })} error={retries.error} hint="0 … 5 on communication errors" disabled={locked} />
            <TextField label="Label" value={settings.label} onChange={(label) => onChange({ label })} error={labelError} hint="Optional, shown in reports" placeholder="e.g. nightly" disabled={locked} />
          </div>
        </fieldset>

        {formError && (
          <p role="alert" className="rounded border border-danger/40 bg-danger-soft px-3 py-2 text-xs text-danger-text">
            {formError}
          </p>
        )}

        <div className="flex items-center justify-between gap-4 border-t border-border pt-4">
          <p className="min-w-0 text-xs text-ink-3" aria-live="polite" id="run-hint">
            {startBlocked ?? 'Ready. The init step connects the instruments if needed.'}
          </p>
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="secondary" icon={<Square aria-hidden className="h-3.5 w-3.5" />} onClick={onCancel} loading={cancelling} disabledReason={cancelBlocked} aria-describedby="run-hint">
              Cancel run
            </Button>
            <Button type="submit" variant="primary" icon={<Play aria-hidden className="h-3.5 w-3.5" />} loading={starting} disabledReason={startBlocked} aria-describedby="run-hint">
              Start run
            </Button>
          </div>
        </div>
      </form>
    </Panel>
  );
}
