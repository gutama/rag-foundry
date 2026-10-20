import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {AskBar, SelectField, TextField} from './fields';

describe('TextField', () => {
  it('labels the input', () => {
    render(<TextField label="Effective date" defaultValue="" />);
    expect(screen.getByLabelText('Effective date')).toBeInTheDocument();
  });

  it('marks the input invalid and describes it with the error', () => {
    render(
      <TextField
        label="Effective date"
        defaultValue="07/08/2026"
        error="Use an ISO 8601 date: YYYY-MM-DD."
        hint="Not shown while there is an error."
        meta="policy-document v3 · effective_date"
      />,
    );
    const input = screen.getByLabelText('Effective date');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAccessibleDescription(
      'Use an ISO 8601 date: YYYY-MM-DD.',
    );
    expect(
      screen.queryByText('Not shown while there is an error.'),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText('policy-document v3 · effective_date'),
    ).toBeInTheDocument();
  });

  it('keeps a given id', () => {
    render(<TextField id="effective" label="Effective date" />);
    expect(screen.getByLabelText('Effective date')).toHaveAttribute(
      'id',
      'effective',
    );
  });
});

describe('SelectField', () => {
  it('lists the options and describes the select with the hint', () => {
    render(
      <SelectField
        label="Semantic profile"
        options={['records · v12', 'records · v11']}
        hint="Taxonomy and ontology used to expand the query."
      />,
    );
    const select = screen.getByLabelText('Semantic profile');
    expect(select).toHaveAccessibleDescription(
      'Taxonomy and ontology used to expand the query.',
    );
    expect(screen.getAllByRole('option')).toHaveLength(2);
    expect(select).not.toHaveAttribute('aria-invalid');
  });

  it('describes the select with an error', () => {
    render(
      <SelectField
        label="Semantic profile"
        options={['records · v12']}
        error="Pick a published profile."
      />,
    );
    expect(
      screen.getByLabelText('Semantic profile'),
    ).toHaveAccessibleDescription('Pick a published profile.');
  });
});

describe('AskBar', () => {
  it('submits the trimmed question and clears the box', async () => {
    const onAsk = vi.fn();
    render(<AskBar onAsk={onAsk} />);
    const input = screen.getByRole('textbox', {name: 'Ask a question'});
    await userEvent.type(input, '  How long do we keep records?  {Enter}');
    expect(onAsk).toHaveBeenCalledWith('How long do we keep records?');
    expect(input).toHaveValue('');
  });

  it('ignores an empty question', async () => {
    const onAsk = vi.fn();
    render(<AskBar onAsk={onAsk} />);
    await userEvent.type(
      screen.getByRole('textbox', {name: 'Ask a question'}),
      '   ',
    );
    await userEvent.click(screen.getByRole('button', {name: 'Ask'}));
    expect(onAsk).not.toHaveBeenCalled();
  });

  it('is a search landmark with an optional scope button', async () => {
    const onScope = vi.fn();
    render(
      <AskBar
        onAsk={() => {}}
        scopeLabel="Scope · 3 collections"
        onScope={onScope}
      />,
    );
    expect(screen.getByRole('search')).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', {name: 'Scope · 3 collections'}),
    );
    expect(onScope).toHaveBeenCalledOnce();
  });
});
