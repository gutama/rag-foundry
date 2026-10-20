import {cx} from '../lib/cx';
import type {RetrievalSignals} from '../types';

/**
 * - `default`: a channel rank or fused score.
 * - `score`: the rerank score that decided the order.
 * - `optional`: a hit from the optional graph provider, dashed because it is
 *   explained, never assumed.
 */
export type SignalEmphasis = 'default' | 'score' | 'optional';

const EMPHASIS: Record<SignalEmphasis, string> = {
  default:
    'border-border text-fg-secondary dark:border-border-strong dark:text-fg-muted',
  score:
    'border-info-border bg-action-subtle text-on-action-subtle dark:border-action',
  optional: 'border-dashed border-border-control text-fg-secondary',
};

/** A mono tag such as "LEX 2" or "RERANK 0.91". */
export function SignalTag({
  label,
  emphasis = 'default',
}: {
  label: string;
  emphasis?: SignalEmphasis;
}) {
  return (
    <span
      className={cx(
        'h-5 rounded-stamp border px-1.5 font-mono text-[0.6875rem] leading-[1.125rem] whitespace-nowrap tabular-nums',
        EMPHASIS[emphasis],
      )}
    >
      {label}
    </span>
  );
}

/** Tags for each channel that returned the passage. */
export function ChannelTags({signals}: {signals: RetrievalSignals}) {
  return (
    <>
      {signals.lexicalRank !== undefined && (
        <SignalTag label={`LEX ${signals.lexicalRank}`} />
      )}
      {signals.denseRank !== undefined && (
        <SignalTag label={`DENSE ${signals.denseRank}`} />
      )}
      {signals.graph && <SignalTag label="GRAPH" emphasis="optional" />}
    </>
  );
}

/** A 0–1 score as a bar and its value. */
export function ScoreBar({score, label}: {score: number; label: string}) {
  return (
    <span className="flex items-center gap-2">
      <span
        role="meter"
        aria-label={label}
        aria-valuenow={score}
        aria-valuemin={0}
        aria-valuemax={1}
        className="h-1.5 grow overflow-hidden rounded-[3px] bg-surface-sunken"
      >
        <span
          className="block h-1.5 bg-action"
          style={{width: `${Math.round(score * 100)}%`}}
        />
      </span>
      <span className="font-mono text-label font-normal tabular-nums">
        {score.toFixed(2)}
      </span>
    </span>
  );
}

/** One ranked passage: position, document, channel ranks and rerank score. */
export function RetrievalSignalRow({
  rank,
  title,
  signals,
}: {
  rank: number;
  title: string;
  signals: RetrievalSignals;
}) {
  return (
    <div className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-center gap-3.5 sm:grid-cols-[1.25rem_minmax(0,1fr)_auto_8.75rem]">
      <span className="font-mono text-label font-normal text-fg-muted tabular-nums">
        {rank}
      </span>
      <span className="text-body leading-5">{title}</span>
      <span className="flex gap-1">
        <ChannelTags signals={signals} />
      </span>
      <span className="col-span-full sm:col-span-1">
        <ScoreBar score={signals.rerank} label={`Rerank score for ${title}`} />
      </span>
    </div>
  );
}
