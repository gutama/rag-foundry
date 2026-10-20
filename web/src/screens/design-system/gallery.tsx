import {SegmentedControl} from '../../components/facets';
import {Logo} from '../../components/logo';
import type {Theme} from '../../lib/theme';
import {cx} from '../../lib/cx';
import {ComponentsBoard} from './components-board';
import {EvidenceBoard} from './evidence-board';
import {GovernanceBoard} from './governance-board';
import {OverviewBoard} from './overview-board';

export const BOARDS = [
  {id: 'overview', label: 'Overview', render: () => <OverviewBoard />},
  {id: 'components', label: 'Components', render: () => <ComponentsBoard />},
  {id: 'evidence', label: 'Evidence', render: () => <EvidenceBoard />},
  {id: 'governance', label: 'Governance', render: () => <GovernanceBoard />},
] as const;

export type BoardId = (typeof BOARDS)[number]['id'];

/** The Assay design-system pages, with a theme switch to check both themes. */
export function Gallery({
  board,
  theme,
  onThemeChange,
}: {
  board: BoardId;
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
}) {
  const current = BOARDS.find(b => b.id === board) ?? BOARDS[0];
  return (
    <div className="flex min-h-screen flex-col bg-bg text-fg">
      <header className="flex flex-wrap items-center justify-between gap-x-8 gap-y-3 border-b border-border px-4 py-5 sm:px-16">
        <div className="flex items-center gap-3">
          <Logo />
          <span className="text-title-3 tracking-[-0.005em]">RAG Foundry</span>
          <span className="font-mono text-label font-normal text-fg-muted">
            design-system / assay / v0.1
          </span>
        </div>
        <nav
          aria-label="Design system"
          className="flex flex-wrap items-center gap-1"
        >
          {BOARDS.map(b => (
            <a
              key={b.id}
              href={`#/design/${b.id}`}
              aria-current={b.id === current.id ? 'page' : undefined}
              className={cx(
                'flex h-8 items-center rounded-control px-2.5 text-small font-medium no-underline',
                b.id === current.id
                  ? 'bg-surface-sunken text-fg'
                  : 'text-fg-secondary hover:text-fg',
              )}
            >
              {b.label}
            </a>
          ))}
          <a
            href="#/ask"
            className="flex h-8 items-center rounded-control px-2.5 text-small font-medium text-link no-underline"
          >
            Ask screen
          </a>
        </nav>
        <SegmentedControl<Theme>
          label="Theme"
          options={[
            {value: 'system', label: 'System'},
            {value: 'light', label: 'Light'},
            {value: 'dark', label: 'Dark'},
          ]}
          value={theme}
          onChange={onThemeChange}
        />
      </header>
      <main className="flex grow flex-col">{current.render()}</main>
    </div>
  );
}
