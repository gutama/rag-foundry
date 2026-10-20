import {render, screen} from '@testing-library/react';

import {ChannelTags, RetrievalSignalRow, ScoreBar, SignalTag} from './signals';

describe('ChannelTags', () => {
  it('tags each channel that returned the passage', () => {
    render(
      <ChannelTags signals={{lexicalRank: 2, denseRank: 1, rerank: 0.9}} />,
    );
    expect(screen.getByText('LEX 2')).toBeInTheDocument();
    expect(screen.getByText('DENSE 1')).toBeInTheDocument();
    expect(screen.queryByText('GRAPH')).not.toBeInTheDocument();
  });

  it('dashes a graph hit, since the provider is optional', () => {
    render(<ChannelTags signals={{graph: true, rerank: 0.6}} />);
    expect(screen.getByText('GRAPH')).toHaveClass('border-dashed');
  });
});

describe('SignalTag', () => {
  it('fills the score that decided the order', () => {
    render(<SignalTag label="RERANK 0.91" emphasis="score" />);
    expect(screen.getByText('RERANK 0.91')).toHaveClass('bg-action-subtle');
  });
});

describe('ScoreBar', () => {
  it('exposes the score as a meter', () => {
    render(<ScoreBar score={0.84} label="Rerank score" />);
    expect(screen.getByRole('meter', {name: 'Rerank score'})).toHaveAttribute(
      'aria-valuenow',
      '0.84',
    );
    expect(screen.getByText('0.84')).toBeInTheDocument();
  });
});

describe('RetrievalSignalRow', () => {
  it('shows rank, title, channels and the rerank score', () => {
    render(
      <RetrievalSignalRow
        rank={1}
        title="Records Retention Policy"
        signals={{lexicalRank: 2, denseRank: 1, rerank: 0.91}}
      />,
    );
    expect(
      screen.getByRole('meter', {
        name: 'Rerank score for Records Retention Policy',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('LEX 2')).toBeInTheDocument();
  });
});
