import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {
  AUDIT_EVENTS,
  CHANGE_SET,
  CONCEPT,
  ENTITY_MATCH,
} from '../fixtures/sample-data';
import {
  AuditTrail,
  ChangeSetReview,
  ConceptCard,
  EntityResolution,
  LifecycleDiagram,
} from './governance';

describe('LifecycleDiagram', () => {
  it('shows every lifecycle state with its transition', () => {
    render(<LifecycleDiagram />);
    for (const label of [
      'Candidate',
      'Validated',
      'Approved',
      'Superseded',
      'Rejected',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getAllByRole('listitem')).toHaveLength(4);
  });
});

describe('ChangeSetReview', () => {
  it('shows who proposed what and what will publish', () => {
    render(<ChangeSetReview changeSet={CHANGE_SET} />);
    expect(
      screen.getByRole('heading', {
        name: 'Add Indonesian labels to Records retention concepts',
      }),
    ).toBeVisible();
    expect(screen.getByText('change-set CS-0142 · taxonomy')).toBeVisible();
    expect(screen.getByText('records-taxonomy v13')).toBeVisible();
  });

  it('marks each diff line for assistive tech', () => {
    render(<ChangeSetReview changeSet={CHANGE_SET} />);
    expect(screen.getAllByText('added', {exact: false})).toHaveLength(2);
    expect(screen.getByText('rf:records').tagName).toBe('DEL');
    expect(screen.getByText('“supplier file”').tagName).toBe('DEL');
  });

  it('lists the checks with their outcome', () => {
    render(<ChangeSetReview changeSet={CHANGE_SET} />);
    const checks = within(screen.getByRole('list')).getAllByRole('listitem');
    expect(checks).toHaveLength(3);
    expect(
      within(checks[2]).getByRole('link', {name: 'Preview'}),
    ).toBeVisible();
  });

  it('routes the three decisions to their handlers', async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const onRequestChanges = vi.fn();
    render(
      <ChangeSetReview
        changeSet={CHANGE_SET}
        onApprove={onApprove}
        onReject={onReject}
        onRequestChanges={onRequestChanges}
      />,
    );
    await userEvent.click(screen.getByRole('button', {name: 'Reject'}));
    await userEvent.click(
      screen.getByRole('button', {name: 'Request changes'}),
    );
    await userEvent.click(
      screen.getByRole('button', {name: 'Approve and publish v13'}),
    );
    expect(onReject).toHaveBeenCalledOnce();
    expect(onRequestChanges).toHaveBeenCalledOnce();
    expect(onApprove).toHaveBeenCalledOnce();
  });

  it('stops the proposer approving their own change set', () => {
    render(<ChangeSetReview changeSet={CHANGE_SET} canApprove={false} />);
    expect(
      screen.getByRole('button', {name: 'Approve and publish v13'}),
    ).toBeDisabled();
  });

  it('marks a failed check', () => {
    render(
      <ChangeSetReview
        changeSet={{
          ...CHANGE_SET,
          checks: [{result: 'fail', text: '2 SHACL violations'}],
        }}
      />,
    );
    expect(screen.getByText('2 SHACL violations')).toBeVisible();
  });
});

describe('ConceptCard', () => {
  it('shows labels by language and links broader and narrower concepts', () => {
    render(<ConceptCard concept={CONCEPT} />);
    expect(
      screen.getByRole('heading', {name: 'Vendor contract records'}),
    ).toBeVisible();
    expect(screen.getByText('Arsip kontrak vendor')).toBeVisible();
    expect(
      screen.getByText('Arsip kontrak vendor').closest('[lang]'),
    ).toHaveAttribute('lang', 'id');
    expect(screen.getByRole('link', {name: 'Contract records'})).toBeVisible();
    expect(screen.getByRole('link', {name: 'Purchase orders'})).toBeVisible();
    expect(screen.getByText('records·v12')).toBeVisible();
  });
});

describe('AuditTrail', () => {
  it('lists each transition with who, when and the reference', () => {
    render(<AuditTrail events={AUDIT_EVENTS} />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent('Validated by validation job');
    expect(items[0]).toHaveTextContent('2026-10-01 14:22 UTC · job:val-88f2');
  });
});

describe('EntityResolution', () => {
  it('shows both records, the match evidence and the decisions', () => {
    render(
      <EntityResolution
        {...ENTITY_MATCH}
        actions={<button type="button">Merge into org-2291</button>}
      />,
    );
    expect(screen.getByText('Meridian Cargo Ltd.')).toBeVisible();
    expect(screen.getByText('Meridian Cargo Limited')).toBeVisible();
    expect(screen.getByText('Same organization?')).toBeVisible();
    expect(screen.getByText('Different security domain')).toBeVisible();
    expect(
      screen.getByRole('button', {name: 'Merge into org-2291'}),
    ).toBeVisible();
  });
});
