import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {useState} from 'react';

import {FacetChip, ScopeChip, SegmentedControl, Tabs} from './facets';

describe('FacetChip', () => {
  it('reports its pressed state and count', async () => {
    const onToggle = vi.fn();
    render(
      <FacetChip label="Policy" count={128} selected onToggle={onToggle} />,
    );
    const chip = screen.getByRole('button', {name: /Policy/});
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    expect(chip).toHaveTextContent('128');
    await userEvent.click(chip);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it('shows a check only when selected', () => {
    const {container} = render(
      <FacetChip label="Contract" selected={false} onToggle={() => {}} />,
    );
    expect(container.querySelector('svg')).not.toBeInTheDocument();
  });
});

describe('ScopeChip', () => {
  it('is a label, not a control', () => {
    render(<ScopeChip label="Policies" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText('Policies')).toBeInTheDocument();
  });
});

function ControlledTabs() {
  const [selected, setSelected] = useState('answer');
  return (
    <Tabs
      label="Result views"
      tabs={[
        {id: 'answer', label: 'Answer'},
        {id: 'sources', label: 'Sources', count: 3},
        {id: 'trace', label: 'Trace'},
      ]}
      selected={selected}
      onSelect={setSelected}
    />
  );
}

describe('Tabs', () => {
  it('selects a tab on click', async () => {
    render(<ControlledTabs />);
    await userEvent.click(screen.getByRole('tab', {name: /Sources/}));
    expect(screen.getByRole('tab', {name: /Sources/})).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('moves with the arrow keys and wraps around', async () => {
    render(<ControlledTabs />);
    await userEvent.click(screen.getByRole('tab', {name: 'Answer'}));
    await userEvent.keyboard('{ArrowLeft}');
    const trace = screen.getByRole('tab', {name: 'Trace'});
    expect(trace).toHaveAttribute('aria-selected', 'true');
    expect(trace).toHaveFocus();
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', {name: 'Answer'})).toHaveFocus();
  });

  it('keeps only the selected tab in the tab order', () => {
    render(<ControlledTabs />);
    expect(screen.getByRole('tab', {name: 'Answer'})).toHaveAttribute(
      'tabindex',
      '0',
    );
    expect(screen.getByRole('tab', {name: 'Trace'})).toHaveAttribute(
      'tabindex',
      '-1',
    );
  });
});

describe('SegmentedControl', () => {
  it('presses the current option and reports changes', async () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl
        label="Retrieval mode"
        options={[
          {value: 'hybrid', label: 'Hybrid'},
          {value: 'graph', label: 'Graph'},
        ]}
        value="hybrid"
        onChange={onChange}
      />,
    );
    expect(screen.getByRole('group', {name: 'Retrieval mode'})).toBeVisible();
    expect(screen.getByRole('button', {name: 'Hybrid'})).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await userEvent.click(screen.getByRole('button', {name: 'Graph'}));
    expect(onChange).toHaveBeenCalledWith('graph');
  });
});
