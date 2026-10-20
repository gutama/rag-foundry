import {useRef, type KeyboardEvent} from 'react';

import {cx} from '../lib/cx';
import {CheckIcon} from './icons';

/** A toggleable filter with its result count. Pills are for facets only. */
export function FacetChip({
  label,
  count,
  selected,
  onToggle,
}: {
  label: string;
  count?: number;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onToggle}
      className={cx(
        'inline-flex h-8 items-center gap-2 rounded-pill border px-3 text-small font-medium',
        selected
          ? 'border-action bg-action-subtle text-on-action-subtle'
          : 'border-border-control bg-surface text-fg hover:bg-surface-sunken',
      )}
    >
      {selected && <CheckIcon />}
      {label}
      {count !== undefined && (
        <span
          className={cx(
            'font-mono text-label font-normal tabular-nums',
            selected ? 'text-link' : 'text-fg-muted',
          )}
        >
          {count}
        </span>
      )}
    </button>
  );
}

/** A read-only chip naming a collection the query is scoped to. */
export function ScopeChip({label}: {label: string}) {
  return (
    <span className="inline-flex h-7 items-center rounded-pill border border-action bg-action-subtle px-2.5 text-label text-on-action-subtle">
      {label}
    </span>
  );
}

export interface TabItem {
  id: string;
  label: string;
  count?: number;
}

/** Underlined tabs. Arrow keys move between them. */
export function Tabs({
  label,
  tabs,
  selected,
  onSelect,
}: {
  /** Accessible name of the tab list. */
  label: string;
  tabs: TabItem[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  function onKeyDown(event: KeyboardEvent, position: number) {
    const step = {ArrowRight: 1, ArrowLeft: -1}[event.key];
    if (!step) return;
    event.preventDefault();
    const next = (position + step + tabs.length) % tabs.length;
    onSelect(tabs[next].id);
    refs.current[next]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      className="flex grow gap-6 border-b border-border"
    >
      {tabs.map((tab, position) => {
        const active = tab.id === selected;
        return (
          <button
            key={tab.id}
            ref={el => {
              refs.current[position] = el;
            }}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onSelect(tab.id)}
            onKeyDown={event => onKeyDown(event, position)}
            className={cx(
              '-mb-px inline-flex h-10 items-center gap-1.5 border-b-2 text-body',
              active
                ? 'border-fg font-semibold text-fg'
                : 'border-transparent font-medium text-fg-muted hover:text-fg',
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="font-mono text-label font-normal tabular-nums">
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** A small set of mutually exclusive modes on a sunken track. */
export function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  /** Accessible name of the group. */
  label: string;
  options: Array<{value: T; label: string}>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="flex gap-0.5 rounded-control bg-surface-sunken p-0.75"
    >
      {options.map(option => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={cx(
              'h-7.5 rounded-[4px] px-3 text-small font-medium',
              active
                ? 'bg-surface text-fg shadow-[0_1px_2px_rgb(14_17_22/0.12)]'
                : 'text-fg-secondary hover:text-fg',
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
