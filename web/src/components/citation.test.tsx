import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {SOURCES} from '../fixtures/sample-data';
import {CitationMarker, ExcerptText, SourcePreview} from './citation';

describe('CitationMarker', () => {
  it('is a static label without a handler', () => {
    render(<CitationMarker index={2} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText('2')).not.toHaveClass('cursor-pointer');
  });

  it('opens its source when selected', async () => {
    const onSelect = vi.fn();
    render(<CitationMarker index={2} onSelect={onSelect} />);
    const marker = screen.getByRole('button', {name: 'Source 2'});
    expect(marker).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(marker);
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it('is pressed while its source is open', () => {
    render(<CitationMarker index={1} state="open" onSelect={() => {}} />);
    expect(
      screen.getByRole('button', {name: 'Source 1, open'}),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  it('says when a citation failed validation', () => {
    render(<CitationMarker index={4} state="failed" onSelect={() => {}} />);
    expect(
      screen.getByRole('button', {name: 'Source 4, failed validation'}),
    ).toHaveClass('line-through');
  });
});

describe('ExcerptText', () => {
  it('highlights only the cited span', () => {
    const {container} = render(
      <ExcerptText excerpt={SOURCES[0].excerpt} quoted />,
    );
    expect(container.querySelector('mark')).toHaveTextContent(
      /^Vendor contract records are retained/,
    );
    expect(container.firstChild).toHaveTextContent(/^“3\.2 Vendor/);
  });
});

describe('SourcePreview', () => {
  it('names the source, page and chunk, and links to the page', () => {
    render(<SourcePreview source={SOURCES[0]} href="#/viewer/rrp/12" />);
    expect(screen.getByText('Source 1 · p.12')).toBeInTheDocument();
    expect(screen.getByText('Records Retention Policy')).toBeInTheDocument();
    expect(screen.getByText('chunk:0f3a91')).toBeInTheDocument();
    expect(screen.getByRole('link', {name: 'Open at page 12'})).toHaveAttribute(
      'href',
      '#/viewer/rrp/12',
    );
  });
});
