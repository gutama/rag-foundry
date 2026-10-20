import {act, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {App} from './app';

function go(hash: string) {
  act(() => {
    window.location.hash = hash;
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  });
}

beforeEach(() => {
  window.location.hash = '';
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe('App', () => {
  it('opens on the Ask screen', () => {
    render(<App />);
    expect(
      screen.getByRole('heading', {
        level: 1,
        name: 'How long do we keep vendor contract records?',
      }),
    ).toBeVisible();
  });

  it.each([
    ['#/design', 'Assay'],
    ['#/design/components', 'Components'],
    ['#/design/evidence', 'Evidence'],
    ['#/design/governance', 'Governance'],
    ['#/design/unknown', 'Assay'],
  ])('shows the design-system board at %s', (hash, title) => {
    render(<App />);
    go(hash);
    expect(screen.getByRole('heading', {level: 1, name: title})).toBeVisible();
  });

  it('returns to Ask from the design system', () => {
    render(<App />);
    go('#/design/evidence');
    go('#/ask');
    expect(screen.getByRole('navigation', {name: 'Main'})).toBeVisible();
  });

  it('applies and remembers the chosen theme', async () => {
    render(<App />);
    go('#/design');
    await userEvent.click(screen.getByRole('button', {name: 'Dark'}));
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(localStorage.getItem('rf-theme')).toBe('dark');

    await userEvent.click(screen.getByRole('button', {name: 'System'}));
    expect(document.documentElement).not.toHaveAttribute('data-theme');
    expect(localStorage.getItem('rf-theme')).toBeNull();
  });

  it('restores a remembered theme', () => {
    localStorage.setItem('rf-theme', 'light');
    render(<App />);
    expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  });
});

describe('design-system boards', () => {
  it('lets a marker in the grounded answer open its source in the panel', async () => {
    render(<App />);
    go('#/design/evidence');
    await userEvent.click(screen.getByRole('button', {name: 'Source 3'}));
    expect(
      screen.getByRole('button', {name: /Vendor Management Standard/}),
    ).toHaveAttribute('aria-expanded', 'true');
  });

  it('validates the date field on the components board', async () => {
    render(<App />);
    go('#/design/components');
    const date = screen.getByLabelText('Effective date');
    expect(date).toHaveAttribute('aria-invalid', 'true');
    await userEvent.clear(date);
    await userEvent.type(date, '2026-08-07');
    expect(date).not.toHaveAttribute('aria-invalid');
  });

  it('toggles and clears facets on the components board', async () => {
    render(<App />);
    go('#/design/components');
    const contract = screen.getByRole('button', {name: /Contract/});
    await userEvent.click(contract);
    expect(contract).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', {name: /Policy/}));
    expect(screen.getByRole('button', {name: /Policy/})).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    await userEvent.click(screen.getByRole('button', {name: 'Clear'}));
    expect(contract).toHaveAttribute('aria-pressed', 'false');
  });
});
