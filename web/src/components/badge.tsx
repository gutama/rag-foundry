import type {ComponentType, ReactNode} from 'react';

import {cx} from '../lib/cx';
import type {AnswerSupport, LifecycleStatus} from '../types';
import {
  AbstainedIcon,
  ApprovedIcon,
  CandidateIcon,
  GroundedIcon,
  RejectedIcon,
  SupersededIcon,
  ValidatedIcon,
  WarningIcon,
} from './icons';

interface BadgeStyle {
  label: string;
  icon: ComponentType<{size?: number; className?: string}>;
  className: string;
}

/**
 * Status is never color alone: each state has its own icon and label.
 * Approved is the only filled state, candidate is dashed, and superseded
 * strikes its label.
 */
const LIFECYCLE: Record<LifecycleStatus, BadgeStyle> = {
  candidate: {
    label: 'Candidate',
    icon: CandidateIcon,
    className:
      'border-dashed border-candidate-border bg-candidate-bg text-candidate-fg',
  },
  validated: {
    label: 'Validated',
    icon: ValidatedIcon,
    className: 'border-validated-border bg-validated-bg text-validated-fg',
  },
  approved: {
    label: 'Approved',
    icon: ApprovedIcon,
    className: 'border-approved-border bg-approved-bg text-approved-fg',
  },
  rejected: {
    label: 'Rejected',
    icon: RejectedIcon,
    className: 'border-rejected-border bg-rejected-bg text-rejected-fg',
  },
  superseded: {
    label: 'Superseded',
    icon: SupersededIcon,
    className: 'border-superseded-border bg-superseded-bg text-superseded-fg',
  },
};

const SUPPORT: Record<AnswerSupport, BadgeStyle> = {
  grounded: {
    label: 'Grounded',
    icon: GroundedIcon,
    className: 'border-success-border bg-success-bg text-success-fg',
  },
  partial: {
    label: 'Partly supported',
    icon: WarningIcon,
    className: 'border-caution-border bg-caution-bg text-caution-fg',
  },
  // An abstention is a result, not an error: neutral, never danger.
  abstained: {
    label: 'Abstained',
    icon: AbstainedIcon,
    className: 'border-border-control bg-surface text-fg',
  },
};

function Badge({
  style,
  children,
  className,
}: {
  style: BadgeStyle;
  children: ReactNode;
  className?: string;
}) {
  const Icon = style.icon;
  return (
    <span
      className={cx(
        'inline-flex h-6 shrink-0 items-center gap-1.5 self-start rounded-stamp border pr-2.25 pl-1.75 text-label whitespace-nowrap',
        style.className,
        className,
      )}
    >
      <Icon size={14} />
      {children}
    </span>
  );
}

/** The review state of a governed object. */
export function StatusBadge({
  status,
  className,
}: {
  status: LifecycleStatus;
  className?: string;
}) {
  const style = LIFECYCLE[status];
  return (
    <Badge style={style} className={className}>
      {status === 'superseded' ? (
        <span className="line-through">{style.label}</span>
      ) : (
        style.label
      )}
    </Badge>
  );
}

/**
 * How well an answer is supported. Pass the claim counts to add
 * "· 3 of 3 claims cited"; an abstention never shows counts.
 */
export function AnswerBadge({
  support,
  cited,
  total,
  className,
}: {
  support: AnswerSupport;
  cited?: number;
  total?: number;
  className?: string;
}) {
  const style = SUPPORT[support];
  const counts =
    support !== 'abstained' && total !== undefined && cited !== undefined
      ? ` · ${cited} of ${total} claims cited`
      : '';
  return (
    <Badge style={style} className={className}>
      {style.label + counts}
    </Badge>
  );
}
