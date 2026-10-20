import {Fragment, useState, type ReactNode} from 'react';

import {AnswerBadge} from '../components/badge';
import {CitationMarker} from '../components/citation';
import {countClaims} from '../lib/citations';
import {cx} from '../lib/cx';
import type {Answer, AnswerSegment} from '../types';

/** Identifies one marker: claim, segment and source, e.g. "0.0.1". */
function markerKey(claim: number, segment: number, source: number) {
  return `${claim}.${segment}.${source}`;
}

function firstMarkerFor(answer: Answer, source: number) {
  for (const [c, claim] of answer.claims.entries()) {
    for (const [s, segment] of claim.segments.entries()) {
      if (segment.citations?.includes(source)) return markerKey(c, s, source);
    }
  }
  return undefined;
}

function UnsupportedText({segment}: {segment: AnswerSegment}) {
  return (
    <>
      <span className="text-fg-secondary underline decoration-caution-fg decoration-dashed decoration-[1.5px] underline-offset-4">
        {segment.text}
      </span>
      <span className="ml-1.5 inline-block h-5 rounded-stamp bg-caution-bg px-1.5 align-[2px] font-mono text-[0.6875rem] leading-5 font-medium text-caution-fg">
        unsupported
      </span>
    </>
  );
}

interface AnswerCardProps {
  answer: Answer;
  /** Source open in the evidence panel or viewer. */
  openSource?: number;
  onSelectSource?: (index: number) => void;
  /** Shows the semantic profile beside the badge. */
  showProfile?: boolean;
  /** A notice under the answer, e.g. why part of it is unsupported. */
  notice?: ReactNode;
  /** Text buttons in the footer, beside the taxonomy note. */
  actions?: ReactNode;
  className?: string;
}

/**
 * A generated answer with a marker after each supported clause. Selecting a
 * marker opens its source and inverts that marker while the source is open.
 */
export function AnswerCard({
  answer,
  openSource,
  onSelectSource,
  showProfile = false,
  notice,
  actions,
  className,
}: AnswerCardProps) {
  const [selected, setSelected] = useState<{key: string; source: number}>();
  const {cited, total} = countClaims(answer);

  // The marker the reader chose, unless the open source changed elsewhere.
  const openKey =
    openSource === undefined
      ? undefined
      : selected?.source === openSource
        ? selected.key
        : firstMarkerFor(answer, openSource);

  function select(key: string, source: number) {
    setSelected({key, source});
    onSelectSource?.(source);
  }

  return (
    <article
      className={cx(
        'flex flex-col rounded-panel border border-border bg-surface',
        className,
      )}
    >
      <div className="flex flex-col gap-4 px-6 pt-6 pb-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <AnswerBadge support={answer.support} cited={cited} total={total} />
          {showProfile && (
            <span className="font-mono text-label font-normal text-fg-muted">
              profile {answer.profile}
            </span>
          )}
        </div>
        <p className="text-body-lg">
          {answer.claims.map((claim, c) => (
            <Fragment key={c}>
              {c > 0 && ' '}
              {claim.segments.map((segment, s) => (
                <Fragment key={s}>
                  {segment.unsupported ? (
                    <UnsupportedText segment={segment} />
                  ) : (
                    segment.text
                  )}
                  {segment.citations?.map(source => {
                    const key = markerKey(c, s, source);
                    return (
                      <CitationMarker
                        key={key}
                        index={source}
                        inline
                        state={key === openKey ? 'open' : 'default'}
                        onSelect={
                          onSelectSource ? () => select(key, source) : undefined
                        }
                      />
                    );
                  })}
                </Fragment>
              ))}
            </Fragment>
          ))}
        </p>
        {notice}
      </div>
      {actions && (
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-graphite-100 py-2.5 pr-4 pl-6 dark:border-border">
          <span className="text-small text-fg-muted">
            Terms checked against{' '}
            <span className="font-mono text-label font-normal text-fg-secondary dark:text-fg">
              {answer.taxonomy}
            </span>
          </span>
          <div className="flex flex-wrap items-center gap-1">{actions}</div>
        </div>
      )}
    </article>
  );
}
