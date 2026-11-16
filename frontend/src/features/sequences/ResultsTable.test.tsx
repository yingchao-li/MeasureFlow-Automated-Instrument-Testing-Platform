import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ERROR_TASK, FAIL_TASK, PASS_TASK } from '@/test/fixtures';
import { ResultsTable } from './ResultsTable';

describe('ResultsTable', () => {
  const tasks = [PASS_TASK, FAIL_TASK, ERROR_TASK];

  it('renders measured value with unit, limits, attempts and a status badge per task', () => {
    render(<ResultsTable tasks={tasks} />);
    const pass = screen.getByText('Gain @ 1000 Hz').closest('tr') as HTMLElement;
    expect(within(pass).getByText('19.98 dB')).toBeInTheDocument();
    expect(within(pass).getByText('19 … 21 dB')).toBeInTheDocument();
    expect(within(pass).getByText('PASS')).toBeInTheDocument();
  });

  it('renders FAIL (out of tolerance) with its code and message, amber', () => {
    render(<ResultsTable tasks={tasks} />);
    const row = screen.getByText('THD @ 1000 Hz').closest('tr') as HTMLElement;
    expect(row).toHaveAttribute('data-status', 'FAIL');
    expect(within(row).getByText('FAIL')).toBeInTheDocument();
    expect(within(row).getByText('OUT_OF_TOLERANCE_HIGH')).toBeInTheDocument();
    expect(within(row).getByText('THD 2.31 % above limit 1 %')).toBeInTheDocument();
    expect(within(row).getByText('2.310 %')).toBeInTheDocument();
    expect(within(row).getByText('≤ 1 %')).toBeInTheDocument();
    expect(within(row).getByText('FAIL').className).toContain('bg-warn-soft');
  });

  it('renders ERROR (communication / software) differently: no value, red, error code, retries', () => {
    render(<ResultsTable tasks={tasks} />);
    const row = screen.getByText('SNR @ 1000 Hz').closest('tr') as HTMLElement;
    expect(row).toHaveAttribute('data-status', 'ERROR');
    expect(within(row).getByText('ERROR').className).toContain('bg-danger-soft');
    expect(within(row).getByText('COMM_TIMEOUT')).toBeInTheDocument();
    expect(within(row).getByText('analyzer did not answer within 2000 ms')).toBeInTheDocument();
    expect(within(row).getByText('3')).toBeInTheDocument(); // attempts
    expect(within(row).getByText('≥ 60 dB')).toBeInTheDocument();
    // no measurement exists for an ERROR task
    const cells = within(row).getAllByRole('cell');
    expect(cells[1]).toHaveTextContent('—'); // measured column
  });

  it('never labels FAIL as ERROR or the other way round', () => {
    render(<ResultsTable tasks={tasks} />);
    const failRow = screen.getByText('THD @ 1000 Hz').closest('tr') as HTMLElement;
    const errorRow = screen.getByText('SNR @ 1000 Hz').closest('tr') as HTMLElement;
    expect(within(failRow).queryByText('ERROR')).not.toBeInTheDocument();
    expect(within(errorRow).queryByText('FAIL')).not.toBeInTheDocument();
    expect(within(failRow).queryByText('COMM_TIMEOUT')).not.toBeInTheDocument();
  });

  it('filters to FAIL / ERROR only', async () => {
    const user = userEvent.setup();
    render(<ResultsTable tasks={tasks} />);
    await user.click(screen.getByRole('radio', { name: /FAIL \/ ERROR 2/ }));
    expect(screen.queryByText('Gain @ 1000 Hz')).not.toBeInTheDocument();
    expect(screen.getByText('THD @ 1000 Hz')).toBeInTheDocument();
    expect(screen.getByText('SNR @ 1000 Hz')).toBeInTheDocument();
  });

  it('shows an instructive empty state before the first result', () => {
    render(<ResultsTable tasks={[]} />);
    expect(screen.getByText('No results yet')).toBeInTheDocument();
  });
});
