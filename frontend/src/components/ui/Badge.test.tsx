import { render, screen } from '@testing-library/react';
import { StatusBadge } from './Badge';

describe('StatusBadge', () => {
  it.each([
    ['PASS', 'bg-success-soft'],
    ['FAIL', 'bg-warn-soft'],
    ['ERROR', 'bg-danger-soft'],
    ['CANCELLED', 'bg-neutral-soft'],
    ['RUNNING', 'bg-info-soft'],
  ])('renders %s with its functional colour', (status, cls) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(status);
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain(cls);
  });

  it('keeps FAIL (out of tolerance) visually distinct from ERROR (communication / software)', () => {
    const { container: fail } = render(<StatusBadge status="FAIL" />);
    const { container: error } = render(<StatusBadge status="ERROR" />);
    const failEl = fail.firstElementChild as HTMLElement;
    const errorEl = error.firstElementChild as HTMLElement;
    expect(failEl.className).not.toEqual(errorEl.className);
    // shape differs as well, not only colour
    expect(failEl.querySelector('svg')?.innerHTML).not.toEqual(errorEl.querySelector('svg')?.innerHTML);
  });

  it('decorative icons are hidden from assistive technology; the label is the accessible text', () => {
    render(<StatusBadge status="PASS" />);
    expect(screen.getByText('PASS').querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('spins only while RUNNING and falls back gracefully for unknown values', () => {
    const { container, rerender } = render(<StatusBadge status="RUNNING" />);
    expect(container.querySelector('svg')?.getAttribute('class')).toContain('animate-spin');
    rerender(<StatusBadge status="WEIRD" />);
    expect(screen.getByText('WEIRD')).toBeInTheDocument();
    expect(container.querySelector('svg')?.getAttribute('class')).not.toContain('animate-spin');
  });
});
