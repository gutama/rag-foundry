# Specification: Ontology Registry, Entity Identity & Semantic Assertion Governance

## Overview

This track implements roadmap Phase 4 (`docs/architecture/ARCHITECTURE.md`
§8.5–8.9, §21) and ADRs 0011–0014. It adds:

- a versioned ontology registry with JSON-LD and Turtle interchange and a
  documented constraint subset;
- entity identity with auditable resolution, merge and split;
- candidate semantic assertions with an explicit lifecycle;
- a curator review queue.

Knowledge extracted by a model or rule stays a candidate until a steward
approves it.

## Requirements

### Functional Requirements

- **FR1 Ontology registry.** An ontology release is versioned and contains
  classes and properties.
  - Classes have an IRI, multilingual labels, parent classes and identity rules.
  - Properties are object or data properties with domain, range, inverse,
    `temporal` and `provenance_required`.
  - Releases move through `draft → approved → deprecated`. An approved release
    is immutable, so any edit creates a new draft release.
- **FR2 Constraints.** The supported subset is:
  - cardinality (min/max) per property;
  - datatype for data properties: `xsd:string`, `xsd:integer`, `xsd:decimal`,
    `xsd:boolean`, `xsd:date`, `xsd:dateTime`;
  - allowed values;
  - domain and range, including transitive `rdfs:subClassOf` inference.

  Any other constraint kind raises `UnsupportedConstraintError`, both on import
  and during validation.
- **FR3 Import/export.** JSON-LD import and export use OWL, RDFS and SHACL
  vocabulary. Turtle export is deterministic. IRIs and constraints survive a
  round trip unchanged.
- **FR4 Entities.** Each entity has:
  - a stable UUID and a canonical IRI;
  - an ontology class;
  - multilingual labels and aliases;
  - typed authoritative identifiers (scheme → value, unique per scheme);
  - a status: `active`, `merged`, `split` or `deprecated`;
  - a workspace and a semantic profile.
- **FR5 Mentions.** A mention records its surface text, source chunk, character
  span and normalized form. Its resolution status is `unresolved`, `candidate`
  or `resolved`.
- **FR6 Resolution.** The pipeline is: normalize → generate candidates
  (identifier match, then exact label or alias match, then `difflib`
  similarity) → filter by ontology class → score → apply policy.
  - Each candidate keeps its score breakdown, method, policy version and
    evidence.
  - Auto-approval happens only when the active policy explicitly enables it and
    the score meets the threshold. The default policy sends every candidate to
    review.
- **FR7 Merge and split.**
  - Merge marks the losing entity `merged`, adds a redirect to the surviving
    entity, and moves aliases and identifiers to it.
  - Split creates successor entities and records lineage.
  - Lineage is never deleted.
- **FR8 Assertions.** An assertion has:
  - a subject entity, a property IRI, and either an object entity or a literal;
  - source chunk IDs;
  - extraction method, model and prompt version;
  - confidence;
  - origin: `curated` or `extracted`;
  - a validity interval;
  - the ontology release it was validated against.
- **FR9 Lifecycle.** Allowed transitions are `candidate → validated | invalid`,
  `validated → approved | rejected` and `approved → superseded`.
  - Every transition is appended to a log with actor, time and reason.
  - Any other transition raises `InvalidTransitionError`.
- **FR10 Validation** checks that:
  - evidence chunks exist and share the assertion's workspace;
  - subject and object entities are active, or are merged and resolve through
    their redirect;
  - domain, range, cardinality, datatype and allowed values hold against the
    pinned ontology release;
  - confidence meets the policy minimum.

  Validation stores a report of what it checked and found.
- **FR11 Curated protection.** An extracted assertion can never replace,
  overwrite or upgrade a curated or approved one. Extracting the same triple
  again adds evidence but never raises its status.
- **FR12 Review queue.** Queue items cover resolution candidates and validated
  assertions.
  - Items can be listed and filtered by kind, workspace and status.
  - Approving or rejecting records actor, reason and semantic profile.
  - Approval is refused when the latest validation failed or evidence is
    missing.
- **FR13 Audit and explain.** Every merge, split, resolution decision and
  assertion transition writes an `AuditEvent`. `explain_entity_link(mention_id)`
  returns the candidate, its scores, the policy and the approval path.
- **FR14 Metrics (§19.3).** The track reports duplicate entity rate, unresolved
  mention rate, assertion provenance coverage, ontology constraint pass rate and
  invalid assertion rejection rate.

### Non-Functional Requirements

- **NFR1** No new runtime dependencies: only the standard library plus the
  existing Pydantic and SQLAlchemy.
- **NFR2** Services use async SQLAlchemy and are tested on in-memory aiosqlite,
  like the existing modules. Schema changes go through PostgreSQL-compatible
  Alembic migrations.
- **NFR3** New modules have more than 80% test coverage, docstrings and type
  hints, and follow `conductor/code_styleguides/python.md`.
- **NFR4** Resolution and validation give the same result for the same inputs
  and policy version.

## User Stories

- As an ontology owner, I want to publish an immutable ontology release so that
  assertions are validated against a fixed set of rules.
- As a steward, I want to see why a resolution candidate was proposed so that I
  can approve or reject it with confidence.
- As a steward, I want to merge duplicates and split false merges without
  losing history.
- As an analyst, I want extracted facts kept separate from curated facts so
  that I know which are authoritative.
- As an operator, I want duplicate and unresolved rates so that I can track
  semantic quality.

## Acceptance Criteria

- [ ] Duplicate entities can be measured, and none are merged automatically
      unless a policy explicitly allows it.
- [ ] An assertion without resolvable evidence cannot reach `validated` or
      `approved`.
- [ ] Validation rejects relationships that violate an ontology property's
      domain or range.
- [ ] Merges and splits are audited, and their lineage is never erased.
- [ ] Ontology IRIs are identical after a JSON-LD and Turtle round trip.
- [ ] Constraint features outside the supported subset fail explicitly.
- [ ] Invalid status transitions are rejected, and every transition is in the
      append-only log.
- [ ] Re-extraction cannot replace a curated assertion.
- [ ] Every resolved link can explain its candidate and approval path.

## Technical Approach

Four new packages under `src/rag_foundry/`:

| Package | Contents |
|---|---|
| `ontology/` | `models.py`, `registry.py`, `serialization.py`, `constraints.py` |
| `entities/` | `models.py`, `resolution.py`, `lineage.py` |
| `assertions/` | `models.py`, `lifecycle.py`, `validation.py` |
| `stewardship/` | `review_queue.py`, `metrics.py` |

- ORM tables go in `src/rag_foundry/db/models.py`, with Alembic migrations. The
  existing `AuditEvent` table is reused for audit records.
- The supported constraint subset is documented in
  `docs/semantics/ontology-constraints.md`.
- Assertion statuses follow ADR-0014, plus `invalid` from §8.7 so that a failed
  machine validation is distinct from a steward's rejection. §8.7's
  `needs_review` is represented by an open review-queue item rather than a
  status.
- The package layout follows the existing flat `src/rag_foundry/<area>/`
  structure (as taxonomy and retrieval do) rather than the `packages/` tree in
  ARCHITECTURE.md §20.

## Out of Scope

- FastAPI endpoints and a review UI (roadmap Phase 7).
- Entity and relation extraction by an LLM. In this track, assertions are
  created through the service API.
- Embedding similarity in resolution, and the taxonomy-alignment step of the
  §8.7 pipeline.
- Ontology query expansion, graph publication and LightRAG (roadmap Phases
  9–10).
- Full OWL reasoning, SHACL beyond the subset above, rdflib and pySHACL.
- A semantic profile registry. `semantic_profile_id` is stored as a plain UUID.
- The existing `TaxonomyService.resolve_candidate_entities`, which stays
  unchanged.
