# ADR-0022: Stewardship and approval workflow

- **Status:** Proposed
- **Date:** 2026-08-07

## Context

Metadata schemas, taxonomies, ontologies, entity corrections, and semantic
assertions affect retrieval behavior across a workspace. Anonymous or unaudited
edits would make knowledge quality and accountability impossible to manage.

## Decision

Treat governed knowledge changes as explicit change sets with ownership,
stewardship, review, approval, publication, and audit history.

Roles distinguish at minimum platform/workspace authority from knowledge steward
and reviewer responsibilities. High-impact changes can require maker-checker
separation by policy. Review records include actor, time, rationale, validation
results, diff/base version, and resulting publication. Rejection does not erase
the proposed change.

Permissions are scoped to workspace and artifact type; possessing edit rights
does not imply publication rights.

## Consequences

Knowledge changes take more steps than direct CRUD, but releases become auditable
and can be rolled back to known publications.

## Verification

- Publication requires the configured approval policy to be satisfied.
- Audit history can reconstruct who proposed, reviewed, and published a change.
- Concurrent edits detect base-version conflicts rather than silently overwriting.
