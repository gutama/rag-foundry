# Specification: Phase 6 — Grounded Generation & Citations

## 1. Overview
Implement the governed generation, model gateway, citation validation, and QA orchestration layer for RAG Foundry (Phase 6 of `docs/architecture/ARCHITECTURE.md`), adhering to `ADR-0006` (Model Gateway & Approved Profiles), `ADR-0013` (Curated vs. Extracted Knowledge), and `ADR-0020` (Citation Validation & Abstention).

All generation passes through approved, versioned model profiles, enforces authorization before context assembly or citation resolution, visibly distinguishes curated vs. extracted knowledge, and validates every claim and citation post-generation with explicit abstention when evidence is insufficient.

## 2. Package Architecture
Following `docs/architecture/ARCHITECTURE.md`:
- `src/rag_foundry/model_gateway/` — `ModelProfile` domain models, `ModelProfileRepository` protocol, `InMemoryModelProfileRegistry`, `ChatModelAdapter` protocol, stdlib HTTP adapters (`OllamaChatAdapter`, `OpenAICompatibleChatAdapter`), `MockDeterministicChatAdapter`, and fail-closed `ModelGateway`.
- `src/rag_foundry/generation/` — Structured output contracts (`AnswerClaim`, `GroundedAnswer`, `EvidenceEntry`, `KnowledgeAuthority`), curated-vs-extracted `EvidenceFormatter`, prompt policies, strict structured JSON response parser, authorized `AssertionContextLoader`, `QueryDecomposer`, and `GroundedQAPipeline` supporting `standard`, `curated_knowledge`, and `decomposed` QA modes.
- `src/rag_foundry/citations/` — `CitationValidationPolicy`, `CitationValidationReport`, `CitationAligner`, `CitationValidator`, and `SufficiencyGate`.

## 3. Functional Requirements

### FR-1: Model Gateway & Approved Profiles (`ADR-0006`)
1. **Versioned `ModelProfile` Schema:** Captures `profile_id`, `version`, `task` (e.g. `"chat_generation"`, `"query_decomposition"`), `provider` (`"ollama"`, `"openai_compatible"`, `"mock"`), `model_name`, `model_revision`, `data_handling_class`, `deployment_policy` (`"local_only"` or `"approved_remote"`), `base_url`, `inference_settings` (temperature, max tokens, timeout, JSON mode), and `status` (`"draft"`, `"approved"`, `"deprecated"`).
2. **Profile Registry Protocol:** Define a runtime-checkable `ModelProfileRepository` protocol and an `InMemoryModelProfileRegistry` (config-loadable, ready to be backed by PostgreSQL in Phase 7).
3. **Fail-Closed Enforcement:** `ModelGateway` MUST:
   - Reject missing, `draft`, `deprecated`, or task-mismatched profiles with typed authorization/policy errors.
   - Enforce local-only network boundaries (`local_only` profiles reject non-local hosts or remote providers; never fall back silently to a remote provider).
   - Prevent callers from supplying arbitrary endpoints or API keys at request time.
4. **Local/Air-Gapped Chat Adapters:** Implement `OllamaChatAdapter` (`/api/chat`) and `OpenAICompatibleChatAdapter` (`/v1/chat/completions`, e.g., vLLM) using Python's stdlib `urllib.request` with injectable transport (for offline unit tests) and `asyncio.to_thread` offload, plus `MockDeterministicChatAdapter` for reproducible testing.
5. **Reproducibility Traces:** Every `ChatGenerationResponse` records `profile_id`, `profile_version`, `provider`, `model_name`, `model_revision`, token usage (when provided), and `duration_ms`.

### FR-2: Curated-vs-Extracted Knowledge Labeling & Evidence Formatting (`ADR-0013`)
1. **Authority Classification:** Every piece of context fed to the model is tagged with an explicit `KnowledgeAuthority`:
   - `curated` — Steward-created or steward-approved assertions (`origin == "curated"` or `status == "approved"`).
   - `extracted` — Automated candidate assertions (`origin == "extracted"` and `status != "approved"`).
   - `document_evidence` — Authorized retrieved document chunks from `RetrievalPipeline`.
2. **Stable Citation Handles (`EvidenceEntry`):** Assigns deterministic handles (`E1`, `E2`, ... for document chunks; `A1`, `A2`, ... for semantic assertions) carrying full provenance (`chunk_id` / `assertion_id`, `document_version_id`, `workspace_id`, `security_domain`, `section_path`, `page_numbers`, `bounding_boxes`, `authority`, `assertion_status`, `confidence_score`).
3. **Prompt & Context Formatting:** `EvidenceFormatter` renders clear authority banners distinguishing `[CURATED / APPROVED]` vs. `[EXTRACTED / CANDIDATE — UNVERIFIED]` vs. `[DOCUMENT EVIDENCE]` and enforces prompt instructions prohibiting citation of unprovided IDs or misrepresentation of candidate extractions as authoritative truth.

### FR-3: Structured Answer Contract (`ARCHITECTURE.md §15.2`)
1. **`AnswerClaim`:** Structured claim carrying `text`, `evidence_ids`, `concept_uris`, `entity_ids`, `authority` (`"curated"` | `"extracted"` | `"document_evidence"` | `"mixed"`), `support_score`, and `verified`.
2. **`GroundedAnswer`:** Structured response carrying `answer`, `claims`, `citations` (resolved `EvidenceEntry` list), `limitations`, `sufficient_evidence`, `abstained`, `abstention_reason`, `qa_mode`, `semantic_profile_id`, `model_profile_id`, `model_profile_version`, `validation_report`, and `execution_metrics` (including sub-question traces for decomposed mode).
3. **Strict Parsing:** Parses JSON / fenced-JSON model outputs against Pydantic contracts and fails closed (or triggers abstention per policy) on malformed output.

### FR-4: Citation Alignment, Validation & Sufficiency/Abstention (`ADR-0020`)
1. **`CitationValidationPolicy`:** Configurable policy governing strictness (`reject_invalid_citation_ids=True`, `require_claim_citations=True`, `min_claim_support_score`, `min_supported_claim_ratio`, `min_evidence_confidence`, `allow_extracted_only_answers`, `unsupported_claim_action` in `{"abstain", "strip_and_warn", "warn"}`, `enforce_revision_check=True`).
2. **`CitationValidator` & `CitationAligner`:**
   - **Existence check:** Rejects any citation ID not present in the supplied `EvidenceEntry` map.
   - **Authorization check:** Re-verifies every cited evidence item against caller `SecurityContext` (`allowed_workspaces`, `allowed_security_domains`).
   - **Document revision & span check:** Verifies cited `document_version_id` against active/allowed revisions (when supplied) and confirms valid source span metadata (chunk/page provenance).
   - **Claim-passage support alignment:** Computes deterministic lexical/phrase/key-token alignment between each claim and its cited evidence passages; flags or rejects unsupported claims.
   - **Curated-vs-extracted integrity:** Computes effective claim authority from cited evidence and rejects/flags attempts to present `extracted`-only candidate evidence as `curated` truth.
3. **`SufficiencyGate`:** Evaluates retrieval abstention, invalid citations, supported claim ratio, evidence confidence, and authority policy to either pass with explicit `limitations` warnings or return an explicit abstained `GroundedAnswer` (`abstained=True`, `sufficient_evidence=False`, clear `abstention_reason`).

### FR-5: QA Orchestration & Three QA Modes (`ARCHITECTURE.md §15`)
1. **`standard` mode:** Executes authorized hybrid retrieval via `RetrievalPipeline`, formats authorized document chunks (plus optional approved assertions), generates a structured answer via `ModelGateway`, and runs full citation alignment, validation, and sufficiency gating.
2. **`curated_knowledge` mode:** Queries authorized workspace/profile `AssertionRecord`s alongside document evidence, prioritizes `curated`/`approved` assertions, visibly isolates or excludes unapproved `extracted` candidates according to policy, and notes explicit limitations whenever only extracted candidates or no curated facts exist.
3. **`decomposed` mode:** Splits complex multi-part questions into bounded sub-questions (configurable `max_sub_questions`, via `ModelGateway` with deterministic fallback), runs authorized retrieval and grounded sub-answer generation per sub-question, merges and deduplicates authorized evidence handles, synthesizes a unified `GroundedAnswer`, re-validates all final claims and citations, and records per-sub-question provenance in `execution_metrics`.

## 4. Non-Functional Requirements
- **Air-Gapped & Lightweight:** Zero mandatory heavy LLM/ML SDKs added to `pyproject.toml`; HTTP adapters use stdlib `urllib.request` with `asyncio.to_thread` offload so the asyncio event loop is never blocked.
- **Authorization Before Generation (`ADR-0005`):** Unauthorized workspace or security-domain chunks/assertions never enter prompt context or citations; empty `allowed_security_domains` fails closed with explicit abstention.
- **Reproducibility & Style:** Deterministic ordering and IDs, full type hints, Google-style docstrings, max 80-character lines, and >80% test coverage on every new module.

## 5. Acceptance Criteria (Phase 6 Exit Criteria)
1. Every supported claim in a non-abstained `GroundedAnswer` links to verified, supplied, authorized evidence with resolved source provenance.
2. Invalid, fabricated, unauthorized, or superseded citation identifiers are deterministically rejected by `CitationValidator`.
3. Low-evidence, ungrounded, or conflicting questions trigger explicit warnings (`limitations`) or full abstention (`abstained=True`, `sufficient_evidence=False`) rather than fabricating support.
4. Curated and extracted knowledge are visibly distinguished in formatted context, claim authority metadata, and final output; candidate assertions cannot silently present as curated institutional truth.
5. Unapproved model profiles and disallowed remote endpoints fail closed in `ModelGateway`.
6. End-to-end integration tests verify all three QA modes (`standard`, `curated_knowledge`, `decomposed`) wired to Phase 5 `RetrievalPipeline` and Phase 4 `AssertionRecord` storage.

## 6. Out of Scope
- SKOS taxonomy and ontology terminology consistency checks (explicitly deferred to Phase 8).
- PostgreSQL ORM table and Alembic migration for `ModelProfile` persistence (protocol-backed in-memory/config registry in Phase 6; database/admin profile management in Phase 7).
- FastAPI HTTP endpoints, SSE token streaming, PDF citation viewer, and React UI (Phase 7).
- Langfuse/OpenTelemetry observability integration and Ragas/DeepEval evaluation harness (Phase 8).
