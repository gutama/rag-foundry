import {useId} from 'react';

import {StatusBadge} from '../components/badge';
import {CitationMarker, ExcerptText} from '../components/citation';
import {ChevronDownIcon, LockIcon} from '../components/icons';
import {ChannelTags, SignalTag} from '../components/signals';
import {bboxLabel, sourceLocation} from '../lib/citations';
import {cx} from '../lib/cx';
import type {Source} from '../types';

/** Widths of the schematic text lines; `h` marks a heading line. */
const SKETCH: Array<{w: string; h?: boolean; gap?: boolean}> = [
  {w: 'w-[46%]', h: true},
  {w: 'w-full', gap: true},
  {w: 'w-[96%]'},
  {w: 'w-[88%]'},
  {w: 'w-[30%]', h: true, gap: true},
  {w: 'w-full'},
  {w: 'w-[98%]'},
  {w: 'w-full'},
  {w: 'w-[72%]'},
  {w: 'w-full', gap: true},
  {w: 'w-[92%]'},
  {w: 'w-[64%]'},
];

/**
 * A schematic of the cited page with its bounding box drawn over the cited
 * region. It stands in for the rendered page crop. Pages stay on paper, so
 * it is always drawn in the light theme.
 */
export function PageThumbnail({source}: {source: Source}) {
  return (
    <div
      data-theme="light"
      role="img"
      aria-label={`Page ${source.page} with the cited region outlined`}
      className="relative flex h-58 flex-col gap-2.25 overflow-hidden rounded-stamp border border-border bg-surface px-6.5 py-5.5 shadow-[0_1px_0_var(--rf-graphite-100)]"
    >
      {SKETCH.map((line, i) => (
        <div
          key={i}
          className={cx(
            line.w,
            'shrink-0 rounded-[2px]',
            line.h ? 'h-2 bg-border-strong' : 'h-1.5 bg-surface-sunken',
            line.gap && 'mt-1.5',
          )}
        />
      ))}
      <div className="absolute inset-x-5 top-26 h-13 rounded-stamp border-2 border-evidence-stroke bg-[color-mix(in_srgb,var(--rf-evidence-highlight)_45%,transparent)]" />
      <span className="absolute top-20.5 right-5 h-4.5 rounded-stamp bg-evidence-stroke px-1.5 font-mono text-[0.625rem] leading-4.5 font-medium text-ingot-950">
        bbox {bboxLabel(source.bbox, source.pageSize)}
      </span>
      <span className="absolute bottom-3 left-6.5 font-mono text-[0.625rem] text-fg-muted">
        p.{source.page}
      </span>
    </div>
  );
}

function OpenSource({
  source,
  onToggle,
}: {
  source: Source;
  onToggle: () => void;
}) {
  return (
    <div
      id={`source-${source.index}`}
      className="flex flex-col gap-3.5 border-b border-border px-5 pt-4.5 pb-5"
    >
      <div className="flex items-start gap-2.5">
        <button
          type="button"
          aria-expanded="true"
          onClick={onToggle}
          className="flex grow items-start gap-2.5 text-left"
        >
          <CitationMarker
            index={source.index}
            state="open"
            className="mt-0.5"
          />
          <span className="flex flex-col gap-0.5">
            <span className="text-[0.9375rem] leading-5.5 font-semibold">
              {source.documentTitle}
            </span>
            <span className="font-mono text-label font-normal text-fg-muted">
              {sourceLocation(source)}
            </span>
          </span>
        </button>
        <StatusBadge status={source.status} />
      </div>
      <PageThumbnail source={source} />
      <ExcerptText excerpt={source.excerpt} quoted className="text-quote" />
      <div className="flex flex-wrap items-center gap-1.5">
        <ChannelTags signals={source.signals} />
        {source.signals.rrf !== undefined && (
          <SignalTag label={`RRF ${source.signals.rrf.toFixed(3)}`} />
        )}
        <SignalTag
          label={`RERANK ${source.signals.rerank.toFixed(2)}`}
          emphasis="score"
        />
      </div>
      <div className="flex items-center justify-between">
        <a href="#" className="text-small font-medium text-link">
          Open at page {source.page}
        </a>
        <span className="font-mono text-[0.6875rem] text-fg-muted">
          {source.chunkId}
        </span>
      </div>
    </div>
  );
}

function ClosedSource({
  source,
  onToggle,
}: {
  source: Source;
  onToggle: () => void;
}) {
  return (
    <button
      id={`source-${source.index}`}
      type="button"
      aria-expanded="false"
      onClick={onToggle}
      className="flex w-full items-center gap-2.5 border-b border-border px-5 py-3.5 text-left hover:bg-bg"
    >
      <CitationMarker index={source.index} />
      <span className="flex grow flex-col gap-0.5">
        <span className="text-body leading-5 font-semibold">
          {source.documentTitle}
        </span>
        <span className="font-mono text-label font-normal text-fg-muted">
          {sourceLocation(source)}
        </span>
      </span>
      <ChevronDownIcon className="text-fg-muted" />
    </button>
  );
}

/**
 * The sources behind an answer, one open at a time. Only sources the reader
 * may open are listed; excluded superseded evidence is stated, not hidden.
 */
export function EvidencePanel({
  sources,
  openSource,
  onToggle,
  excludedNote,
}: {
  sources: Source[];
  openSource?: number;
  /** Opens a closed source, or closes the open one. */
  onToggle: (index: number | undefined) => void;
  /** Says what superseded evidence was left out. */
  excludedNote?: string;
}) {
  const titleId = useId();
  return (
    <section
      aria-labelledby={titleId}
      className="flex flex-col overflow-hidden rounded-panel border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-3.5">
        <h2 id={titleId} className="text-title-3">
          Sources{' '}
          <span className="font-mono text-small font-normal text-fg-muted">
            {sources.length}
          </span>
        </h2>
        <span className="inline-flex items-center gap-1.5 text-label font-normal text-fg-muted">
          <LockIcon />
          All checked for your access
        </span>
      </div>
      {sources.map(source =>
        source.index === openSource ? (
          <OpenSource
            key={source.index}
            source={source}
            onToggle={() => onToggle(undefined)}
          />
        ) : (
          <ClosedSource
            key={source.index}
            source={source}
            onToggle={() => onToggle(source.index)}
          />
        ),
      )}
      {excludedNote && (
        <div className="flex items-start gap-2.5 bg-bg px-5 py-3.5">
          <StatusBadge status="superseded" />
          <span className="text-small text-fg-secondary">{excludedNote}</span>
        </div>
      )}
    </section>
  );
}
