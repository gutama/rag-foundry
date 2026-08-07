# ADR-0025: Third-party code and license policy

- **Status:** Proposed
- **Date:** 2026-08-07

## Context

RAG Foundry intentionally learns from and integrates with projects such as RAG
Blueprint, Kotaemon, LightRAG, and nano-GraphRAG. Architectural inspiration,
runtime dependency, vendored code, and copied implementation have different
maintenance and licensing consequences.

## Decision

Adopt third-party functionality deliberately through reviewed dependencies and
provider adapters; do not copy or vendor implementation merely because a project
inspired the architecture.

Every production dependency must have a recorded source/version, license review,
security/maintenance assessment, and compatibility with the intended distribution
and deployment model. Pin deployable versions and produce an SBOM for releases.
Vendoring or modifying third-party source requires explicit attribution/license
handling and a documented reason. Experimental dependencies—including
nano-GraphRAG when used for conformance research—must not become production
requirements accidentally.

Provider boundaries are preferred where they reduce license, upgrade, or failure
coupling.

## Consequences

Integration may require more adapter code, but the project retains clear
provenance, upgrade paths, and distribution hygiene.

## Verification

- CI/release checks can inventory production dependencies and licenses.
- No copied third-party source enters the repository without provenance review.
- Experimental dependencies are excluded from the default production install.
