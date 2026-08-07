# ADR-0011: Ontology representation, constraints, and versioning

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Taxonomies express controlled vocabulary and hierarchy but cannot by themselves
capture typed entities, relations, domain/range semantics, or validation rules.
RAG Foundry needs richer semantics without making a graph database or reasoner a
mandatory transactional dependency.

## Decision

Use RDF-compatible stable IRIs for ontology terms, OWL-compatible vocabulary for
class/property semantics where needed, and SHACL-compatible shapes for validation
constraints. The canonical registry is provider-neutral and stored transactionally
in PostgreSQL; JSON-LD/Turtle-style interchange can be provided by adapters.

Ontology releases are immutable versioned artifacts. A semantic profile pins one
approved ontology release plus its taxonomy/mapping dependencies. Constraint
validation happens before semantic assertions become publishable.

A general-purpose triple store or full OWL reasoner is not required for the
compact profile; such capabilities may be added behind interfaces.

## Consequences

The model aligns with established semantic-web standards without forcing a heavy
runtime. The supported reasoning/constraint subset must be documented and tested
to avoid implying semantics the runtime does not implement.

## Verification

- Ontology terms keep stable identifiers across serialization formats.
- Published assertions are validated against the pinned constraint version.
- Unsupported reasoning features fail explicitly rather than being ignored.
