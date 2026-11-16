import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ApiError } from '@/api/errors';
import type { CommandResponse } from '@/api/types';
import { resetConsoleSessions } from './consoleSession';
import { ScpiConsole } from './ScpiConsole';

function response(over: Partial<CommandResponse> = {}): CommandResponse {
  return { id: 'siggen', command: '*IDN?', is_query: true, response: 'MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0', duration_ms: 1.7, timestamp: '2026-11-16T17:21:29.043Z', error: null, ...over };
}

function setup(send = vi.fn(async (_id: string, _cmd: string) => response())) {
  const user = userEvent.setup();
  render(<ScpiConsole instrumentId="siggen" instrumentKind="signal_generator" send={send} />);
  const input = screen.getByRole('textbox', { name: 'SCPI command' });
  return { user, send, input };
}

describe('ScpiConsole', () => {
  beforeEach(() => resetConsoleSessions());

  it('sends on Enter and shows the response with its duration', async () => {
    const { user, send, input } = setup();
    await user.type(input, '*IDN?{Enter}');
    expect(send).toHaveBeenCalledWith('siggen', '*IDN?');
    expect(await screen.findByText('MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0')).toBeInTheDocument();
    expect(screen.getByText('1.7 ms')).toBeInTheDocument();
    expect(input).toHaveValue('');
  });

  it('shows a setter as ok when the instrument queued no error', async () => {
    const { user, input } = setup(vi.fn(async () => response({ command: 'OUTP ON', is_query: false, response: null })));
    await user.type(input, 'OUTP ON{Enter}');
    const entry = await screen.findByTestId('scpi-entry');
    expect(within(entry).getByText('ok')).toBeInTheDocument();
  });

  it('displays the SCPI error queue entry returned for a setter', async () => {
    const { user, input } = setup(vi.fn(async () => response({ command: 'SOUR:FREQ 99999', is_query: false, response: null, error: { code: -222, message: 'Data out of range' } })));
    await user.type(input, 'SOUR:FREQ 99999{Enter}');
    expect(await screen.findByRole('alert')).toHaveTextContent('SCPI error -222: Data out of range');
  });

  it('displays API errors (code + message) when the request fails', async () => {
    const { user, input } = setup(vi.fn(async () => Promise.reject(new ApiError('TIMEOUT', 'SCPI timeout after 3 attempts', 504))));
    await user.type(input, 'MEAS:RMS?{Enter}');
    expect(await screen.findByRole('alert')).toHaveTextContent('TIMEOUT: SCPI timeout after 3 attempts');
  });

  it('walks the history with ArrowUp / ArrowDown and restores the draft', async () => {
    const { user, input } = setup();
    await user.type(input, '*IDN?{Enter}');
    await user.type(input, 'SOUR:FREQ?{Enter}');
    await user.type(input, 'dra');
    await user.keyboard('{ArrowUp}');
    expect(input).toHaveValue('SOUR:FREQ?');
    await user.keyboard('{ArrowUp}');
    expect(input).toHaveValue('*IDN?');
    await user.keyboard('{ArrowUp}'); // stays at the oldest entry
    expect(input).toHaveValue('*IDN?');
    await user.keyboard('{ArrowDown}');
    expect(input).toHaveValue('SOUR:FREQ?');
    await user.keyboard('{ArrowDown}');
    expect(input).toHaveValue('dra');
  });

  it('does not store consecutive duplicates in the history', async () => {
    const { user, input } = setup();
    await user.type(input, '*IDN?{Enter}');
    await user.type(input, '*IDN?{Enter}');
    await user.keyboard('{ArrowUp}');
    await user.keyboard('{ArrowUp}');
    expect(input).toHaveValue('*IDN?');
    await user.keyboard('{ArrowUp}');
    expect(input).toHaveValue('*IDN?');
  });

  it('validates the command before sending (empty, non-ASCII)', async () => {
    const { user, send, input } = setup();
    await user.click(input);
    await user.keyboard('{Enter}');
    expect(screen.getByText('Enter a command')).toBeInTheDocument();
    await user.type(input, 'ÄÖ?{Enter}');
    expect(screen.getByText('Only printable ASCII characters are allowed')).toBeInTheDocument();
    expect(send).not.toHaveBeenCalled();
  });

  it('quick-insert fills the input without sending, and Clear empties the transcript', async () => {
    const { user, send, input } = setup();
    await user.click(screen.getByRole('button', { name: 'SYST:ERR?' }));
    expect(input).toHaveValue('SYST:ERR?');
    expect(send).not.toHaveBeenCalled();
    await user.keyboard('{Enter}');
    await screen.findAllByTestId('scpi-entry');
    await user.click(screen.getByRole('button', { name: /clear/i }));
    expect(screen.queryByTestId('scpi-entry')).not.toBeInTheDocument();
  });

  it('keeps the transcript when the console is unmounted and mounted again', async () => {
    const { user, input } = setup();
    await user.type(input, '*IDN?{Enter}');
    await screen.findByText('1.7 ms');
    const { unmount } = render(<></>);
    unmount();
    // remount a fresh console for the same instrument
    render(<ScpiConsole instrumentId="siggen" instrumentKind="signal_generator" send={vi.fn()} />);
    await waitFor(() => expect(screen.getAllByTestId('scpi-entry').length).toBeGreaterThanOrEqual(1));
  });

  it('disables sending and explains why when the instrument is not connected', () => {
    render(<ScpiConsole instrumentId="siggen" instrumentKind="signal_generator" disabledReason="Connect the instrument to send commands" send={vi.fn()} />);
    expect(screen.getByRole('textbox', { name: 'SCPI command' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send' })).toHaveAttribute('aria-disabled', 'true');
  });
});
