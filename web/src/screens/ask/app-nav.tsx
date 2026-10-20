import type {ComponentType} from 'react';

import {
  CatalogIcon,
  CollectionsIcon,
  EvalsIcon,
  LockIcon,
  SearchIcon,
  SourcesIcon,
  StewardshipIcon,
} from '../../components/icons';
import {Logo} from '../../components/logo';
import {cx} from '../../lib/cx';

export interface NavItem {
  id: string;
  label: string;
  href: string;
  icon: ComponentType<{size?: number; className?: string}>;
  /** Items waiting for the reader, e.g. reviews in Stewardship. */
  count?: number;
}

export const NAV_ITEMS: NavItem[] = [
  {id: 'ask', label: 'Ask', href: '#/ask', icon: SearchIcon},
  {
    id: 'collections',
    label: 'Collections',
    href: '#/collections',
    icon: CollectionsIcon,
  },
  {id: 'sources', label: 'Sources', href: '#/sources', icon: SourcesIcon},
  {id: 'catalog', label: 'Catalog', href: '#/catalog', icon: CatalogIcon},
  {
    id: 'stewardship',
    label: 'Stewardship',
    href: '#/stewardship',
    icon: StewardshipIcon,
  },
  {id: 'evals', label: 'Evals', href: '#/evals', icon: EvalsIcon},
  {id: 'admin', label: 'Admin', href: '#/admin', icon: LockIcon},
];

/** The application sidebar, with the deployment profile at its foot. */
export function AppNav({
  items,
  current,
  deployment,
}: {
  items: NavItem[];
  current: string;
  /** Storage profile and network mode, e.g. "compact · air-gapped". */
  deployment: string;
}) {
  return (
    <nav
      aria-label="Main"
      className="flex flex-[1_1_14.5rem] flex-col gap-6 border-r border-border bg-bg px-3.5 py-5"
    >
      <div className="flex items-center gap-2.5 px-2">
        <Logo size={24} />
        <span className="text-[0.9375rem] font-semibold">RAG Foundry</span>
      </div>
      <ul className="flex flex-col gap-0.5">
        {items.map(item => {
          const active = item.id === current;
          const Icon = item.icon;
          return (
            <li key={item.id}>
              <a
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={cx(
                  'flex h-10 items-center gap-2.5 rounded-control px-2.5 text-body no-underline',
                  active
                    ? 'bg-surface-raised font-semibold text-fg'
                    : 'font-medium text-fg-secondary hover:bg-surface hover:text-fg',
                )}
              >
                <Icon size={18} />
                <span className="grow">{item.label}</span>
                {item.count !== undefined && (
                  <span className="h-5 min-w-5 rounded-stamp border border-border-strong bg-surface-raised px-1.5 text-center font-mono text-[0.6875rem] leading-[1.125rem] text-fg tabular-nums">
                    {item.count}
                  </span>
                )}
              </a>
            </li>
          );
        })}
      </ul>
      <div className="mt-auto flex flex-col gap-1 rounded-control border border-border px-2.5 py-3">
        <span className="font-mono text-overline text-fg-muted uppercase">
          Deployment
        </span>
        <span className="font-mono text-label font-normal">{deployment}</span>
      </div>
    </nav>
  );
}
