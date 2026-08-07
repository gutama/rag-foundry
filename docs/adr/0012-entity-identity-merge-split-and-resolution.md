# ADR-0012: Entity identity, merge, split, and resolution strategy

- **Status:** Proposed
- **Date:** 2026-08-07

## Context

Entity extraction yields aliases, duplicates, ambiguous names, and occasional
false merges. Treating a model-generated name as identity would contaminate
graphs and make corrections difficult to propagate.

## Decision

Assign entities stable internal identities and treat resolution as an auditable,
reversible governance process.

Resolution produces candidates using names, registered identifiers, context, and
semantic constraints. Candidate matches retain scores, method/profile versions,
and evidence. Approval establishes canonical links. Merges preserve redirect and
provenance history; splits create explicit successor identities and require
dependent assertions/indexes to be republished. External identifiers are typed
attributes, not interchangeable primary keys.

Automated resolution may auto-approve only under an explicitly governed policy;
otherwise it remains candidate knowledge.

## Consequences

Corrections remain traceable and graph identity can improve over time. Entity
operations are more complex than simple upserts and require downstream impact
tracking.

## Verification

- Merge and split history is never erased.
- Every resolved link can explain the source candidate and approval path.
- Replaying a correction cannot leave published graph edges pointing to an
  invalid identity silently.
