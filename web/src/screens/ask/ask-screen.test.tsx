import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {GROUNDED_ANSWER, SOURCES} from '../../fixtures/sample-data';
import {AskScreen} from './ask-screen';

function renderAsk(props: Partial<Parameters<typeof AskScreen>[0]> = {}) {
  return render(
    <AskScreen
      answer={GROUNDED_ANSWER}
      sources={SOURCES}
      scope={['Policies', 'Standards']}
      followUps={['Which record classes are in Schedule B?']}
      deployment="compact · air-gapped"
      pendingReviews={4}
      {...props}
    />,
  );
}

function viewer() {
  return screen.getByRole('complementary', {name: 'Document viewer'});
}

describe('AskScreen', () => {
  it('shows the question, the scope and the first source', () => {
    renderAsk();
    expect(
      screen.getByRole('heading', {
        level: 1,
        name: 'How long do we keep vendor contract records?',
      }),
    ).toBeVisible();
    expect(screen.getByText('Standards')).toBeVisible();
    expect(
      within(viewer()).getByText('Records Retention Policy'),
    ).toBeVisible();
    expect(within(viewer()).getByText('12 / 18')).toBeVisible();
  });

  it('marks Ask as the current page and shows pending reviews', () => {
    renderAsk();
    const nav = screen.getByRole('navigation', {name: 'Main'});
    expect(within(nav).getByRole('link', {name: 'Ask'})).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(
      within(nav).getByRole('link', {name: /Stewardship/}),
    ).toHaveTextContent('4');
    expect(within(nav).getByText('compact · air-gapped')).toBeVisible();
  });

  it('opens the source of the marker the reader selects', async () => {
    renderAsk();
    await userEvent.click(screen.getByRole('button', {name: 'Source 2'}));
    expect(within(viewer()).getByText('Records Schedule B')).toBeVisible();
    expect(within(viewer()).getByText('2 / 6')).toBeVisible();
    expect(
      screen.getByRole('button', {name: 'Source 2, open'}),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  it('highlights the cited passage on the page', () => {
    renderAsk();
    const cited = within(viewer()).getByText(/^3\.2 Vendor contract records/);
    expect(cited).toHaveClass('bg-evidence-highlight');
    expect(cited.closest('[data-theme]')).toHaveAttribute(
      'data-theme',
      'light',
    );
  });

  it('disables page turns until the viewer can page', () => {
    renderAsk();
    expect(
      within(viewer()).getByRole('button', {name: 'Next page'}),
    ).toBeDisabled();
  });

  it('copies the answer with bracketed citations', async () => {
    const user = userEvent.setup();
    renderAsk();
    await user.click(screen.getByRole('button', {name: 'Copy with citations'}));
    expect(await navigator.clipboard.readText()).toContain(
      'Records Retention Policy [1].',
    );
    expect(screen.getByRole('button', {name: 'Copied'})).toBeVisible();
  });

  it('asks follow-ups and typed questions', async () => {
    const onAsk = vi.fn();
    renderAsk({onAsk});
    await userEvent.click(
      screen.getByRole('button', {
        name: 'Which record classes are in Schedule B?',
      }),
    );
    expect(onAsk).toHaveBeenLastCalledWith(
      'Which record classes are in Schedule B?',
    );
    await userEvent.type(
      screen.getByRole('textbox', {name: 'Ask a question'}),
      'Does a legal hold change this?{Enter}',
    );
    expect(onAsk).toHaveBeenLastCalledWith('Does a legal hold change this?');
  });
});
