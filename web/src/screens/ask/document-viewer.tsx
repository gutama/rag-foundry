import {useEffect, useRef} from 'react';

import {IconButton} from '../../components/button';
import {CitationMarker} from '../../components/citation';
import {ChevronLeftIcon, ChevronRightIcon} from '../../components/icons';
import {ChannelTags, SignalTag} from '../../components/signals';
import {cx} from '../../lib/cx';
import type {Source} from '../../types';

/**
 * The cited page beside the answer, scrolled to the highlighted span. The
 * page canvas stays on paper (light theme) whatever the app theme is.
 */
export function DocumentViewer({
  source,
  onPreviousPage,
  onNextPage,
  originalHref = '#',
}: {
  source: Source;
  /** Page turns are disabled until a handler is given. */
  onPreviousPage?: () => void;
  onNextPage?: () => void;
  originalHref?: string;
}) {
  const highlight = useRef<HTMLParagraphElement>(null);
  const shown = useRef(source.index);

  // Bring the cited span into view when the reader opens another source.
  useEffect(() => {
    if (shown.current === source.index) return;
    shown.current = source.index;
    highlight.current?.scrollIntoView?.({block: 'nearest', behavior: 'smooth'});
  }, [source.index]);

  return (
    <aside
      aria-label="Document viewer"
      className="flex min-w-0 flex-[1_1_32.5rem] flex-col border-l border-border bg-surface"
    >
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3.5">
        <div className="flex min-w-0 items-center gap-2.5">
          <CitationMarker index={source.index} state="open" />
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-body leading-5 font-semibold">
              {source.documentTitle}
            </span>
            <span className="font-mono text-label font-normal text-fg-muted">
              {source.revision} · {source.locator}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <IconButton
            label="Previous page"
            variant="ghost"
            size="compact"
            disabled={!onPreviousPage}
            onClick={onPreviousPage}
            className="disabled:text-fg-muted"
          >
            <ChevronLeftIcon />
          </IconButton>
          <span className="font-mono text-label font-normal tabular-nums">
            {source.page} / {source.pageCount}
          </span>
          <IconButton
            label="Next page"
            variant="ghost"
            size="compact"
            disabled={!onNextPage}
            onClick={onNextPage}
            className="disabled:text-fg-muted"
          >
            <ChevronRightIcon />
          </IconButton>
        </div>
      </div>
      <div className="flex grow justify-center bg-surface-sunken p-6">
        <div
          data-theme="light"
          className="relative flex w-full max-w-[27.5rem] flex-col gap-2.5 rounded-[2px] bg-bg px-10 pt-10 pb-12 font-serif text-[0.71875rem] leading-[1.125rem] text-fg"
        >
          {source.pageBlocks.map((block, i) =>
            block.kind === 'heading' ? (
              <span
                key={i}
                className={cx('text-small font-semibold', i > 0 && 'mt-1.5')}
              >
                {block.text}
              </span>
            ) : (
              <p
                key={i}
                ref={block.cited ? highlight : undefined}
                className={
                  block.cited
                    ? 'rounded-[1px] bg-evidence-highlight shadow-[0_0_0_4px_var(--rf-evidence-highlight),0_0_0_6px_var(--rf-evidence-stroke)]'
                    : undefined
                }
              >
                {block.cited && <span className="sr-only">Cited: </span>}
                {block.text}
              </p>
            ),
          )}
          <span className="absolute bottom-4.5 left-10 font-mono text-[0.625rem] text-fg-muted">
            {source.documentTitle} · {source.revision} · page {source.page} of{' '}
            {source.pageCount}
          </span>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3">
        <div className="flex flex-wrap gap-1.5">
          <ChannelTags signals={source.signals} />
          <SignalTag
            label={`RERANK ${source.signals.rerank.toFixed(2)}`}
            emphasis="score"
          />
        </div>
        <a href={originalHref} className="text-small font-medium text-link">
          Open original
        </a>
      </div>
    </aside>
  );
}
