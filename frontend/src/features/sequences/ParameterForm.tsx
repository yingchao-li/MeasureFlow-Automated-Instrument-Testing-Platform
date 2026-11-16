import { RotateCcw } from 'lucide-react';
import type { SequenceParameter } from '@/api/types';
import { IconButton, TextField } from '@/components/ui';
import { isModified, isToleranceParameter, orderTolerances, type ParameterValidation } from '@/lib/parameters';

interface ParameterFormProps {
  parameters: ReadonlyArray<SequenceParameter>;
  values: Record<string, string>;
  validation: ParameterValidation;
  onChange: (key: string, value: string) => void;
  onReset: (key: string) => void;
  disabled?: boolean;
}

const fmt = (n: number) => String(Number(n.toPrecision(8)));

/**
 * Parameter and tolerance form generated from `sequence.parameters`:
 * units, min/max validation, per-field reset-to-default. Stimulus first, tolerance limits second.
 */
export function ParameterForm({ parameters, values, validation, onChange, onReset, disabled }: ParameterFormProps) {
  const stimulus = parameters.filter((p) => !isToleranceParameter(p));
  const tolerances = orderTolerances(parameters.filter(isToleranceParameter));

  const renderField = (p: SequenceParameter) => {
    const modified = isModified(p, values[p.key]);
    return (
      <TextField
        key={p.key}
        label={p.label}
        unit={p.unit}
        mono
        inputMode="decimal"
        value={values[p.key] ?? ''}
        onChange={(v) => onChange(p.key, v)}
        error={validation.errors[p.key] ?? null}
        warning={validation.warnings[p.key] ?? null}
        hint={`Default ${fmt(p.default)} · ${fmt(p.min)} … ${fmt(p.max)}${p.unit ? ` ${p.unit}` : ''}`}
        disabled={disabled}
        labelAction={
          modified && !disabled ? (
            <IconButton label={`Reset ${p.label} to default (${fmt(p.default)})`} size="sm" onClick={() => onReset(p.key)}>
              <RotateCcw aria-hidden className="h-3 w-3" />
            </IconButton>
          ) : undefined
        }
      />
    );
  };

  if (parameters.length === 0) return <p className="text-sm text-ink-3">This sequence declares no parameters.</p>;
  return (
    <div className="space-y-5">
      {stimulus.length > 0 && (
        <fieldset>
          <legend className="eyebrow mb-2">Stimulus</legend>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 xl:grid-cols-3">{stimulus.map(renderField)}</div>
        </fieldset>
      )}
      {tolerances.length > 0 && (
        <fieldset>
          <legend className="eyebrow mb-2">Tolerances</legend>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 xl:grid-cols-3">{tolerances.map(renderField)}</div>
        </fieldset>
      )}
    </div>
  );
}
