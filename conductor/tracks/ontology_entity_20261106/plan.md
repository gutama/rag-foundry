# Implementation Plan: Ontology Registry, Entity Identity & Semantic Assertion Governance

## Phase 1: Ontology Domain Models & Versioned Registry [checkpoint: 20b2692]

- [x] Task: Define ontology domain models (4d1e13f)
  - [x] Write tests: validation of `OntologyClass`, `OntologyProperty`,
        `PropertyConstraint` and `OntologyRelease` (IRI format, status values,
        a data property must have a datatype range)
  - [x] Implement the Pydantic models in `ontology/models.py`
- [x] Task: Add the ontology persistence schema (508b245)
  - [x] Write tests: ORM round trip of releases, classes and properties on
        aiosqlite
  - [x] Implement the ORM tables and the Alembic migration
- [x] Task: Implement the `OntologyRegistry` service (20b2692)
  - [x] Write tests: create a draft, add terms, publish, approved releases are
        immutable, new draft from an approved release, deprecate a term, look up
        by IRI, subclass closure
  - [x] Implement `ontology/registry.py`
- [x] Task: Conductor - User Manual Verification 'Phase 1' (Protocol in workflow.md)

## Phase 2: Ontology Interchange & Constraint Validation [checkpoint: fe70ebe]

- [x] Task: JSON-LD import and export (712afb9)
  - [x] Write tests: round trip of IRIs, labels, domain/range, inverses and
        constraints; unsupported OWL or SHACL terms raise errors
  - [x] Implement in `ontology/serialization.py`
- [x] Task: Turtle export (a5eedf0)
  - [x] Write tests: deterministic output, prefixes, comparison against a
        golden file
  - [x] Implement
- [x] Task: Constraint validator (2770d36)
  - [x] Write tests: domain/range with subclass inference, cardinality,
        datatype, allowed values; any other constraint kind raises
        `UnsupportedConstraintError`
  - [x] Implement `ontology/constraints.py`
- [x] Task: Document the supported constraint subset in
      `docs/semantics/ontology-constraints.md` (db35eca)
- [x] Task: Conductor - User Manual Verification 'Phase 2' (Protocol in workflow.md)

## Phase 3: Entity Identity, Resolution, Merge & Split [checkpoint: cec90bd]

- [x] Task: Entity and mention models and schema (e73c222)
  - [x] Write tests: typed identifiers are unique per scheme, aliases are
        stored, status values are enforced
  - [x] Implement the models, ORM tables and migration
- [x] Task: Mention normalization and candidate generation (3cc87d3)
  - [x] Write tests: Unicode, whitespace and case normalization; an identifier
        match outranks a label match; alias matches; similarity ranking;
        ontology class filter
  - [x] Implement `entities/resolution.py`
- [x] Task: Resolution policy and decisions (41d8793)
  - [x] Write tests: the default policy never auto-approves; an explicit policy
        auto-approves above its threshold; candidates store the score breakdown
        and policy version; results are deterministic
  - [x] Implement
- [x] Task: Merge and split with lineage (6816e12)
  - [x] Write tests: merge adds a redirect and moves aliases and identifiers
        while keeping history; split creates successors; redirect chains
        resolve; merging an entity into itself or into an already-merged entity
        is rejected
  - [x] Implement `entities/lineage.py`
- [x] Task: Conductor - User Manual Verification 'Phase 3' (Protocol in workflow.md)

## Phase 4: Semantic Assertions & Validation Pipeline

- [x] Task: Assertion model, schema and lifecycle state machine (4bfaf4d)
  - [x] Write tests: allowed and invalid transitions, append-only transition
        log, origin class is required
  - [x] Implement `assertions/models.py` and `assertions/lifecycle.py`
- [x] Task: Assertion validation pipeline (576cd61)
  - [x] Write tests:
    - missing evidence, or evidence from another workspace, makes the assertion
      `invalid`;
    - a domain/range violation makes it `invalid`;
    - cardinality is enforced;
    - a merged entity is followed through its redirect;
    - a split entity makes the assertion `invalid`, with the reason recorded;
    - confidence below the policy minimum is caught;
    - the stored report pins the ontology release used.
  - [x] Implement `assertions/validation.py`
- [x] Task: Protect curated assertions from extracted ones (9eeb75b)
  - [x] Write tests: an extracted assertion cannot supersede a curated one;
        re-extracting a triple adds evidence without changing its status
  - [x] Implement
- [~] Task: Handle the effect of entity changes on assertions
  - [ ] Write tests: approved assertions that reference a split entity are
        flagged for re-review; assertions that reference a merged entity are
        re-pointed on revalidation
  - [ ] Implement
- [ ] Task: Conductor - User Manual Verification 'Phase 4' (Protocol in workflow.md)

## Phase 5: Curator Review Queue, Audit & Semantic Metrics

- [ ] Task: Review queue service
  - [ ] Write tests:
    - items are enqueued when a candidate is created and when an assertion is
      validated;
    - items can be filtered by kind, workspace and status;
    - approve and reject record actor, time, reason and profile;
    - approval is refused when validation failed or evidence is missing;
    - approving the same item twice has no extra effect.
  - [ ] Implement `stewardship/review_queue.py`
- [ ] Task: Audit trail and explainability
  - [ ] Write tests: an `AuditEvent` is written for each merge, split, decision
        and transition; `explain_entity_link` returns the full path
  - [ ] Implement
- [ ] Task: Ontology and entity metrics
  - [ ] Write tests: compute each of the five metrics on a fixture dataset
  - [ ] Implement `stewardship/metrics.py`
- [ ] Task: Conductor - User Manual Verification 'Phase 5' (Protocol in workflow.md)
