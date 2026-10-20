import {cx} from '../lib/cx';
import type {DocumentRow} from '../types';
import {StatusBadge} from './badge';

const HEAD =
  'border-b border-border px-4 py-2.5 font-mono text-overline text-fg-muted uppercase';

/** Lighter than the table outline, so rows read as one block. */
const CELL = 'border-b border-graphite-100 px-4 py-2.25 dark:border-border';

/**
 * Compact document rows. Identifiers and numbers are mono, the selected row
 * is tinted, and superseded revisions are muted.
 */
export function DocumentTable({
  rows,
  selectedRow,
  hrefFor = () => '#',
}: {
  rows: DocumentRow[];
  /** Position of the selected row, if any. */
  selectedRow?: number;
  hrefFor?: (row: DocumentRow) => string;
}) {
  return (
    <div className="overflow-x-auto border border-border bg-surface">
      <table className="w-full min-w-[45rem] border-collapse text-body">
        <thead>
          <tr className="bg-bg text-left">
            <th scope="col" className={HEAD}>
              Document
            </th>
            <th scope="col" className={HEAD}>
              Collection
            </th>
            <th scope="col" className={HEAD}>
              Revision
            </th>
            <th scope="col" className={cx(HEAD, 'text-right')}>
              Pages
            </th>
            <th scope="col" className={HEAD}>
              Status
            </th>
            <th scope="col" className={HEAD}>
              Updated
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, position) => {
            const muted = row.status === 'superseded';
            return (
              <tr
                key={`${row.id}@${row.revision}`}
                className={cx(
                  position === selectedRow && 'bg-action-subtle',
                  '[&:last-child>td]:border-b-0',
                )}
              >
                <td className={CELL}>
                  <span className="flex items-baseline gap-2.5">
                    <a
                      href={hrefFor(row)}
                      className={cx(
                        'font-medium no-underline hover:underline',
                        muted ? 'text-fg-muted' : 'text-fg',
                      )}
                    >
                      {row.title}
                    </a>
                    <span className="font-mono text-label font-normal text-fg-muted">
                      {row.id}
                    </span>
                  </span>
                </td>
                <td
                  className={cx(
                    CELL,
                    muted ? 'text-fg-muted' : 'text-fg-secondary',
                  )}
                >
                  {row.collection}
                </td>
                <td
                  className={cx(
                    CELL,
                    'font-mono text-code',
                    muted && 'text-fg-muted',
                  )}
                >
                  {row.revision}
                </td>
                <td
                  className={cx(
                    CELL,
                    'text-right font-mono text-code tabular-nums',
                    muted && 'text-fg-muted',
                  )}
                >
                  {row.pages}
                </td>
                <td className={CELL}>
                  <StatusBadge status={row.status} />
                </td>
                <td className={cx(CELL, 'text-small text-fg-muted')}>
                  {row.updated}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
