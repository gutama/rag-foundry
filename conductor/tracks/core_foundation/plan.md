# Implementation Plan: Core Framework & Knowledge Governance Foundation

## Phase 1: Environment & Project Structure Setup
- [x] Task: Initialize Python project dependencies & environment (pytest, asyncpg, sqlalchemy, alembic, pydantic) (bc5b6be)
  - [x] Write failing test to verify environment importability and config loading
  - [x] Configure dependency management (`pyproject.toml` / `requirements.txt`)
  - [x] Implement configuration module (`config.py`) using Pydantic Settings
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 2: Database Schema & Migration Foundation
- [x] Task: Set up Async SQLAlchemy 2.0 models and Alembic migrations (75e0d06)
  - [x] Write failing tests for Database engine connection and session context manager
  - [x] Write failing tests for core ORM models (Document, Chunk, MetadataSchema, TaxonomyConcept, AuditEvent)
  - [x] Implement SQLAlchemy ORM models and set up Alembic migration environment
  - [x] Run baseline Alembic migration
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 3: Knowledge Governance Plane (MetadataRegistry)
- [ ] Task: Implement Pydantic v2 Metadata Registry & Validation Service
  - [ ] Write failing unit tests for `MetadataRegistry` schema registration and versioning
  - [ ] Write failing unit tests for field-level metadata validation against versioned schemas
  - [ ] Implement `MetadataRegistry` service with Pydantic v2 JSON Schema support
  - [ ] Verify unit test suite passes with >80% coverage
- [ ] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase 4: SKOS Taxonomy & Identity Resolution Baseline
- [ ] Task: Implement SKOS Concept Scheme and Taxonomy Service
  - [ ] Write failing tests for TaxonomyConcept CRUD operations and label lookups (prefLabel, altLabel)
  - [ ] Write failing tests for broader/narrower concept relationship queries
  - [ ] Implement `TaxonomyService` and basic candidate entity resolution interface
- [ ] Task: Phase Verification & Checkpoint (Refer to workflow.md)

## Phase: Review Fixes
- [x] Task: Apply review suggestions (0c86db6)
