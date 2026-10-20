import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {ABSTENTION, SOURCES} from '../fixtures/sample-data';
import {AbstentionCard} from './abstention-card';
import {EvidencePanel} from './evidence-panel';

describe('EvidencePanel', () => {
  it('opens one source with its page, excerpt and signals', () => {
    render(
      <EvidencePanel sources={SOURCES} openSource={1} onToggle={() => {}} />,
    );
    expect(screen.getByRole('heading', {name: 'Sources 3'})).toBeVisible();
    expect(
      screen.getByRole('img', {name: 'Page 12 with the cited region outlined'}),
    ).toHaveTextContent('bbox 72,318 · 540,372');
    expect(screen.getByText('RRF 0.032')).toBeInTheDocument();
    expect(screen.getByText('RERANK 0.91')).toBeInTheDocument();
    expect(screen.getByText('chunk:0f3a91')).toBeInTheDocument();
    expect(
      screen.getByRole('button', {name: /Records Retention Policy/}),
    ).toHaveAttribute('aria-expanded', 'true');
  });

  it('draws the page on paper whatever the theme', () => {
    render(
      <EvidencePanel sources={SOURCES} openSource={1} onToggle={() => {}} />,
    );
    expect(screen.getByRole('img', {name: /Page 12/})).toHaveAttribute(
      'data-theme',
      'light',
    );
  });

  it('opens a closed source and closes the open one', async () => {
    const onToggle = vi.fn();
    render(
      <EvidencePanel sources={SOURCES} openSource={1} onToggle={onToggle} />,
    );
    const closed = screen.getByRole('button', {name: /Records Schedule B/});
    expect(closed).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(closed);
    expect(onToggle).toHaveBeenLastCalledWith(2);
    await userEvent.click(
      screen.getByRole('button', {name: /Records Retention Policy/}),
    );
    expect(onToggle).toHaveBeenLastCalledWith(undefined);
  });

  it('states what superseded evidence was excluded', () => {
    render(
      <EvidencePanel
        sources={SOURCES}
        onToggle={() => {}}
        excludedNote="1 passage from rev. 3 was excluded."
      />,
    );
    expect(screen.getByText('Superseded')).toBeInTheDocument();
    expect(
      screen.getByText('1 passage from rev. 3 was excluded.'),
    ).toBeInTheDocument();
  });
});

describe('AbstentionCard', () => {
  it('says what was searched and why it fell short', () => {
    render(
      <AbstentionCard
        abstention={ABSTENTION}
        headingLevel={3}
        actions={<button type="button">Widen scope</button>}
      />,
    );
    expect(screen.getByText('Abstained')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        level: 3,
        name: 'Not enough evidence to answer',
      }),
    ).toBeVisible();
    expect(screen.getByText('Policies · Standards · Minutes')).toBeVisible();
    expect(screen.getByText('214')).toBeVisible();
    expect(screen.getByText('· answer threshold 0.55')).toBeVisible();
    expect(screen.getByRole('button', {name: 'Widen scope'})).toBeVisible();
  });

  it('uses a second-level heading by default', () => {
    render(<AbstentionCard abstention={ABSTENTION} />);
    expect(screen.getByRole('heading', {level: 2})).toBeVisible();
  });
});
