import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { SequenceParameter } from '@/api/types';
import { defaultValues, validateParameters } from '@/lib/parameters';
import { ParameterForm } from './ParameterForm';

const params: SequenceParameter[] = [
  { key: 'frequency_hz', label: 'Stimulus frequency', unit: 'Hz', default: 1000, min: 20, max: 20000 },
  { key: 'gain_min_db', label: 'Gain lower limit', unit: 'dB', default: 19, min: -20, max: 60 },
  { key: 'gain_max_db', label: 'Gain upper limit', unit: 'dB', default: 21, min: -20, max: 60 },
];

function Harness() {
  const [values, setValues] = useState(defaultValues(params));
  const validation = validateParameters(params, values);
  return (
    <>
      <ParameterForm parameters={params} values={values} validation={validation} onChange={(k, v) => setValues((s) => ({ ...s, [k]: v }))} onReset={(k) => setValues((s) => ({ ...s, [k]: defaultValues(params)[k] as string }))} />
      <output data-testid="invalid">{validation.invalidCount}</output>
    </>
  );
}

describe('ParameterForm', () => {
  it('generates one labelled field per declared parameter, grouped into stimulus and tolerances', () => {
    render(<Harness />);
    expect(screen.getByLabelText('Stimulus frequency')).toHaveValue('1000');
    expect(screen.getByLabelText('Gain lower limit')).toHaveValue('19');
    expect(screen.getByText('Stimulus')).toBeInTheDocument();
    expect(screen.getByText('Tolerances')).toBeInTheDocument();
    // hint shows default and range with unit
    expect(screen.getAllByText(/Default 1000 · 20 … 20000 Hz/)).toHaveLength(1);
  });

  it('shows an inline range error with units and marks the field invalid', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const field = screen.getByLabelText('Stimulus frequency');
    await user.clear(field);
    await user.type(field, '5');
    expect(screen.getByText('Must be between 20 and 20000 Hz')).toBeInTheDocument();
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(field).toHaveAccessibleDescription('Must be between 20 and 20000 Hz');
    expect(screen.getByTestId('invalid')).toHaveTextContent('1');
  });

  it('rejects non-numeric and empty input', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const field = screen.getByLabelText('Stimulus frequency');
    await user.clear(field);
    expect(screen.getByText('Enter a value')).toBeInTheDocument();
    await user.type(field, 'abc');
    expect(screen.getByText('Enter a number')).toBeInTheDocument();
  });

  it('offers reset-to-default only for modified fields and restores the default', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.queryByRole('button', { name: /reset stimulus frequency/i })).not.toBeInTheDocument();
    const field = screen.getByLabelText('Stimulus frequency');
    await user.clear(field);
    await user.type(field, '2000');
    await user.click(screen.getByRole('button', { name: 'Reset Stimulus frequency to default (1000)' }));
    expect(field).toHaveValue('1000');
    expect(screen.queryByRole('button', { name: /reset stimulus frequency/i })).not.toBeInTheDocument();
  });

  it('warns when the lower limit is above the upper limit but does not mark it invalid', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const lo = screen.getByLabelText('Gain lower limit');
    await user.clear(lo);
    await user.type(lo, '30');
    expect(screen.getByText(/Lower limit is above the upper limit/)).toBeInTheDocument();
    expect(lo).not.toHaveAttribute('aria-invalid');
    expect(screen.getByTestId('invalid')).toHaveTextContent('0');
  });
});
