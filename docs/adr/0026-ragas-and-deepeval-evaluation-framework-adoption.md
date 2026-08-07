# ADR-0026: Ragas and DeepEval evaluation framework adoption

- **Status:** Accepted
- **Date:** 2026-08-08

## Context

RAG Foundry defines eight evaluation metric categories (§19 of ARCHITECTURE.md)
spanning metadata, taxonomy, ontology, retrieval, generation, graph, OKF, and
operational dimensions. The tech stack currently lists Langfuse, OpenTelemetry,
and a custom golden dataset evaluator.

Retrieval and generation metrics—faithfulness, context precision, answer
relevancy, Recall@k, and unsupported-claim rate—are well-studied problems with
mature open-source implementations. Building these from scratch duplicates
existing research and delays the evaluation milestone. Meanwhile, release gates
(§19.9) require pytest-compatible assertions that block deployments when quality
regresses.

Domain-specific metrics—authorization leakage, taxonomy-expansion uplift,
ontology constraint pass rate, graph provenance coverage, OKF round-trip
fidelity, and curated-versus-extracted labeling accuracy—have no off-the-shelf
implementation and require custom evaluators.

## Decision

Adopt Ragas as the metric computation engine for retrieval and generation
evaluation, and DeepEval as the pytest-native assertion framework for CI/CD
release gates. Both complement the existing Langfuse and OpenTelemetry stack
rather than replacing it.

Ragas computes reference-free and reference-based RAG metrics (faithfulness,
context precision, context recall, answer relevancy) and generates synthetic
evaluation datasets from ingested documents to solve the cold-start problem.
Results feed into Langfuse for longitudinal tracking.

DeepEval provides `assert_test()` calls inside pytest suites that enforce
threshold-based quality gates. Release gate criteria from §19.9—citation
precision regressions, unsupported-claim thresholds, critical golden-case
failures—translate directly to DeepEval assertions.

Domain-specific metrics remain in the custom golden dataset evaluator.
Authorization leakage, graph provenance, OKF fidelity, taxonomy, ontology, and
entity-resolution metrics cannot be delegated to general-purpose RAG evaluation
frameworks.

Neither framework may own or replace the Langfuse trace pipeline. Ragas and
DeepEval consume trace data and golden datasets; they do not collect production
traces independently.

## Consequences

Retrieval and generation evaluation reaches production quality faster because
mature, research-backed metrics are adopted rather than reimplemented. CI/CD
gates gain pytest-native LLM assertions with diagnostic reasoning on failure.
Two additional dependencies are introduced, both Apache-2.0 licensed and
compatible with ADR-0025 third-party policy. The custom evaluator scope narrows
to domain-specific metrics, reducing its implementation surface.

Ragas metric computation requires LLM calls for judge-based metrics, adding
evaluation cost. DeepEval's Confident AI cloud platform must not be used in
air-gapped deployments; only the local open-source library is permitted.

## Verification

- Ragas metrics are computed during golden dataset evaluation and results are
  stored in Langfuse.
- DeepEval assertions run in CI and block releases when thresholds are violated.
- Neither framework introduces external network calls in air-gapped profiles.
- Domain-specific metrics (authorization, taxonomy, ontology, graph, OKF) remain
  in the custom evaluator, not delegated to Ragas or DeepEval.
- Both dependencies are listed with license review per ADR-0025.
