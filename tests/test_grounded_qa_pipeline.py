"""Unit tests for GroundedQAPipeline in standard and curated_knowledge modes."""

import json
import uuid
from typing import AsyncIterator, Sequence

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from rag_foundry.citations.models import CitationValidationPolicy
from rag_foundry.db.models import (
    AssertionRecord,
    Base,
    Chunk,
    Document,
    EntityRecord,
)
from rag_foundry.model_gateway.adapters import MockDeterministicChatAdapter
from rag_foundry.model_gateway.gateway import ModelGateway
from rag_foundry.model_gateway.models import (
    ChatMessage,
    ModelProfile,
    ModelProfilePolicyError,
)
from rag_foundry.model_gateway.registry import InMemoryModelProfileRegistry
from rag_foundry.retrieval.lexical import LexicalRecord, LexicalRetriever
from rag_foundry.retrieval.pipeline import RetrievalPipeline
from rag_foundry.retrieval.security import (
    SecurityAuthorizationError,
    SecurityContext,
)


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Create an isolated in-memory async SQLite session factory."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _make_gateway(
    responder=None,
) -> tuple[ModelGateway, MockDeterministicChatAdapter]:
    """Build a ModelGateway with approved and draft mock profiles."""
    adapter = MockDeterministicChatAdapter(responder=responder)
    registry = InMemoryModelProfileRegistry(
        profiles=[
            ModelProfile(
                profile_id="qa-local",
                version="1.0.0",
                task="chat_generation",
                provider="mock",
                model_name="mock-grounded-v1",
                model_revision="rev-100",
                status="approved",
            ),
            ModelProfile(
                profile_id="qa-draft",
                version="0.1.0",
                task="chat_generation",
                provider="mock",
                model_name="mock-draft",
                status="draft",
            ),
        ]
    )
    gw = ModelGateway(registry=registry, adapters={"mock": adapter})
    return gw, adapter


@pytest.mark.asyncio
async def test_grounded_qa_pipeline_standard_mode_and_repro_trace() -> None:
    """Standard mode retrieves, generates, validates, and records traces."""
    from rag_foundry.generation.pipeline import (
        GroundedQAPipeline,
        GroundedQARequest,
    )

    ws_id = uuid.uuid4()
    doc_ver_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    sem_profile_id = uuid.uuid4()

    lex = LexicalRetriever()
    await lex.index_records(
        [
            LexicalRecord(
                chunk_id=chunk_id,
                document_version_id=doc_ver_id,
                workspace_id=ws_id,
                text=(
                    "Enterprise backup archives must be encrypted using "
                    "AES-256 and verified quarterly."
                ),
                section_path=["Security", "Backups"],
                page_numbers=[5],
                security_domain="security",
            )
        ]
    )
    retrieval = RetrievalPipeline(lexical_retriever=lex)

    def responder(
        _prof: ModelProfile, _msgs: Sequence[ChatMessage], _jm: bool
    ) -> str:
        return json.dumps(
            {
                "answer": (
                    "Enterprise backup archives must be encrypted using "
                    "AES-256 and verified quarterly [E1]."
                ),
                "claims": [
                    {
                        "text": (
                            "Enterprise backup archives must be encrypted "
                            "using AES-256 and verified quarterly."
                        ),
                        "evidence_ids": ["E1"],
                    }
                ],
                "limitations": [],
                "sufficient_evidence": True,
            }
        )

    gw, _ = _make_gateway(responder=responder)
    qa = GroundedQAPipeline(retrieval_pipeline=retrieval, model_gateway=gw)

    ctx = SecurityContext(
        user_id="sec-analyst",
        allowed_workspaces=[ws_id],
        allowed_security_domains=["security"],
    )
    ans = await qa.answer(
        GroundedQARequest(
            question="How must enterprise backup archives be protected?",
            workspace_id=ws_id,
            model_profile_id="qa-local",
            qa_mode="standard",
            semantic_profile_id=sem_profile_id,
            enable_dense=False,
            enable_expansion=False,
        ),
        security_context=ctx,
    )

    assert ans.abstained is False
    assert ans.sufficient_evidence is True
    assert ans.qa_mode == "standard"
    assert ans.semantic_profile_id == sem_profile_id
    assert ans.model_profile_id == "qa-local"
    assert ans.model_profile_version == "1.0.0"
    assert len(ans.claims) == 1
    assert ans.claims[0].verified is True
    assert ans.claims[0].authority == "document_evidence"
    assert len(ans.citations) == 1
    assert ans.citations[0].chunk_id == chunk_id
    assert ans.validation_report is not None
    assert ans.validation_report.passed is True
    assert ans.execution_metrics["model_revision"] == "rev-100"
    assert ans.execution_metrics["context_counts"]["document"] == 1


@pytest.mark.asyncio
async def test_grounded_qa_curated_knowledge_prioritization_and_isolation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """curated_knowledge loads assertions, prioritizes curated, isolates."""
    from rag_foundry.generation.pipeline import (
        GroundedQAPipeline,
        GroundedQARequest,
    )

    ws_id = uuid.uuid4()
    sem_profile = uuid.uuid4()
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    ent_id = uuid.uuid4()

    async with session_factory() as session:
        session.add_all(
            [
                Document(
                    id=doc_id,
                    document_id=uuid.uuid4(),
                    workspace_id=ws_id,
                    title="Retention Standard",
                    mime_type="application/pdf",
                    checksum="a" * 64,
                    page_count=2,
                    parser_name="native_pdf",
                    parser_version="1.0",
                    semantic_profile_id=sem_profile,
                ),
                Chunk(
                    id=chunk_id,
                    document_version_id=doc_id,
                    workspace_id=ws_id,
                    chunk_index=0,
                    text="Records must be retained for 7 years.",
                    section_path=["Retention"],
                    page_numbers=[1],
                    bounding_boxes=[],
                    security_domain="public",
                    checksum="b" * 64,
                    chunker_name="structural",
                    chunker_version="1.0",
                    semantic_profile_id=sem_profile,
                ),
                EntityRecord(
                    id=ent_id,
                    workspace_id=ws_id,
                    semantic_profile_id=sem_profile,
                    canonical_uri="http://id.example.org/policy/retention",
                    ontology_class_uri="http://example.org/ont#Policy",
                    preferred_labels={"en": "Retention Policy"},
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                AssertionRecord(
                    id=uuid.uuid4(),
                    workspace_id=ws_id,
                    semantic_profile_id=sem_profile,
                    subject_entity_id=ent_id,
                    property_uri="http://example.org/ont#retentionYears",
                    literal_value=7,
                    source_chunk_ids=[str(chunk_id)],
                    origin="curated",
                    extraction_method="steward",
                    confidence=1.0,
                    status="approved",
                ),
                AssertionRecord(
                    id=uuid.uuid4(),
                    workspace_id=ws_id,
                    semantic_profile_id=sem_profile,
                    subject_entity_id=ent_id,
                    property_uri="http://example.org/ont#draftNotes",
                    literal_value="candidate 5 years",
                    source_chunk_ids=[str(chunk_id)],
                    origin="extracted",
                    extraction_method="llm",
                    confidence=0.65,
                    status="candidate",
                ),
            ]
        )
        await session.commit()

    seen_prompts: list[str] = []

    def responder(
        _prof: ModelProfile, msgs: Sequence[ChatMessage], _jm: bool
    ) -> str:
        seen_prompts.append(msgs[-1].content)
        return json.dumps(
            {
                "answer": "Retention Policy retention years is 7 [A1].",
                "claims": [
                    {
                        "text": "Retention Policy retention years: 7.",
                        "evidence_ids": ["A1"],
                        "authority": "curated",
                    }
                ],
                "limitations": [],
                "sufficient_evidence": True,
            }
        )

    gw, _ = _make_gateway(responder=responder)
    qa = GroundedQAPipeline(
        retrieval_pipeline=RetrievalPipeline(),
        model_gateway=gw,
        session_or_factory=session_factory,
    )
    ctx = SecurityContext(
        user_id="steward",
        allowed_workspaces=[ws_id],
        allowed_security_domains=["public"],
    )

    ans = await qa.answer(
        GroundedQARequest(
            question="What is the official retention period?",
            workspace_id=ws_id,
            model_profile_id="qa-local",
            qa_mode="curated_knowledge",
            semantic_profile_id=sem_profile,
            include_extracted_candidates=False,
        ),
        security_context=ctx,
    )

    assert ans.abstained is False
    assert ans.sufficient_evidence is True
    assert ans.claims[0].authority == "curated"
    assert ans.citations[0].evidence_id == "A1"
    assert "[CURATED / APPROVED]" in seen_prompts[0]
    assert "[EXTRACTED / CANDIDATE — UNVERIFIED]" not in seen_prompts[0]


@pytest.mark.asyncio
async def test_grounded_qa_fail_closed_parse_acl_and_profile_errors() -> None:
    """Malformed output abstains; bad ACL/profile fails closed."""
    from rag_foundry.generation.pipeline import (
        GroundedQAPipeline,
        GroundedQARequest,
    )

    ws_id = uuid.uuid4()
    other_ws = uuid.uuid4()
    lex = LexicalRetriever()
    await lex.index_records(
        [
            LexicalRecord(
                chunk_id=uuid.uuid4(),
                document_version_id=uuid.uuid4(),
                workspace_id=ws_id,
                text="Policy document content on governance controls.",
                section_path=["Governance"],
                page_numbers=[1],
                security_domain="public",
            )
        ]
    )
    retrieval = RetrievalPipeline(lexical_retriever=lex)

    gw, adapter = _make_gateway(
        responder=lambda _p, _m, _j: "Unstructured plain text without JSON!"
    )
    qa = GroundedQAPipeline(retrieval_pipeline=retrieval, model_gateway=gw)

    # 1. Malformed LLM output -> explicit abstention
    ans = await qa.answer(
        GroundedQARequest(
            question="Summarize governance controls.",
            workspace_id=ws_id,
            model_profile_id="qa-local",
            enable_dense=False,
            enable_expansion=False,
        ),
        security_context=SecurityContext(
            user_id="u1",
            allowed_workspaces=[ws_id],
            allowed_security_domains=["public"],
        ),
    )
    assert ans.abstained is True
    assert ans.sufficient_evidence is False
    assert "parsing" in (ans.abstention_reason or "").lower()

    # 2. Empty allowed_security_domains -> fail-closed abstention, 0 LLM calls
    calls_before = len(adapter.calls)
    empty_dom_ans = await qa.answer(
        GroundedQARequest(
            question="Summarize governance controls.",
            workspace_id=ws_id,
            model_profile_id="qa-local",
        ),
        security_context=SecurityContext(
            user_id="u2",
            allowed_workspaces=[ws_id],
            allowed_security_domains=[],
        ),
    )
    assert empty_dom_ans.abstained is True
    assert len(adapter.calls) == calls_before

    # 3. Unauthorized workspace -> SecurityAuthorizationError
    with pytest.raises(SecurityAuthorizationError):
        await qa.answer(
            GroundedQARequest(
                question="Leak workspace.",
                workspace_id=ws_id,
                model_profile_id="qa-local",
            ),
            security_context=SecurityContext(
                user_id="u3",
                allowed_workspaces=[other_ws],
                allowed_security_domains=["public"],
            ),
        )

    # 4. Draft/unapproved model profile -> ModelProfilePolicyError
    with pytest.raises(ModelProfilePolicyError):
        await qa.answer(
            GroundedQARequest(
                question="Run draft model.",
                workspace_id=ws_id,
                model_profile_id="qa-draft",
            ),
            security_context=SecurityContext(
                user_id="u1",
                allowed_workspaces=[ws_id],
                allowed_security_domains=["public"],
            ),
        )
