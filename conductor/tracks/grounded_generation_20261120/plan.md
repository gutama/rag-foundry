# Implementation Plan: Phase 6 — Grounded Generation & Citations

## Phase 1: Model Gateway, Approved Profiles & Local/Air-Gapped Chat Adapters (`ADR-0006`) [checkpoint: ec1e71e]

- [x] Task: Build `ModelProfile` domain models, `ModelProfileRepository` protocol, and `InMemoryModelProfileRegistry` 0b7c334
  - [x] Write failing unit tests in `tests/test_model_gateway_profiles.py` covering `ModelProfile` validation (task, provider, status `draft|approved|deprecated`, `deployment_policy` `local_only|approved_remote`, inference settings), `ModelProfileRepository` protocol conformance, versioned profile registration/lookup, and rejection of duplicate `(profile_id, version)` pairs
  - [x] Implement `src/rag_foundry/model_gateway/__init__.py`, `src/rag_foundry/model_gateway/models.py`, and `src/rag_foundry/model_gateway/registry.py`
  - [x] Refactor and verify >80% module coverage
- [x] Task: Implement stdlib HTTP chat adapters and deterministic mock adapter aacf166
  - [x] Write failing unit tests in `tests/test_model_gateway_adapters.py` covering `ChatModelAdapter` protocol, `OllamaChatAdapter` (`/api/chat` payload, JSON mode, timeout/HTTP/JSON error handling), `OpenAICompatibleChatAdapter` (`/v1/chat/completions` payload, bearer auth, response parsing), and `MockDeterministicChatAdapter` (deterministic structured JSON output and custom responder hooks)
  - [x] Implement `src/rag_foundry/model_gateway/adapters.py` using stdlib `urllib.request` with injectable transport (zero mandatory heavy LLM SDKs)
  - [x] Refactor and verify >80% module coverage
- [x] Task: Build fail-closed `ModelGateway` with policy enforcement and non-blocking async execution ec1e71e
  - [x] Write failing tests in `tests/test_model_gateway.py` verifying fail-closed rejection of unknown, `draft`, `deprecated`, or task-mismatched profiles, enforcement of `local_only` host boundary (rejecting non-local URLs and forbidding hidden remote fallbacks), rejection of caller-supplied ad-hoc endpoints/API keys, reproducibility trace metadata on `ChatGenerationResponse`, and non-blocking `asyncio.to_thread` execution during slow HTTP calls
  - [x] Implement `src/rag_foundry/model_gateway/gateway.py` and wire exports in `src/rag_foundry/model_gateway/__init__.py`
  - [x] Refactor and verify >80% module coverage
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md) ec1e71e

## Phase 2: Structured Answer Schema, Curated-vs-Extracted Evidence Formatter & Prompt Policies (`ADR-0013`) [checkpoint: d465b0d]

- [x] Task: Build structured answer models and strict JSON response parser 0f06ab5
  - [x] Write failing unit tests in `tests/test_generation_models.py` covering `KnowledgeAuthority` (`curated`, `extracted`, `document_evidence`), `EvidenceEntry`, `AnswerClaim`, `GroundedAnswer`, strict parsing of raw and fenced JSON model outputs, deterministic field defaults, and fail-closed `AnswerParseError` on malformed or schema-invalid outputs
  - [x] Implement `src/rag_foundry/generation/__init__.py`, `src/rag_foundry/generation/models.py`, and `src/rag_foundry/generation/parser.py`
  - [x] Refactor and verify >80% module coverage
- [x] Task: Implement `EvidenceFormatter` with curated-vs-extracted labeling and prompt policies 6ae62c9
  - [x] Write failing unit tests in `tests/test_evidence_formatter.py` covering deterministic handle assignment (`E1..En`, `A1..An`), explicit `[CURATED / APPROVED]` vs. `[EXTRACTED / CANDIDATE — UNVERIFIED]` vs. `[DOCUMENT EVIDENCE]` context blocks, deterministic ordering, character budget truncation, and mode-specific prompt policies (`standard`, `curated_knowledge`, `decomposed`)
  - [x] Implement `src/rag_foundry/generation/formatter.py` and `src/rag_foundry/generation/prompts.py`
  - [x] Refactor and verify >80% module coverage
- [x] Task: Implement authorized `AssertionContextLoader` bridging Phase 4 assertions and Phase 5 evidence d465b0d
  - [x] Write failing tests in `tests/test_assertion_context_loader.py` covering loading workspace/profile-scoped `AssertionRecord` rows with entity preferred labels and `source_chunk_ids`, strict `SecurityContext` authorization before disclosure, fail-closed empty `allowed_security_domains`, deterministic classification into `curated` vs. `extracted` `EvidenceEntry` objects, and exclusion of `rejected`/`superseded` assertions
  - [x] Implement `src/rag_foundry/generation/context.py`
  - [x] Refactor and verify >80% module coverage
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md) d465b0d

## Phase 3: Post-Generation Citation Alignment, Validation & Sufficiency/Abstention Gate (`ADR-0020`) [checkpoint: 7e9dbad]

- [x] Task: Build `CitationValidationPolicy`, report models, and `CitationAligner` e6839db
  - [x] Write failing unit tests in `tests/test_citation_aligner.py` covering `CitationValidationPolicy` validation, claim-to-passage lexical/phrase/key-token support scoring, source span resolution (`document_version_id`, `page_numbers`, `bounding_boxes`, `section_path`), effective claim `KnowledgeAuthority` derivation (`curated`, `extracted`, `document_evidence`, `mixed`), and detection of unsupported synthetic claims
  - [x] Implement `src/rag_foundry/citations/__init__.py`, `src/rag_foundry/citations/models.py`, and `src/rag_foundry/citations/aligner.py`
  - [x] Refactor and verify >80% module coverage
- [x] Task: Implement fail-closed `CitationValidator` 18bfafd
  - [x] Write failing unit tests in `tests/test_citation_validator.py` verifying rejection of fabricated/unknown citation IDs, rejection of citations unauthorized under caller `SecurityContext` (workspace or security domain), rejection of superseded `document_version_id` revisions, rejection of unresolvable source spans, and detection of curated-vs-extracted misrepresentation (claiming curated certainty from candidate-only extracted evidence)
  - [x] Implement `src/rag_foundry/citations/validator.py`
  - [x] Refactor and verify >80% module coverage
- [x] Task: Implement `SufficiencyGate` for warnings, claim stripping, and explicit abstention 7e9dbad
  - [x] Write failing unit tests in `tests/test_sufficiency_gate.py` covering retrieval-level abstention propagation, invalid-citation abstention, insufficient supported-claim ratio triggers, `unsupported_claim_action` modes (`abstain`, `strip_and_warn`, `warn`), `allow_extracted_only_answers=False` enforcement, and visible curated-vs-extracted disclosure in `limitations`
  - [x] Implement `src/rag_foundry/citations/sufficiency.py` and export public symbols in `src/rag_foundry/citations/__init__.py`
  - [x] Refactor and verify >80% module coverage
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md) 7e9dbad

## Phase 4: Grounded QA Orchestrator (`standard`, `curated_knowledge`, `decomposed`) & End-to-End Exit-Criteria Suite [checkpoint: 153c64f]

- [x] Task: Implement `GroundedQAPipeline` for `standard` and `curated_knowledge` QA modes d010476
  - [x] Write failing tests in `tests/test_grounded_qa_pipeline.py` covering end-to-end execution across `RetrievalPipeline` -> `AssertionContextLoader` -> `EvidenceFormatter` -> `ModelGateway` -> `CitationAligner` -> `CitationValidator` -> `SufficiencyGate`, verifying `standard` mode grounding, `curated_knowledge` prioritization and candidate segregation, malformed LLM output abstention, and `semantic_profile_id` / `model_profile_id` trace recording
  - [x] Implement `src/rag_foundry/generation/pipeline.py` and wire exports in `src/rag_foundry/generation/__init__.py`
  - [x] Refactor and verify >80% module coverage
- [x] Task: Implement `QueryDecomposer` and `decomposed` multi-step QA mode 6ea7fe7
  - [x] Write failing tests in `tests/test_decomposed_qa.py` covering complex question decomposition (LLM-assisted via `ModelGateway` + deterministic fallback splitter), `max_sub_questions` bounds, per-sub-question authorized retrieval and grounded sub-answering, deduplicated evidence handle merging, final synthesized `GroundedAnswer` re-validation, and sub-question provenance traces in `execution_metrics`
  - [x] Implement `src/rag_foundry/generation/decomposer.py` and integrate `decomposed` mode into `src/rag_foundry/generation/pipeline.py`
  - [x] Refactor and verify >80% module coverage
- [x] Task: End-to-end Phase 6 exit-criteria integration & regression suite 153c64f
  - [x] Write failing integration tests in `tests/test_phase6_end_to_end.py` validating all Phase 6 exit criteria end-to-end (`IngestionPipeline` -> `IndexerService` -> `RetrievalPipeline` + `AssertionRecord`s -> `GroundedQAPipeline` across `standard`, `curated_knowledge`, and `decomposed` modes): (1) every supported claim links to supplied authorized evidence, (2) invalid/unauthorized/superseded citation IDs are rejected, (3) low-evidence questions trigger explicit warning or abstention, (4) curated and extracted knowledge are visibly distinguished, and (5) unapproved model profiles fail closed
  - [x] Resolve any integration gaps and verify the full `pytest` suite and >80% coverage gates pass across all new modules
- [x] Task: Phase Verification & Checkpoint (Refer to workflow.md) 153c64f
