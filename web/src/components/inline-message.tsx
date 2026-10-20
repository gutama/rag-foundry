import type {ReactNode} from 'react';

import {cx} from '../lib/cx';
import {ErrorIcon, InfoIcon, WarningIcon} from './icons';

export type MessageTone = 'info' | 'caution' | 'danger';

const TONES: Record<MessageTone, {icon: typeof InfoIcon; className: string}> = {
  info: {
    icon: InfoIcon,
    className: 'border-info-border bg-info-bg text-info-fg',
  },
  caution: {
    icon: WarningIcon,
    className: 'border-caution-border bg-caution-bg text-caution-fg',
  },
  danger: {
    icon: ErrorIcon,
    className: 'border-danger-border bg-danger-bg text-danger-fg',
  },
};

/** A titled notice with one line of explanation. */
export function InlineMessage({
  tone,
  title,
  children,
  className,
}: {
  tone: MessageTone;
  title: string;
  children?: ReactNode;
  className?: string;
}) {
  const {icon: Icon, className: toneClass} = TONES[tone];
  return (
    <div
      className={cx(
        'flex gap-2.5 rounded-control border px-3.5 py-3',
        toneClass,
        className,
      )}
    >
      <Icon className="mt-0.5 shrink-0" />
      <div className="flex flex-col gap-0.5">
        <span className="text-body leading-5 font-semibold">{title}</span>
        {children && (
          <span className="text-small text-fg-secondary">{children}</span>
        )}
      </div>
    </div>
  );
}
