import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {Button, IconButton} from './button';

describe('Button', () => {
  it('is a plain button, not a submit, by default', () => {
    render(<Button>Export</Button>);
    expect(screen.getByRole('button', {name: 'Export'})).toHaveAttribute(
      'type',
      'button',
    );
  });

  it('calls onClick', async () => {
    const onClick = vi.fn();
    render(
      <Button variant="primary" onClick={onClick}>
        Publish
      </Button>,
    );
    await userEvent.click(screen.getByRole('button', {name: 'Publish'}));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('blocks presses and shows a spinner while busy', async () => {
    const onClick = vi.fn();
    const {container} = render(
      <Button variant="primary" busy onClick={onClick}>
        Searching
      </Button>,
    );
    const button = screen.getByRole('button', {name: 'Searching'});
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(container.querySelector('svg')).toBeInTheDocument();
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('renders a trailing icon after the label', () => {
    render(<Button trailingIcon={<svg data-testid="icon" />}>Ask</Button>);
    const button = screen.getByRole('button', {name: 'Ask'});
    expect(button.lastChild).toBe(screen.getByTestId('icon'));
  });
});

describe('IconButton', () => {
  it('takes its accessible name from the label', () => {
    render(
      <IconButton label="Search">
        <svg />
      </IconButton>,
    );
    expect(screen.getByRole('button', {name: 'Search'})).toBeInTheDocument();
  });
});
