import type {CSSProperties, ReactNode} from 'react';

import {cx} from '../lib/cx';
import type {Excerpt, Source} from '../types';

/**
 * - `default`: a cited source, closed.
 * - `open`: its source is open in the evidence panel; the marker inverts.
 * - `failed`: the citation failed validation and is struck through.
 */
export type CitationState = 'default' | 'open' | 'failed';

const MARKER =
  'inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-stamp px-1.25 font-mono text-[0.6875rem] leading-5 font-medium tabular-nums';

const MARKER_STATES: Record<CitationState, string> = {
  default: 'bg-evidence-marker text-on-evidence-marker',
  open: 'bg-evidence-marker-active text-on-evidence-marker-active',
  failed:
    'border border-dashed border-danger-fg bg-danger-bg text-danger-fg line-through',
};

/** Rings for markers the reader can press; static labels stay flat. */
const PRESSABLE_STATES: Record<CitationState, string> = {
  default:
    'cursor-pointer hover:bg-ingot-300 hover:outline-[1.5px] hover:outline-offset-2 hover:outline-ingot-700 focus-visible:bg-ingot-300 focus-visible:outline-[1.5px] focus-visible:outline-ingot-700 dark:hover:outline-ingot-400 dark:focus-visible:outline-ingot-400',
  // On dark, the inverted marker alone is too quiet, so it keeps a ring.
  open: 'cursor-pointer dark:outline-[1.5px] dark:outline-offset-2 dark:outline-ingot-400',
  failed: 'cursor-pointer',
};

/** Space before an inline marker, and a nudge up off the baseline. */
const INLINE = 'ml-0.75 align-[2px]';

interface CitationMarkerProps {
  index: number;
  state?: CitationState;
  /** Opens the source. Without it the marker is a static label. */
  onSelect?: (index: number) => void;
  /** Places the marker in running text, after the clause it supports. */
  inline?: boolean;
  className?: string;
  style?: CSSProperties;
}

function markerLabel(index: number, state: CitationState) {
  if (state === 'open') return `Source ${index}, open`;
  if (state === 'failed') return `Source ${index}, failed validation`;
  return `Source ${index}`;
}

/** The numbered stamp that ties a claim to its source. */
export function CitationMarker({
  index,
  state = 'default',
  onSelect,
  inline = false,
  className,
  style,
}: CitationMarkerProps) {
  const classes = cx(MARKER, MARKER_STATES[state], inline && INLINE, className);
  if (!onSelect) {
    return (
      <span className={classes} style={style}>
        {index}
      </span>
    );
  }
  return (
    <button
      type="button"
      aria-label={markerLabel(index, state)}
      aria-pressed={state === 'open'}
      className={cx(classes, PRESSABLE_STATES[state])}
      style={style}
      onClick={() => onSelect(index)}
    >
      {index}
    </button>
  );
}

/** A span quoted from a source, highlighted as evidence. */
export function EvidenceHighlight({children}: {children: ReactNode}) {
  return (
    <mark className="rounded-[2px] bg-evidence-highlight text-inherit shadow-[0_0_0_2px_var(--rf-evidence-highlight)]">
      {children}
    </mark>
  );
}

/** Excerpt text in the source voice, with the cited span highlighted. */
export function ExcerptText({
  excerpt,
  quoted = false,
  className,
}: {
  excerpt: Excerpt;
  /** Wraps the excerpt in quotation marks. */
  quoted?: boolean;
  className?: string;
}) {
  return (
    <p className={cx('font-serif text-fg', className)}>
      {quoted && '“'}
      {excerpt.before}
      <EvidenceHighlight>{excerpt.cited}</EvidenceHighlight>
      {excerpt.after}
      {quoted && '”'}
    </p>
  );
}

/** The card a citation marker opens on hover or focus. */
export function SourcePreview({
  source,
  href = '#',
  className,
}: {
  source: Source;
  /** Opens the document viewer at the cited page. */
  href?: string;
  className?: string;
}) {
  return (
    <div
      className={cx(
        'flex flex-col gap-2.5 rounded-panel border border-border bg-surface-raised px-4 py-3.5 shadow-popover',
        className,
      )}
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-overline text-fg-muted uppercase">
          Source {source.index} · p.{source.page}
        </span>
        <span className="font-mono text-[0.6875rem] text-fg-muted">
          {source.revision}
        </span>
      </div>
      <span className="text-body leading-5 font-semibold">
        {source.documentTitle}
      </span>
      <ExcerptText excerpt={source.excerpt} className="text-body leading-5.5" />
      <div className="flex items-center justify-between">
        <a href={href} className="text-small font-medium text-link">
          Open at page {source.page}
        </a>
        <span className="font-mono text-[0.6875rem] text-fg-muted">
          {source.chunkId}
        </span>
      </div>
    </div>
  );
}
