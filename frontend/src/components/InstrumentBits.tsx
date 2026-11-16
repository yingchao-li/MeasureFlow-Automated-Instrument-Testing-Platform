import { Badge, StatusDot } from '@/components/ui';
import type { Calibration, InstrumentKind, InstrumentState } from '@/api/types';
import { CALIBRATION_STATUS, INSTRUMENT_STATE } from '@/lib/status';
import { formatDate } from '@/lib/format';

export function InstrumentStateBadge({ state }: { state: InstrumentState }) {
  const m = INSTRUMENT_STATE[state];
  return (
    <Badge tone={m.tone} icon={<StatusDot tone={m.tone} pulse={state === 'connecting'} />}>
      {m.label}
    </Badge>
  );
}

/** valid / due soon / expired chip with the due date and days remaining. */
export function CalibrationChip({ calibration }: { calibration: Calibration | null | undefined }) {
  if (!calibration || calibration.status === 'none') return <Badge tone="neutral">No calibration record</Badge>;
  const m = CALIBRATION_STATUS[calibration.status];
  const days = calibration.days_remaining;
  const when = days === null ? null : days < 0 ? `${-days} d overdue` : `${days} d left`;
  return (
    <Badge tone={m.tone} title={calibration.due ? `Due ${formatDate(calibration.due)}` : undefined}>
      {m.label.replace('Calibration ', 'Cal ')} {when && <span className="mono font-medium opacity-80">{when}</span>}
    </Badge>
  );
}

export const KIND_LABEL: Record<InstrumentKind, string> = {
  signal_generator: 'Signal generator',
  audio_analyzer: 'Audio analyzer',
  device_under_test: 'Device under test',
};
