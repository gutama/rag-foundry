import type {ButtonHTMLAttributes, ReactNode} from 'react';

import {cx} from '../lib/cx';
import {SpinnerIcon} from './icons';

/**
 * - `primary`: the one cobalt action in a region.
 * - `secondary`: outlined, for everything else.
 * - `text`: link-colored, for low-emphasis actions and toolbars.
 * - `danger`: outlined, never filled, because a rejection is recorded.
 */
export type ButtonVariant = 'primary' | 'secondary' | 'text' | 'danger';

/** Compact is 32px, default 40px, touch 44px. */
export type ButtonSize = 'compact' | 'default' | 'touch';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner and blocks presses while work is in flight. */
  busy?: boolean;
  /** Icon placed after the label. */
  trailingIcon?: ReactNode;
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-action text-on-action hover:bg-action-hover active:bg-action-hover',
  secondary:
    'border border-border-control bg-surface text-fg hover:bg-surface-sunken',
  text: 'bg-transparent text-link hover:bg-action-subtle',
  danger:
    'border border-danger-border bg-surface text-danger-fg hover:bg-danger-bg',
};

const SIZES: Record<ButtonSize, string> = {
  compact: 'h-8 px-3 text-small',
  default: 'h-10 px-4 text-body',
  touch: 'h-11 px-4.5 text-[0.9375rem]',
};

/** Text buttons sit closer to their neighbors. */
const TEXT_SIZES: Record<ButtonSize, string> = {
  compact: 'h-8 px-2.5 text-small',
  default: 'h-10 px-3 text-body',
  touch: 'h-11 px-3.5 text-[0.9375rem]',
};

export function Button({
  variant = 'secondary',
  size = 'default',
  busy = false,
  trailingIcon,
  className,
  children,
  disabled,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        'inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-control font-medium',
        // A busy button keeps its colors; a disabled one goes grey.
        busy
          ? 'cursor-progress'
          : 'disabled:cursor-not-allowed disabled:border-transparent disabled:bg-surface-sunken disabled:text-fg-muted',
        VARIANTS[variant],
        variant === 'text' ? TEXT_SIZES[size] : SIZES[size],
        className,
      )}
      {...rest}
    >
      {busy && <SpinnerIcon className="animate-spin" />}
      {children}
      {trailingIcon}
    </button>
  );
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accessible name; the icon itself is hidden from assistive tech. */
  label: string;
  /** `ghost` drops the outline, for toolbars. */
  variant?: 'secondary' | 'ghost';
  size?: 'compact' | 'default';
}

/** A square button that shows only an icon. */
export function IconButton({
  label,
  variant = 'secondary',
  size = 'default',
  className,
  children,
  type = 'button',
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      className={cx(
        'inline-flex shrink-0 items-center justify-center rounded-control text-fg',
        size === 'compact' ? 'size-8' : 'size-10',
        variant === 'secondary'
          ? 'border border-border-control bg-surface hover:bg-surface-sunken'
          : 'bg-transparent hover:bg-surface-sunken',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
