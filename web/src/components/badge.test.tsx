import {render, screen} from '@testing-library/react';

import type {LifecycleStatus} from '../types';
import {AnswerBadge, StatusBadge} from './badge';

describe('StatusBadge', () => {
  it.each<[LifecycleStatus, string]>([
    ['candidate', 'Candidate'],
    ['validated', 'Validated'],
    ['approved', 'Approved'],
    ['rejected', 'Rejected'],
    ['superseded', 'Superseded'],
  ])('labels %s with text and an icon, never color alone', (status, label) => {
    const {container} = render(<StatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(container.querySelector('svg')).toHaveAttribute(
      'aria-hidden',
      'true',
    );
  });

  it('dashes the candidate border', () => {
    const {container} = render(<StatusBadge status="candidate" />);
    expect(container.firstChild).toHaveClass('border-dashed');
  });

  it('strikes the superseded label', () => {
    render(<StatusBadge status="superseded" />);
    expect(screen.getByText('Superseded')).toHaveClass('line-through');
  });
});

describe('AnswerBadge', () => {
  it('adds the claim counts to a grounded answer', () => {
    render(<AnswerBadge support="grounded" cited={3} total={3} />);
    expect(
      screen.getByText('Grounded · 3 of 3 claims cited'),
    ).toBeInTheDocument();
  });

  it('shows the bare label without counts', () => {
    render(<AnswerBadge support="partial" />);
    expect(screen.getByText('Partly supported')).toBeInTheDocument();
  });

  it('never adds counts to an abstention', () => {
    render(<AnswerBadge support="abstained" cited={0} total={2} />);
    expect(screen.getByText('Abstained')).toBeInTheDocument();
  });
});
