import {render, screen} from '@testing-library/react';

import {DOCUMENTS} from '../fixtures/sample-data';
import {DocumentTable} from './document-table';

describe('DocumentTable', () => {
  it('lists each revision with its status and links the title', () => {
    render(
      <DocumentTable
        rows={DOCUMENTS}
        selectedRow={1}
        hrefFor={r => `#/${r.id}`}
      />,
    );
    expect(screen.getAllByRole('row')).toHaveLength(DOCUMENTS.length + 1);
    expect(
      screen.getByRole('link', {name: 'Vendor Management Standard'}),
    ).toHaveAttribute('href', '#/doc:vms');
    expect(screen.getByText('Superseded')).toBeInTheDocument();
    expect(screen.getAllByRole('row')[2]).toHaveClass('bg-action-subtle');
  });
});
