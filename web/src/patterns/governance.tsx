import {Fragment, type ReactNode} from 'react';

import {StatusBadge} from '../components/badge';
import {Button} from '../components/button';
import {
  ApprovedIcon,
  ErrorIcon,
  FlowArrowIcon,
  FlowDownIcon,
  LockIcon,
  WarningIcon,
} from '../components/icons';
import {cx} from '../lib/cx';
import type {
  AuditEvent,
  ChangeSet,
  CheckResult,
  Concept,
  DiffRow,
  EntityRecord,
  LifecycleStatus,
  MatchSignal,
} from '../types';

/** Icon for a check outcome; the text beside it carries the meaning. */
export function CheckResultIcon({
  result,
  size = 16,
}: {
  result: CheckResult;
  size?: number;
}) {
  if (result === 'pass') {
    return <ApprovedIcon size={size} className="shrink-0 text-success-fg" />;
  }
  if (result === 'warn') {
    return <WarningIcon size={size} className="shrink-0 text-caution-fg" />;
  }
  return <ErrorIcon size={size} className="shrink-0 text-danger-fg" />;
}

const STAGES: Array<{
  status: LifecycleStatus;
  text: string;
  className: string;
}> = [
  {
    status: 'candidate',
    text: 'Proposed by an extraction job or a person. Visible to stewards only.',
    className: 'border border-dashed border-candidate-border bg-surface',
  },
  {
    status: 'validated',
    text: 'Evidence resolves, constraints hold, identity is unambiguous.',
    className: 'border border-validated-border bg-surface',
  },
  {
    status: 'approved',
    text: 'A reviewer other than the proposer approved it. May be published.',
    className: 'border-[1.5px] border-approved-border bg-surface',
  },
  {
    status: 'superseded',
    text: 'Kept read-only, with a link to the version that replaced it.',
    className: 'border border-border bg-bg',
  },
];

const TRANSITIONS = ['checks', 'review', 'new version'];

/** Candidate → validated → approved → superseded, with rejection below. */
export function LifecycleDiagram() {
  return (
    <div className="flex flex-col gap-5">
      <ol className="flex flex-col items-stretch lg:grid lg:grid-cols-[minmax(0,1fr)_3.5rem_minmax(0,1fr)_3.5rem_minmax(0,1fr)_3.5rem_minmax(0,1fr)] lg:items-center">
        {STAGES.map((stage, i) => (
          <Fragment key={stage.status}>
            {i > 0 && (
              <li
                aria-hidden="true"
                className="flex items-center justify-center gap-2 py-2 text-fg-muted lg:flex-col lg:gap-1 lg:py-0"
              >
                <FlowArrowIcon className="rotate-90 lg:rotate-0" />
                <span className="font-mono text-[0.625rem]">
                  {TRANSITIONS[i - 1]}
                </span>
              </li>
            )}
            <li
              className={cx(
                'flex flex-col gap-2.5 rounded-panel p-4.5',
                stage.className,
              )}
            >
              <StatusBadge status={stage.status} />
              <p className="text-small text-fg-secondary">{stage.text}</p>
            </li>
          </Fragment>
        ))}
      </ol>
      <div className="flex items-center gap-3 px-4.5 lg:max-w-[calc(50%-1.75rem)]">
        <FlowDownIcon className="shrink-0 text-danger-fg" />
        <StatusBadge status="rejected" />
        <span className="text-small text-fg-secondary">
          From candidate or validated, when checks or review fail. The reason is
          required and the record is kept.
        </span>
      </div>
    </div>
  );
}

const DIFF_STYLE: Record<DiffRow['op'], {sign: string; className: string}> = {
  add: {sign: '+', className: 'bg-success-bg [&>:first-child]:text-success-fg'},
  change: {sign: '~', className: '[&>:first-child]:text-fg-muted'},
  remove: {
    sign: '−',
    className: 'bg-danger-bg [&>:first-child]:text-danger-fg',
  },
};

function DiffLine({row}: {row: DiffRow}) {
  const style = DIFF_STYLE[row.op];
  return (
    <div
      className={cx(
        'grid grid-cols-[1.5rem_minmax(0,9rem)_minmax(0,1fr)] gap-x-2 px-6 py-1.5 sm:grid-cols-[1.5rem_12.5rem_minmax(0,1fr)] sm:gap-x-0',
        style.className,
      )}
    >
      <span className="font-medium">
        {style.sign}
        <span className="sr-only">
          {{add: ' added', change: ' changed', remove: ' removed'}[row.op]}
        </span>
      </span>
      <span className="text-fg-secondary">{row.property}</span>
      {row.op === 'change' ? (
        <span>
          <del className="text-danger-fg">{row.previous}</del>
          {'  →  '}
          <ins className="no-underline">{row.value}</ins>
        </span>
      ) : row.op === 'remove' ? (
        <del className="text-fg-secondary">{row.value}</del>
      ) : (
        <span>{row.value}</span>
      )}
    </div>
  );
}

/**
 * Who proposed what, what the checks found, and what will publish, before
 * anyone approves. The proposer cannot approve their own change set.
 */
export function ChangeSetReview({
  changeSet,
  canApprove = true,
  onApprove,
  onRequestChanges,
  onReject,
}: {
  changeSet: ChangeSet;
  /** False when the reader proposed the change set (maker–checker). */
  canApprove?: boolean;
  onApprove?: () => void;
  onRequestChanges?: () => void;
  onReject?: () => void;
}) {
  return (
    <article className="flex flex-col overflow-hidden rounded-panel border border-border bg-surface">
      <div className="flex flex-col gap-3.5 border-b border-border px-6 py-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-mono text-label font-normal text-fg-muted">
            change-set {changeSet.id} · {changeSet.kind}
          </span>
          <StatusBadge status={changeSet.status} />
        </div>
        <h2 className="text-title-2">{changeSet.title}</h2>
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="flex flex-col gap-0.5">
            <dt className="text-label text-fg-muted">Proposed by</dt>
            <dd className="text-body leading-5">{changeSet.proposer}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label text-fg-muted">Base version</dt>
            <dd className="font-mono text-code">{changeSet.baseVersion}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label text-fg-muted">Publishes as</dt>
            <dd className="font-mono text-code">{changeSet.publishesAs}</dd>
          </div>
        </dl>
      </div>
      <div className="flex flex-col overflow-x-auto border-b border-border py-2 font-mono text-code">
        {changeSet.diff.map((row, i) => (
          <DiffLine key={i} row={row} />
        ))}
      </div>
      <div className="flex flex-col gap-2 border-b border-border px-6 py-4">
        <h3 className="font-mono text-overline text-fg-muted uppercase">
          Checks
        </h3>
        <ul className="flex flex-col gap-2">
          {changeSet.checks.map(check => (
            <li
              key={check.text}
              className="flex items-center gap-2 text-body leading-5"
            >
              <CheckResultIcon result={check.result} />
              <span>
                {check.text}
                {check.link && (
                  <a
                    href={check.link.href}
                    className="ml-1 text-small text-link"
                  >
                    {check.link.label}
                  </a>
                )}
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-4 bg-bg px-6 py-4">
        <span className="flex items-center gap-2 text-small text-fg-secondary">
          <LockIcon size={16} />
          Maker–checker: the proposer cannot approve
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="danger" onClick={onReject}>
            Reject
          </Button>
          <Button onClick={onRequestChanges}>Request changes</Button>
          <Button variant="primary" disabled={!canApprove} onClick={onApprove}>
            Approve and publish {changeSet.publishesAs.split(' ').pop()}
          </Button>
        </div>
      </div>
    </article>
  );
}

/** A SKOS concept: labels, alternative labels and its place in the tree. */
export function ConceptCard({concept}: {concept: Concept}) {
  const [title] = concept.prefLabels;
  return (
    <article className="flex flex-col gap-3.5 rounded-panel border border-border bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <h3 className="text-[1.125rem] leading-[1.625rem] font-semibold">
            {title.label}
          </h3>
          <span className="font-mono text-label font-normal text-fg-muted">
            {concept.uri}
          </span>
        </div>
        <StatusBadge status={concept.status} />
      </div>
      <dl className="grid grid-cols-[5.75rem_minmax(0,1fr)] gap-x-3 gap-y-2.5 text-body leading-5">
        <dt className="text-label text-fg-muted">Labels</dt>
        <dd className="flex flex-col gap-1">
          {concept.prefLabels.map(pref => (
            <span key={pref.lang} lang={pref.lang}>
              <span className="font-mono text-[0.6875rem] text-fg-muted">
                {pref.lang}
              </span>
              {'  '}
              {pref.label}
            </span>
          ))}
        </dd>
        <dt className="text-label text-fg-muted">Also</dt>
        <dd className="text-fg-secondary">{concept.altLabels.join(', ')}</dd>
        <dt className="text-label text-fg-muted">Broader</dt>
        <dd className="flex flex-wrap gap-x-3">
          {concept.broader.map(ref => (
            <a key={ref.label} href={ref.href} className="text-link">
              {ref.label}
            </a>
          ))}
        </dd>
        <dt className="text-label text-fg-muted">Narrower</dt>
        <dd className="flex flex-wrap gap-x-3">
          {concept.narrower.map(ref => (
            <a key={ref.label} href={ref.href} className="text-link">
              {ref.label}
            </a>
          ))}
        </dd>
      </dl>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-graphite-100 pt-3 dark:border-border">
        <span className="text-small text-fg-muted">
          Expands queries in{' '}
          <span className="font-mono text-label font-normal">
            {concept.profile}
          </span>
        </span>
        <a href={concept.href} className="text-small font-medium text-link">
          Open in taxonomy
        </a>
      </div>
    </article>
  );
}

const AUDIT_DOT: Partial<Record<LifecycleStatus, string>> = {
  candidate: 'border-2 border-dashed border-candidate-border bg-surface',
  validated: 'border-2 border-validated-fg bg-validated-bg',
  approved: 'bg-approved-bg',
  rejected: 'border-2 border-rejected-fg bg-rejected-bg',
  superseded: 'bg-superseded-fg',
};

/** Recorded transitions, newest first. Nothing is ever deleted. */
export function AuditTrail({events}: {events: AuditEvent[]}) {
  return (
    <ol className="flex flex-col rounded-panel border border-border bg-surface p-5">
      {events.map((event, i) => {
        const last = i === events.length - 1;
        return (
          <li
            key={`${event.at}-${event.action}`}
            className={cx(
              'grid grid-cols-[1rem_minmax(0,1fr)] gap-x-3',
              !last && 'pb-4',
            )}
          >
            <span aria-hidden="true" className="flex flex-col items-center">
              <span
                className={cx(
                  'mt-1.25 size-2.5 rounded-pill',
                  AUDIT_DOT[event.status],
                )}
              />
              {!last && <span className="mt-1 w-px grow bg-border" />}
            </span>
            <span className="flex flex-col gap-0.5">
              <span className="text-body leading-5">
                <strong className="font-semibold">{event.action}</strong> by{' '}
                {event.actor}
              </span>
              <span className="font-mono text-label font-normal text-fg-muted">
                {event.at} · {event.reference}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function EntityCard({entity}: {entity: EntityRecord}) {
  return (
    <div
      className={cx(
        'flex flex-col gap-2 rounded-control border p-4.5',
        entity.status === 'candidate'
          ? 'border-dashed border-candidate-border'
          : 'border-border',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-label font-normal text-fg-muted">
          {entity.id}
        </span>
        <StatusBadge status={entity.status} />
      </div>
      <span className="text-title-3">{entity.name}</span>
      <span className="text-small text-fg-secondary">
        {entity.type} · {entity.origin} · cited in{' '}
        <span className="font-mono text-label font-normal tabular-nums">
          {entity.citedIn}
        </span>{' '}
        documents
      </span>
    </div>
  );
}

/**
 * Should a candidate entity merge into an existing one? Shows both records
 * and the evidence for and against. A merge can be split later.
 */
export function EntityResolution({
  existing,
  candidate,
  signals,
  question = 'Same organization?',
  actions,
}: {
  existing: EntityRecord;
  candidate: EntityRecord;
  signals: MatchSignal[];
  question?: string;
  /** Decision buttons, primary last. */
  actions?: ReactNode;
}) {
  return (
    <article className="flex flex-col overflow-hidden rounded-panel border border-border bg-surface">
      <div className="grid grid-cols-1 items-center gap-6 p-6 lg:grid-cols-[minmax(0,1fr)_21.25rem_minmax(0,1fr)]">
        <EntityCard entity={existing} />
        <div className="flex flex-col gap-2">
          <span className="text-center text-body leading-5 font-semibold">
            {question}
          </span>
          <ul className="flex flex-col gap-2">
            {signals.map(signal => (
              <li
                key={signal.label}
                className="flex items-center justify-between gap-2 text-small"
              >
                <span className="flex items-center gap-1.5">
                  <CheckResultIcon result={signal.result} size={14} />
                  {signal.label}
                </span>
                <span className="font-mono text-label font-normal">
                  {signal.value}
                </span>
              </li>
            ))}
          </ul>
        </div>
        <EntityCard entity={candidate} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-4 border-t border-border bg-bg px-6 py-4">
        <span className="text-small text-fg-secondary">
          A merge can be split later. Both ids stay resolvable, and the decision
          is recorded with its reason.
        </span>
        {actions && (
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        )}
      </div>
    </article>
  );
}
