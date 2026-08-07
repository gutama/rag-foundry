# ADR-0010: Taxonomy representation and SKOS interoperability

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Institutional vocabularies need stable concepts, multilingual labels, aliases,
and hierarchical relationships. Encoding those concepts as application-specific
tags would make mappings and interchange brittle.

## Decision

Model taxonomies with SKOS-compatible semantics.

Concept schemes and concepts receive stable identifiers. Concepts support
language-tagged `prefLabel` and `altLabel`, definitions/notes, `broader` and
`narrower` relationships, and explicit mappings where applicable. PostgreSQL is
the canonical transactional registry; import/export adapters preserve SKOS
meaning in portable representations and OKF bundles.

Published taxonomy versions are immutable. Display labels may change between
versions without changing stable concept identity unless governance explicitly
creates a new concept.

## Consequences

The taxonomy can interoperate with standard knowledge-management tools while the
runtime remains lightweight. The service must validate hierarchy integrity,
label rules, and version compatibility.

## Verification

- Multilingual preferred/alternate labels round-trip without losing language.
- Broader/narrower relationships are reciprocal at the service boundary.
- Import/export preserves stable concept identifiers and mappings.
