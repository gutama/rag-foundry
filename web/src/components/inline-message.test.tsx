import {render, screen} from '@testing-library/react';

import {InlineMessage} from './inline-message';

describe('InlineMessage', () => {
  it('shows the title and its one line', () => {
    render(
      <InlineMessage tone="danger" title="Publication blocked">
        2 SHACL violations in this change set.
      </InlineMessage>,
    );
    expect(screen.getByText('Publication blocked')).toBeInTheDocument();
    expect(
      screen.getByText('2 SHACL violations in this change set.'),
    ).toBeInTheDocument();
  });
});
