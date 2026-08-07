# ADR-0014: Semantic assertion validation and approval

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Candidate semantic assertions need a consistent path from extraction to trusted
use. A single boolean `validated` flag cannot distinguish machine checks, human
review, rejection, or later supersession.

## Decision

Use an explicit assertion lifecycle: `candidate` -> `validated` -> `approved`,
with terminal/transition states for `rejected` and `superseded`.

Validation checks evidence resolvability, ontology/taxonomy constraints, entity
identity, security compatibility, and configured confidence/policy rules.
Approval is a governed action by an authorized steward/reviewer and records actor,
time, reason, and semantic profile. Rejection and supersession retain the prior
record for audit.

Graph publication consumes only assertion statuses permitted by the publication
policy and never upgrades status on its own.

## Consequences

Semantic trust becomes explainable and reviewable. More lifecycle states increase
workflow complexity and require careful idempotency in background jobs.

## Verification

- No approved assertion lacks resolvable evidence and a complete approval audit
  record.
- Constraint failure prevents approval.
- Status transitions are append-audited and invalid transitions are rejected.
