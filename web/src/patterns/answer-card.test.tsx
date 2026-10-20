import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {useState} from 'react';

import {Button} from '../components/button';
import {GROUNDED_ANSWER, PARTIAL_ANSWER} from '../fixtures/sample-data';
import {AnswerCard} from './answer-card';

function Controlled({
  initial = 1,
  onSelect = () => {},
}: {
  initial?: number;
  onSelect?: (index: number) => void;
}) {
  const [open, setOpen] = useState<number | undefined>(initial);
  return (
    <>
      <AnswerCard
        answer={GROUNDED_ANSWER}
        openSource={open}
        onSelectSource={index => {
          setOpen(index);
          onSelect(index);
        }}
      />
      <button type="button" onClick={() => setOpen(3)}>
        Open source 3 elsewhere
      </button>
    </>
  );
}

function markers() {
  return screen.getAllByRole('button', {name: /^Source \d/});
}

describe('AnswerCard', () => {
  it('shows how many claims are cited', () => {
    render(<AnswerCard answer={GROUNDED_ANSWER} />);
    expect(
      screen.getByText('Grounded · 3 of 3 claims cited'),
    ).toBeInTheDocument();
  });

  it('places one marker after each cited clause', () => {
    render(<Controlled />);
    expect(markers().map(m => m.textContent)).toEqual(['1', '1', '2', '3']);
  });

  it('inverts the first marker of the open source', () => {
    render(<Controlled />);
    const [first, second] = markers();
    expect(first).toHaveAccessibleName('Source 1, open');
    expect(second).toHaveAccessibleName('Source 1');
  });

  it('inverts the marker the reader chose and reports the source', async () => {
    const onSelect = vi.fn();
    render(<Controlled onSelect={onSelect} />);
    await userEvent.click(markers()[1]);
    const [first, second] = markers();
    expect(first).toHaveAttribute('aria-pressed', 'false');
    expect(second).toHaveAttribute('aria-pressed', 'true');
    expect(onSelect).toHaveBeenCalledWith(1);

    await userEvent.click(markers()[2]);
    expect(onSelect).toHaveBeenLastCalledWith(2);
    expect(markers()[2]).toHaveAccessibleName('Source 2, open');
  });

  it('follows a source opened elsewhere', async () => {
    render(<Controlled />);
    await userEvent.click(
      screen.getByRole('button', {name: 'Open source 3 elsewhere'}),
    );
    expect(markers()[3]).toHaveAccessibleName('Source 3, open');
    expect(markers()[0]).toHaveAccessibleName('Source 1');
  });

  it('shows static markers when sources cannot be opened', () => {
    render(<AnswerCard answer={GROUNDED_ANSWER} />);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });

  it('marks unsupported text and shows the notice', () => {
    render(
      <AnswerCard
        answer={PARTIAL_ANSWER}
        notice={<p>Treat the marked sentence as unverified.</p>}
      />,
    );
    expect(
      screen.getByText('Partly supported · 1 of 2 claims cited'),
    ).toBeInTheDocument();
    expect(screen.getByText('unsupported')).toBeInTheDocument();
    expect(
      screen.getByText('Scanned copies may replace the originals after that.'),
    ).toHaveClass('decoration-dashed');
    expect(
      screen.getByText('Treat the marked sentence as unverified.'),
    ).toBeInTheDocument();
  });

  it('puts the taxonomy and actions in the footer', () => {
    render(
      <AnswerCard
        answer={GROUNDED_ANSWER}
        showProfile
        actions={<Button variant="text">View trace</Button>}
      />,
    );
    expect(screen.getByText('profile records·v12')).toBeInTheDocument();
    const footer = screen.getByText(/Terms checked against/);
    expect(within(footer).getByText('records-taxonomy v12')).toBeVisible();
    expect(screen.getByRole('button', {name: 'View trace'})).toBeVisible();
  });
});
