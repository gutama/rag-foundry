# ADR-0016: Taxonomy and ontology query expansion

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Institutional queries often use synonyms, abbreviations, broader concepts, or
domain relations that do not appear verbatim in documents. Unbounded semantic
expansion, however, can lower precision and leak restricted vocabulary.

## Decision

Perform semantic query expansion only from the approved taxonomy/ontology
versions pinned by the active semantic profile and only after the caller is
authorized to see the relevant semantic resources.

Expansion rules are explicit and bounded: approved alternate labels and mappings
may expand terms directly; hierarchy/relation traversal has configured relation
types, depth, weights, and candidate budgets. Every expansion records the concept
or relation that caused it so retrieval traces can explain the result.

Unapproved extracted assertions do not automatically become query-expansion
rules.

## Consequences

Domain vocabulary can improve recall while keeping behavior auditable. Expansion
profiles need evaluation because the best depth and relations vary by corpus.

## Verification

- Expansion never crosses an unauthorized semantic/security scope.
- Traces identify original versus expanded terms and their semantic source.
- Golden datasets include terminology/alias cases and precision-regression gates.
