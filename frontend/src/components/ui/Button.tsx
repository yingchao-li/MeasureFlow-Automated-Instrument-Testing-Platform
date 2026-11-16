import { forwardRef, type AnchorHTMLAttributes, type ButtonHTMLAttributes, type MouseEvent, type ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from './cn';
import { Tooltip } from './Tooltip';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md';

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-primary-fg hover:bg-primary-hover border border-transparent',
  secondary: 'bg-surface text-ink border border-border-strong hover:bg-hover hover:border-control',
  ghost: 'bg-transparent text-ink-2 border border-transparent hover:bg-hover hover:text-ink',
  danger: 'bg-danger text-primary-fg border border-transparent hover:opacity-90',
};
const SIZE: Record<ButtonSize, string> = {
  sm: 'h-7 gap-1.5 px-2.5 text-xs',
  md: 'h-8 gap-2 px-3 text-sm',
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
  /**
   * When set the button looks disabled and ignores clicks but stays focusable (aria-disabled),
   * and the reason is exposed as its title. Show the same reason as visible text near the button.
   */
  disabledReason?: string | null;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading, icon, disabledReason, className, children, onClick, disabled, type = 'button', title, ...rest },
  ref,
) {
  const soft = Boolean(disabledReason) || loading;
  const handleClick = (e: MouseEvent<HTMLButtonElement>) => {
    if (soft) {
      e.preventDefault();
      return;
    }
    onClick?.(e);
  };
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled}
      aria-disabled={soft || undefined}
      aria-busy={loading || undefined}
      title={disabledReason ?? title}
      onClick={handleClick}
      className={cn(
        'inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded font-medium transition-colors',
        VARIANT[variant],
        SIZE[size],
        (disabled || disabledReason) && 'cursor-not-allowed opacity-50',
        loading && 'cursor-progress',
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" /> : icon}
      {children}
    </button>
  );
});

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> {
  /** Required accessible name; also used as the tooltip. */
  label: string;
  variant?: 'ghost' | 'secondary';
  size?: 'sm' | 'md';
  pressed?: boolean;
  tooltipSide?: 'top' | 'right' | 'bottom';
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, variant = 'ghost', size = 'md', pressed, tooltipSide = 'top', className, children, type = 'button', ...rest },
  ref,
) {
  return (
    <Tooltip content={label} side={tooltipSide}>
      <button
        ref={ref}
        type={type}
        aria-label={label}
        aria-pressed={pressed}
        className={cn(
          'inline-flex shrink-0 items-center justify-center rounded transition-colors disabled:cursor-not-allowed disabled:opacity-50',
          size === 'sm' ? 'h-6 w-6' : 'h-7 w-7',
          variant === 'ghost'
            ? 'text-ink-2 hover:bg-hover hover:text-ink'
            : 'border border-border-strong bg-surface text-ink-2 hover:bg-hover hover:text-ink',
          pressed && 'bg-primary-soft text-primary-text hover:bg-primary-soft hover:text-primary-text',
          className,
        )}
        {...rest}
      >
        {children}
      </button>
    </Tooltip>
  );
});

export interface ButtonLinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
}

/** A real `<a>` (download / external link) that looks like a Button. */
export const ButtonLink = forwardRef<HTMLAnchorElement, ButtonLinkProps>(function ButtonLink({ variant = 'secondary', size = 'md', icon, className, children, ...rest }, ref) {
  return (
    <a
      ref={ref}
      className={cn('inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded font-medium no-underline transition-colors', VARIANT[variant], SIZE[size], className)}
      {...rest}
    >
      {icon}
      {children}
    </a>
  );
});
