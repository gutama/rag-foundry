import type {ReactNode} from 'react';

import {AnswerBadge} from '../components/badge';
import {cx} from '../lib/cx';
import type {Abstention} from '../types';

/**
 * An abstention is a result, styled with the same care as an answer: it says
 * what was searched, why it fell short, and offers a next step.
 */
export function AbstentionCard({
  abstention,
  headingLevel = 2,
  actions,
  className,
}: {
  abstention: Abstention;
  headingLevel?: 2 | 3;
  /** Next steps, e.g. widen the scope or ask a steward. */
  actions?: ReactNode;
  className?: string;
}) {
  const Heading = headingLevel === 2 ? 'h2' : 'h3';
  return (
    <article
      className={cx(
        'flex flex-col gap-4 rounded-panel border border-border-control bg-surface p-6',
        className,
      )}
    >
      <AnswerBadge support="abstained" />
      <div className="flex flex-col gap-1.5">
        <Heading className="text-[1.125rem] leading-[1.625rem] font-semibold">
          {abstention.title}
        </Heading>
        <p className="text-[0.9375rem] leading-6 text-fg-secondary">
          {abstention.explanation}
        </p>
      </div>
      <dl className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-y-1.5 rounded-control bg-bg px-4 py-3 font-mono text-label leading-5 font-normal">
        <dt className="text-fg-muted">searched</dt>
        <dd>{abstention.searched.join(' · ')}</dd>
        <dt className="text-fg-muted">passages scored</dt>
        <dd className="tabular-nums">{abstention.passagesScored}</dd>
        <dt className="text-fg-muted">best rerank score</dt>
        <dd className="tabular-nums">
          {abstention.highestScore.toFixed(2)}{' '}
          <span className="text-fg-muted">
            · answer threshold {abstention.threshold.toFixed(2)}
          </span>
        </dd>
      </dl>
      {actions && (
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      )}
    </article>
  );
}
