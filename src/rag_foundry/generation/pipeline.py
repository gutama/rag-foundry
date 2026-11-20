"""End-to-end GroundedQAPipeline orchestrator (ARCHITECTURE.md §15)."""

import time
import uuid
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rag_foundry.citations.models import CitationValidationPolicy
from rag_foundry.citations.sufficiency import SufficiencyGate
from rag_foundry.citations.validator import CitationValidator
from rag_foundry.generation.context import (
    AssertionContextLoader,
    AssertionContextProvider,
    load_chunk_security_domains,
)
from rag_foundry.generation.decomposer import QueryDecomposer
from rag_foundry.generation.formatter import (
    EvidenceFormatter,
    FormattedEvidenceContext,
)
from rag_foundry.generation.models import (
    EvidenceEntry,
    GroundedAnswer,
    QAMode,
)
from rag_foundry.generation.parser import AnswerParseError, parse_model_answer
from rag_foundry.generation.prompts import build_qa_messages
from rag_foundry.model_gateway.gateway import ModelGateway
from rag_foundry.model_gateway.models import ChatGenerationRequest
from rag_foundry.retrieval.models import (
    AbstentionResult,
    RetrievalFilter,
    RetrievalQuery,
    RetrievalResult,
)
from rag_foundry.retrieval.pipeline import RetrievalPipeline
from rag_foundry.retrieval.postgres_filters import SessionOrFactory
from rag_foundry.retrieval.security import (
    SecurityAuthorizationError,
    SecurityContext,
)

ChunkDomainResolver = Callable[
    [uuid.UUID, Sequence[uuid.UUID]],
    Awaitable[Mapping[uuid.UUID, str]],
]


class GroundedQARequest(BaseModel):
    """Typed request contract for GroundedQAPipeline execution."""

    model_config = ConfigDict(frozen=True)

    question: str = Field(
        min_length=1, description="Institutional question to answer."
    )
    workspace_id: uuid.UUID = Field(
        description="Target workspace UUID for strict tenant isolation."
    )
    model_profile_id: str = Field(
        min_length=1, description="Approved server-side ModelProfile ID."
    )
    model_profile_version: Optional[str] = Field(
        default=None, description="Optional pinned ModelProfile version."
    )
    decomposition_profile_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional approved profile ID for query_decomposition task."
        ),
    )
    decomposition_profile_version: Optional[str] = Field(
        default=None,
        description="Optional version for decomposition_profile_id.",
    )
    qa_mode: QAMode = Field(
        default="standard",
        description="QA mode: standard, curated_knowledge, or decomposed.",
    )
    semantic_profile_id: Optional[uuid.UUID] = Field(
        default=None, description="Active semantic profile UUID."
    )
    top_k: int = Field(default=6, ge=1, le=50)
    min_relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    security_domains: Tuple[str, ...] = Field(
        default=(),
        description="Optional security domain subset validated against ACL.",
    )
    document_ids: Optional[Tuple[uuid.UUID, ...]] = Field(default=None)
    metadata_filters: Dict[str, Any] = Field(default_factory=dict)
    include_assertions_in_standard: bool = Field(
        default=False,
        description="Also load authorized assertions during standard mode.",
    )
    include_extracted_candidates: bool = Field(
        default=True,
        description="Include unapproved extracted candidate assertions.",
    )
    max_assertions: int = Field(default=15, ge=0, le=100)
    max_sub_questions: int = Field(default=4, ge=1, le=8)
    enable_lexical: bool = Field(default=True)
    enable_dense: bool = Field(default=True)
    enable_graph: bool = Field(default=False)
    enable_expansion: bool = Field(default=True)
    active_document_version_ids: Optional[Tuple[uuid.UUID, ...]] = Field(
        default=None
    )
    superseded_document_version_ids: Optional[Tuple[uuid.UUID, ...]] = Field(
        default=None
    )
    citation_policy: Optional[CitationValidationPolicy] = Field(default=None)

    @field_validator("question", "model_profile_id")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        """Ensure required text fields are non-empty after trimming."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Required text fields must be non-empty.")
        return cleaned


class GroundedQAPipeline:
    """Orchestrates authorized retrieval, formatting, gateway, and citations."""

    def __init__(
        self,
        *,
        retrieval_pipeline: RetrievalPipeline,
        model_gateway: ModelGateway,
        assertion_loader: Optional[AssertionContextProvider] = None,
        session_or_factory: Optional[SessionOrFactory] = None,
        evidence_formatter: Optional[EvidenceFormatter] = None,
        citation_validator: Optional[CitationValidator] = None,
        sufficiency_gate: Optional[SufficiencyGate] = None,
        default_policy: Optional[CitationValidationPolicy] = None,
        chunk_domain_resolver: Optional[ChunkDomainResolver] = None,
        query_decomposer: Optional[QueryDecomposer] = None,
    ) -> None:
        """Initialize GroundedQAPipeline with modular governed components.

        Args:
            retrieval_pipeline: Phase 5 RetrievalPipeline instance.
            model_gateway: Fail-closed ADR-0006 ModelGateway instance.
            assertion_loader: Optional AssertionContextProvider (defaults to
                AssertionContextLoader when ``session_or_factory`` is given).
            session_or_factory: Optional AsyncSession or async_sessionmaker
                used for assertion loading and chunk security-domain lookups.
            evidence_formatter: Optional EvidenceFormatter instance.
            citation_validator: Optional CitationValidator instance.
            sufficiency_gate: Optional SufficiencyGate instance.
            default_policy: Optional default CitationValidationPolicy.
            chunk_domain_resolver: Optional async callback resolving chunk IDs
                to security domain names.
            query_decomposer: Optional QueryDecomposer for decomposed QA mode.
        """
        self._retrieval = retrieval_pipeline
        self._gateway = model_gateway
        self._session_or_factory = session_or_factory
        if assertion_loader is not None:
            self._assertion_loader: Optional[AssertionContextProvider] = (
                assertion_loader
            )
        elif session_or_factory is not None:
            self._assertion_loader = AssertionContextLoader(session_or_factory)
        else:
            self._assertion_loader = None

        self._formatter = evidence_formatter or EvidenceFormatter()
        self._validator = citation_validator or CitationValidator()
        self._gate = sufficiency_gate or SufficiencyGate()
        self._default_policy = default_policy or CitationValidationPolicy()
        self._chunk_domain_resolver = chunk_domain_resolver
        self._decomposer = query_decomposer or QueryDecomposer(
            model_gateway=model_gateway
        )

    def _validate_caller_authorization(
        self,
        request: GroundedQARequest,
        security_context: SecurityContext,
    ) -> List[str]:
        """Verify workspace & requested domain ACLs before any execution."""
        if not security_context.can_access_workspace(request.workspace_id):
            raise SecurityAuthorizationError(
                f"Unauthorized workspace access: user "
                f"'{security_context.user_id}' cannot access workspace "
                f"'{request.workspace_id}'."
            )

        if request.security_domains:
            for domain in request.security_domains:
                if not security_context.can_access_domain(domain):
                    raise SecurityAuthorizationError(
                        f"Unauthorized security domain: user "
                        f"'{security_context.user_id}' cannot access domain "
                        f"'{domain}'."
                    )
            return list(request.security_domains)

        return list(security_context.allowed_security_domains)

    async def _resolve_chunk_domains(
        self,
        workspace_id: uuid.UUID,
        chunk_ids: Sequence[uuid.UUID],
    ) -> Mapping[uuid.UUID, str]:
        """Resolve per-chunk security domains when DB/resolver is available."""
        if not chunk_ids:
            return {}
        if self._chunk_domain_resolver is not None:
            return await self._chunk_domain_resolver(workspace_id, chunk_ids)
        if self._session_or_factory is not None:
            return await load_chunk_security_domains(
                self._session_or_factory, workspace_id, chunk_ids
            )
        return {}

    async def _gather_authorized_evidence(
        self,
        *,
        question: str,
        request: GroundedQARequest,
        security_context: SecurityContext,
        effective_domains: Sequence[str],
    ) -> Tuple[RetrievalResult, List[EvidenceEntry], List[EvidenceEntry]]:
        """Execute authorized retrieval and optional assertion loading."""
        retrieval_query = RetrievalQuery(
            query_text=question,
            filter=RetrievalFilter(
                workspace_id=request.workspace_id,
                document_ids=(
                    list(request.document_ids)
                    if request.document_ids is not None
                    else None
                ),
                metadata_filters=dict(request.metadata_filters),
                security_domains=list(effective_domains),
            ),
            top_k=request.top_k,
            enable_lexical=request.enable_lexical,
            enable_dense=request.enable_dense,
            enable_graph=request.enable_graph,
            enable_expansion=request.enable_expansion,
            min_relevance_score=request.min_relevance_score,
        )
        retrieval_result = await self._retrieval.execute(
            retrieval_query, security_context=security_context
        )

        chunk_ids = [ch.chunk_id for ch in retrieval_result.ranked_chunks]
        domain_map = await self._resolve_chunk_domains(
            request.workspace_id, chunk_ids
        )
        default_domain = effective_domains[0]
        doc_entries = EvidenceFormatter.build_document_entries(
            ranked_chunks=retrieval_result.ranked_chunks,
            evidence_items=retrieval_result.evidence_items,
            security_domain_map=domain_map,
            default_security_domain=default_domain,
        )

        assertion_entries: List[EvidenceEntry] = []
        should_load_assertions = (
            request.qa_mode == "curated_knowledge"
            or request.include_assertions_in_standard
        )
        if (
            should_load_assertions
            and self._assertion_loader is not None
            and request.max_assertions > 0
        ):
            assertion_entries = await self._assertion_loader.load_assertions(
                workspace_id=request.workspace_id,
                security_context=security_context,
                semantic_profile_id=request.semantic_profile_id,
                query_text=question,
                include_extracted_candidates=(
                    request.include_extracted_candidates
                ),
                limit=request.max_assertions,
            )

        return retrieval_result, doc_entries, assertion_entries

    async def _generate_and_validate(
        self,
        *,
        question: str,
        formatted: FormattedEvidenceContext,
        request: GroundedQARequest,
        security_context: SecurityContext,
        policy: CitationValidationPolicy,
        mode: QAMode,
        extra_metrics: Optional[Dict[str, Any]] = None,
        sub_answers_summary: Optional[str] = None,
    ) -> GroundedAnswer:
        """Invoke ModelGateway, parse strictly, validate, and gate output."""
        messages = build_qa_messages(
            question,
            formatted,
            mode=mode,
            sub_answers_summary=sub_answers_summary,
        )
        chat_resp = await self._gateway.generate(
            ChatGenerationRequest(
                profile_id=request.model_profile_id,
                profile_version=request.model_profile_version,
                task="chat_generation",
                messages=messages,
                json_mode=True,
            )
        )

        metrics: Dict[str, Any] = dict(extra_metrics or {})
        metrics.update(
            {
                "qa_mode": mode,
                "model_provider": chat_resp.provider,
                "model_name": chat_resp.model_name,
                "model_revision": chat_resp.model_revision,
                "generation_duration_ms": chat_resp.duration_ms,
                "token_usage": chat_resp.usage.model_dump(),
                "context_counts": {
                    "curated": formatted.curated_count,
                    "extracted": formatted.extracted_count,
                    "document": formatted.document_count,
                    "truncated": formatted.truncated_count,
                },
            }
        )

        try:
            payload = parse_model_answer(chat_resp.content)
        except AnswerParseError as exc:
            return self._gate.evaluate(
                payload=None,
                report=None,
                evidence_map=formatted.evidence_map,
                policy=policy,
                qa_mode=mode,
                semantic_profile_id=request.semantic_profile_id,
                model_profile_id=chat_resp.profile_id,
                model_profile_version=chat_resp.profile_version,
                execution_metrics=metrics,
                parse_error=str(exc),
            )

        report = self._validator.validate(
            payload=payload,
            evidence_map=formatted.evidence_map,
            security_context=security_context,
            policy=policy,
            active_document_version_ids=request.active_document_version_ids,
            superseded_document_version_ids=(
                request.superseded_document_version_ids
            ),
        )

        return self._gate.evaluate(
            payload=payload,
            report=report,
            evidence_map=formatted.evidence_map,
            policy=policy,
            qa_mode=mode,
            semantic_profile_id=request.semantic_profile_id,
            model_profile_id=chat_resp.profile_id,
            model_profile_version=chat_resp.profile_version,
            execution_metrics=metrics,
        )

    async def answer(
        self,
        request: GroundedQARequest,
        security_context: SecurityContext,
    ) -> GroundedAnswer:
        """Execute end-to-end grounded QA for the requested mode.

        Args:
            request: GroundedQARequest specifying question, mode, and profile.
            security_context: Caller SecurityContext verified before retrieval
                and re-verified during post-generation citation validation.

        Returns:
            Governed GroundedAnswer with verified citations or abstention.

        Raises:
            SecurityAuthorizationError: If workspace or requested domain is
                unauthorized.
            ModelProfileNotFoundError: If requested model profile is unknown.
            ModelProfilePolicyError: If requested model profile is unapproved,
                task-mismatched, or violates network boundaries.
        """
        start = time.perf_counter()
        policy = request.citation_policy or self._default_policy

        # Step 0: Fail-closed authorization and model profile checks up front.
        effective_domains = self._validate_caller_authorization(
            request, security_context
        )
        resolved_profile = self._gateway.resolve_profile(
            request.model_profile_id,
            version=request.model_profile_version,
            task="chat_generation",
        )

        if not effective_domains:
            elapsed_ms = round((time.perf_counter() - start) * 1000.0, 3)
            return self._gate.evaluate(
                payload=None,
                report=None,
                evidence_map={},
                policy=policy,
                retrieval_abstention=AbstentionResult(
                    abstained=True,
                    reason=(
                        "No authorized security domains available for caller."
                    ),
                ),
                qa_mode=request.qa_mode,
                semantic_profile_id=request.semantic_profile_id,
                model_profile_id=resolved_profile.profile_id,
                model_profile_version=resolved_profile.version,
                execution_metrics={"duration_ms": elapsed_ms},
            )

        if request.qa_mode == "decomposed":
            return await self._execute_decomposed(
                request=request,
                security_context=security_context,
                effective_domains=effective_domains,
                policy=policy,
                resolved_profile_id=resolved_profile.profile_id,
                resolved_profile_version=resolved_profile.version,
                start_time=start,
            )

        retrieval_result, doc_entries, assertion_entries = (
            await self._gather_authorized_evidence(
                question=request.question,
                request=request,
                security_context=security_context,
                effective_domains=effective_domains,
            )
        )

        # Propagate retrieval abstention unless curated/assertion context exists
        if retrieval_result.is_abstained and not assertion_entries:
            elapsed_ms = round((time.perf_counter() - start) * 1000.0, 3)
            return self._gate.evaluate(
                payload=None,
                report=None,
                evidence_map={},
                policy=policy,
                retrieval_abstention=retrieval_result.abstention,
                qa_mode=request.qa_mode,
                semantic_profile_id=request.semantic_profile_id,
                model_profile_id=resolved_profile.profile_id,
                model_profile_version=resolved_profile.version,
                execution_metrics={
                    "duration_ms": elapsed_ms,
                    "retrieval_metrics": retrieval_result.execution_metrics,
                },
            )

        formatted = self._formatter.format(
            document_entries=doc_entries,
            assertion_entries=assertion_entries,
            mode=request.qa_mode,
            include_extracted_candidates=request.include_extracted_candidates,
        )
        if not formatted.entries:
            elapsed_ms = round((time.perf_counter() - start) * 1000.0, 3)
            return self._gate.evaluate(
                payload=None,
                report=None,
                evidence_map={},
                policy=policy,
                retrieval_abstention=AbstentionResult(
                    abstained=True,
                    reason="No authorized evidence remained after formatting.",
                ),
                qa_mode=request.qa_mode,
                semantic_profile_id=request.semantic_profile_id,
                model_profile_id=resolved_profile.profile_id,
                model_profile_version=resolved_profile.version,
                execution_metrics={"duration_ms": elapsed_ms},
            )

        result = await self._generate_and_validate(
            question=request.question,
            formatted=formatted,
            request=request,
            security_context=security_context,
            policy=policy,
            mode=request.qa_mode,
            extra_metrics={
                "retrieval_metrics": retrieval_result.execution_metrics,
            },
        )
        total_ms = round((time.perf_counter() - start) * 1000.0, 3)
        merged_metrics = dict(result.execution_metrics)
        merged_metrics["duration_ms"] = total_ms
        return result.model_copy(update={"execution_metrics": merged_metrics})

    @staticmethod
    def _deduplicate_entries(
        entries: Sequence[EvidenceEntry],
    ) -> List[EvidenceEntry]:
        """Deduplicate evidence entries preserving deterministic order."""
        by_key: Dict[Tuple[str, str], EvidenceEntry] = {}
        order: List[Tuple[str, str]] = []
        for entry in entries:
            if entry.assertion_id is not None:
                key = ("assertion", str(entry.assertion_id))
            elif entry.chunk_id is not None:
                key = ("chunk", str(entry.chunk_id))
            else:
                key = (entry.authority.value, entry.text)
            if key not in by_key:
                by_key[key] = entry
                order.append(key)
            elif entry.confidence_score > by_key[key].confidence_score:
                by_key[key] = entry
        return [by_key[k] for k in order]

    async def _execute_decomposed(
        self,
        *,
        request: GroundedQARequest,
        security_context: SecurityContext,
        effective_domains: Sequence[str],
        policy: CitationValidationPolicy,
        resolved_profile_id: str,
        resolved_profile_version: str,
        start_time: float,
    ) -> GroundedAnswer:
        """Execute multi-step decomposed QA with merged re-validation."""
        decomp = await self._decomposer.decompose(
            request.question,
            max_sub_questions=request.max_sub_questions,
            profile_id=request.decomposition_profile_id,
            profile_version=request.decomposition_profile_version,
        )

        merged_docs: List[EvidenceEntry] = []
        merged_assertions: List[EvidenceEntry] = []
        sub_traces: List[Dict[str, Any]] = []
        summary_lines: List[str] = []

        for idx, sub_q in enumerate(decomp.sub_questions, start=1):
            sub_ret, sub_docs, sub_assertions = (
                await self._gather_authorized_evidence(
                    question=sub_q,
                    request=request,
                    security_context=security_context,
                    effective_domains=effective_domains,
                )
            )
            merged_docs.extend(sub_docs)
            merged_assertions.extend(sub_assertions)

            sub_fmt = self._formatter.format(
                document_entries=sub_docs,
                assertion_entries=sub_assertions,
                mode="standard",
                include_extracted_candidates=(
                    request.include_extracted_candidates
                ),
            )
            if not sub_fmt.entries or (
                sub_ret.is_abstained and not sub_assertions
            ):
                reason = (
                    sub_ret.abstention.reason
                    or "No authorized evidence found for sub-question."
                )
                sub_traces.append(
                    {
                        "sub_question": sub_q,
                        "abstained": True,
                        "sufficient_evidence": False,
                        "answer": "",
                        "claim_count": 0,
                        "evidence_count": len(sub_fmt.entries),
                        "abstention_reason": reason,
                    }
                )
                summary_lines.append(
                    f"{idx}. {sub_q} -> No sufficient authorized evidence."
                )
                continue

            sub_ans = await self._generate_and_validate(
                question=sub_q,
                formatted=sub_fmt,
                request=request,
                security_context=security_context,
                policy=policy,
                mode="standard",
            )
            sub_traces.append(
                {
                    "sub_question": sub_q,
                    "abstained": sub_ans.abstained,
                    "sufficient_evidence": sub_ans.sufficient_evidence,
                    "answer": sub_ans.answer,
                    "claim_count": len(sub_ans.claims),
                    "evidence_count": len(sub_fmt.entries),
                    "abstention_reason": sub_ans.abstention_reason,
                }
            )
            finding = (
                sub_ans.answer
                if not sub_ans.abstained
                else f"Abstained ({sub_ans.abstention_reason})"
            )
            summary_lines.append(f"{idx}. {sub_q} -> {finding}")

        dedup_docs = self._deduplicate_entries(merged_docs)
        dedup_assertions = self._deduplicate_entries(merged_assertions)

        merged_formatted = self._formatter.format(
            document_entries=dedup_docs,
            assertion_entries=dedup_assertions,
            mode="decomposed",
            include_extracted_candidates=request.include_extracted_candidates,
        )
        decomp_metrics: Dict[str, Any] = {
            "method": decomp.method,
            "decomposition_profile_id": decomp.model_profile_id,
            "sub_questions": list(decomp.sub_questions),
            "sub_question_traces": sub_traces,
            "merged_evidence_count": len(merged_formatted.entries),
        }

        if not merged_formatted.entries:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 3)
            return self._gate.evaluate(
                payload=None,
                report=None,
                evidence_map={},
                policy=policy,
                retrieval_abstention=AbstentionResult(
                    abstained=True,
                    reason=(
                        "No authorized evidence was retrieved across any "
                        "decomposed sub-question."
                    ),
                ),
                qa_mode="decomposed",
                semantic_profile_id=request.semantic_profile_id,
                model_profile_id=resolved_profile_id,
                model_profile_version=resolved_profile_version,
                execution_metrics={
                    "duration_ms": elapsed_ms,
                    "decomposition": decomp_metrics,
                },
            )

        synthesized = await self._generate_and_validate(
            question=request.question,
            formatted=merged_formatted,
            request=request,
            security_context=security_context,
            policy=policy,
            mode="decomposed",
            extra_metrics={"decomposition": decomp_metrics},
            sub_answers_summary="\n".join(summary_lines),
        )
        total_ms = round((time.perf_counter() - start_time) * 1000.0, 3)
        final_metrics = dict(synthesized.execution_metrics)
        final_metrics["duration_ms"] = total_ms
        return synthesized.model_copy(
            update={"execution_metrics": final_metrics}
        )
