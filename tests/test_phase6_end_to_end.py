"""End-to-end Phase 6 exit-criteria integration and regression test suite.

Validates all five Phase 6 exit criteria from real PDF ingestion and indexing
through DB-backed hybrid retrieval, authorized assertion loading, ModelGateway,
and post-generation citation validation across standard, curated_knowledge,
and decomposed QA modes:
1. Every supported claim links to verified, supplied, authorized evidence.
2. Invalid, unauthorized, and superseded citation IDs are rejected.
3. Low-evidence or ungrounded questions trigger warning or abstention.
4. Curated and extracted knowledge are visibly distinguished.
5. Unapproved model profiles and disallowed remote URLs fail closed.
"""

import io
import json
import tempfile
import uuid
from typing import Any, AsyncIterator, Dict, Sequence

import fitz
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from rag_foundry.chunking import ChunkingConfig, StructuralChunker
from rag_foundry.citations import CitationValidationPolicy
from rag_foundry.db.models import (
    AssertionRecord,
    Base,
    EntityRecord,
)
from rag_foundry.generation import (
    GroundedQAPipeline,
    GroundedQARequest,
)
from rag_foundry.ingestion.indexer import IndexerService
from rag_foundry.ingestion.pipeline import (
    IngestionJobStatus,
    IngestionPipeline,
)
from rag_foundry.model_gateway import (
    InMemoryModelProfileRegistry,
    MockDeterministicChatAdapter,
    ModelGateway,
    ModelProfile,
    ModelProfilePolicyError,
)
from rag_foundry.retrieval.embeddings import MockDeterministicEmbeddingService
from rag_foundry.retrieval.pipeline import RetrievalPipeline
from rag_foundry.retrieval.postgres_dense import PostgresDenseRetriever
from rag_foundry.retrieval.postgres_lexical import PostgresLexicalRetriever
from rag_foundry.retrieval.security import SecurityContext
from rag_foundry.storage.provider import LocalStorageProvider


def _make_pdf_bytes(heading: str, body: str) -> bytes:
    """Create a real digital PDF containing a heading and body text."""
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((50, 60), heading, fontsize=16)
    page.insert_text((50, 110), body, fontsize=11)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


@pytest_asyncio.fixture
async def e2e_env() -> AsyncIterator[Dict[str, Any]]:
    """Ingest real PDFs and seed curated/extracted assertions into SQLite."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    ws_id = uuid.uuid4()
    sem_profile = uuid.uuid4()
    embedder = MockDeterministicEmbeddingService(dimension=64)
    chunker = StructuralChunker(ChunkingConfig(max_tokens=200, min_tokens=5))

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorageProvider(base_path=tmpdir)
        async with factory() as session:
            indexer = IndexerService(
                session_or_factory=session,
                embedding_service=embedder,
                chunker=chunker,
                expected_embedding_dim=64,
            )
            ingest = IngestionPipeline(
                storage_provider=storage,
                session=session,
                indexer=indexer,
            )

            res_ret = await ingest.ingest_and_index(
                file_bytes=_make_pdf_bytes(
                    "Retention Policy",
                    (
                        "Financial audit records must be retained for 7 years "
                        "in immutable archival vaults."
                    ),
                ),
                filename="retention_policy.pdf",
                mime_type="application/pdf",
                workspace_id=ws_id,
                semantic_profile_id=sem_profile,
                security_domain="public",
            )
            assert res_ret.status == IngestionJobStatus.INDEXED
            assert res_ret.indexing_result is not None
            ret_chunk_id = res_ret.indexing_result.chunk_ids[0]

            res_enc = await ingest.ingest_and_index(
                file_bytes=_make_pdf_bytes(
                    "Encryption Standard",
                    (
                        "All archival vaults require AES-256 encryption with "
                        "annual cryptographic key rotation."
                    ),
                ),
                filename="encryption_standard.pdf",
                mime_type="application/pdf",
                workspace_id=ws_id,
                semantic_profile_id=sem_profile,
                security_domain="public",
            )
            assert res_enc.status == IngestionJobStatus.INDEXED
            assert res_enc.indexing_result is not None
            enc_chunk_id = res_enc.indexing_result.chunk_ids[0]

            res_sec = await ingest.ingest_and_index(
                file_bytes=_make_pdf_bytes(
                    "Restricted Board Override Annex",
                    (
                        "Emergency override codes are held exclusively by the "
                        "Chief Risk Officer in vault Alpha-9."
                    ),
                ),
                filename="restricted_override.pdf",
                mime_type="application/pdf",
                workspace_id=ws_id,
                semantic_profile_id=sem_profile,
                security_domain="restricted",
            )
            assert res_sec.status == IngestionJobStatus.INDEXED
            assert res_sec.indexing_result is not None
            sec_chunk_id = res_sec.indexing_result.chunk_ids[0]

            # Seed governed EntityRecord + curated & extracted assertions
            ent_policy = EntityRecord(
                id=uuid.uuid4(),
                workspace_id=ws_id,
                semantic_profile_id=sem_profile,
                canonical_uri="http://id.example.org/policy/audit-retention",
                ontology_class_uri="http://example.org/ont#Policy",
                preferred_labels={"en": "Audit Retention Policy"},
            )
            session.add(ent_policy)
            await session.flush()

            session.add_all(
                [
                    AssertionRecord(
                        id=uuid.uuid4(),
                        workspace_id=ws_id,
                        semantic_profile_id=sem_profile,
                        subject_entity_id=ent_policy.id,
                        property_uri="http://example.org/ont#retentionYears",
                        literal_value=7,
                        source_chunk_ids=[str(ret_chunk_id)],
                        origin="curated",
                        extraction_method="steward",
                        confidence=1.0,
                        status="approved",
                    ),
                    AssertionRecord(
                        id=uuid.uuid4(),
                        workspace_id=ws_id,
                        semantic_profile_id=sem_profile,
                        subject_entity_id=ent_policy.id,
                        property_uri="http://example.org/ont#draftArchiveTier",
                        literal_value="cold glacier 5 years",
                        source_chunk_ids=[str(ret_chunk_id)],
                        origin="extracted",
                        extraction_method="llm",
                        confidence=0.70,
                        status="candidate",
                    ),
                    AssertionRecord(
                        id=uuid.uuid4(),
                        workspace_id=ws_id,
                        semantic_profile_id=sem_profile,
                        subject_entity_id=ent_policy.id,
                        property_uri="http://example.org/ont#overrideVault",
                        literal_value="Alpha-9",
                        source_chunk_ids=[str(sec_chunk_id)],
                        origin="curated",
                        extraction_method="steward",
                        confidence=1.0,
                        status="approved",
                    ),
                ]
            )
            await session.commit()

        retrieval = RetrievalPipeline(
            dense_retriever=PostgresDenseRetriever(
                session_or_factory=factory, embedding_service=embedder
            ),
            lexical_retriever=PostgresLexicalRetriever(
                session_or_factory=factory
            ),
        )
        try:
            yield {
                "factory": factory,
                "retrieval": retrieval,
                "ws_id": ws_id,
                "sem_profile": sem_profile,
                "ret_doc_ver": res_ret.document_id,
                "enc_doc_ver": res_enc.document_id,
                "sec_doc_ver": res_sec.document_id,
                "ret_chunk_id": ret_chunk_id,
                "enc_chunk_id": enc_chunk_id,
                "sec_chunk_id": sec_chunk_id,
            }
        finally:
            await engine.dispose()


def _build_gateway(responder) -> ModelGateway:
    """Build a ModelGateway with approved, draft, deprecated, and bad URL."""
    registry = InMemoryModelProfileRegistry(
        profiles=[
            ModelProfile(
                profile_id="balanced-local",
                version="1.0.0",
                task="chat_generation",
                provider="mock",
                model_name="mock-balanced",
                model_revision="sha256:e2e",
                status="approved",
            ),
            ModelProfile(
                profile_id="decomposer-local",
                version="1.0.0",
                task="query_decomposition",
                provider="mock",
                model_name="mock-decomposer",
                status="approved",
            ),
            ModelProfile(
                profile_id="unapproved-draft",
                version="0.1.0",
                task="chat_generation",
                provider="mock",
                model_name="mock-draft",
                status="draft",
            ),
            ModelProfile(
                profile_id="old-deprecated",
                version="0.9.0",
                task="chat_generation",
                provider="mock",
                model_name="mock-old",
                status="deprecated",
            ),
            ModelProfile(
                profile_id="bad-remote-local",
                version="1.0.0",
                task="chat_generation",
                provider="openai_compatible",
                model_name="remote-llm",
                base_url="https://api.openai.com",
                deployment_policy="local_only",
                status="approved",
            ),
        ]
    )
    return ModelGateway(
        registry=registry,
        adapters={"mock": MockDeterministicChatAdapter(responder=responder)},
    )


@pytest.mark.asyncio
async def test_phase6_exit_criteria_standard_and_decomposed_modes(
    e2e_env: Dict[str, Any],
) -> None:
    """Exit Criterion 1: grounded claims link to authorized PDF chunks."""
    seen_contexts: list[str] = []

    def responder(
        prof: ModelProfile, msgs: Sequence[Any], _jm: bool
    ) -> str:
        if prof.task == "query_decomposition":
            return json.dumps(
                {
                    "sub_questions": [
                        "How long must financial audit records be retained?",
                        "What encryption is required for archival vaults?",
                    ]
                }
            )
        user_text = msgs[-1].content
        seen_contexts.append(user_text)
        if "Sub-Question Findings:" in user_text:
            # Find which E-handle corresponds to retention vs encryption
            ret_h = "E1"
            enc_h = "E2"
            for line in user_text.splitlines():
                if "7 years" in line and line.startswith("[E"):
                    ret_h = line.split("]")[0][1:]
                if "AES-256" in line and line.startswith("[E"):
                    enc_h = line.split("]")[0][1:]
            return json.dumps(
                {
                    "answer": (
                        f"Financial audit records must be retained for "
                        f"7 years [{ret_h}], and archival vaults require "
                        f"AES-256 encryption [{enc_h}]."
                    ),
                    "claims": [
                        {
                            "text": (
                                "Financial audit records must be retained "
                                "for 7 years in archival vaults."
                            ),
                            "evidence_ids": [ret_h],
                        },
                        {
                            "text": (
                                "Archival vaults require AES-256 encryption "
                                "with annual key rotation."
                            ),
                            "evidence_ids": [enc_h],
                        },
                    ],
                    "limitations": [],
                    "sufficient_evidence": True,
                }
            )
        q_part = user_text.split("Authorized Evidence Context:", 1)[0].lower()
        if "encryption" in q_part and "AES-256" in user_text:
            enc_h = "E1"
            for line in user_text.splitlines():
                if "AES-256" in line and line.startswith("[E"):
                    enc_h = line.split("]")[0][1:]
                    break
            return json.dumps(
                {
                    "answer": f"Archival vaults require AES-256 [{enc_h}].",
                    "claims": [
                        {
                            "text": (
                                "Archival vaults require AES-256 encryption "
                                "with annual key rotation."
                            ),
                            "evidence_ids": [enc_h],
                        }
                    ],
                    "limitations": [],
                    "sufficient_evidence": True,
                }
            )
        ret_h = "E1"
        for line in user_text.splitlines():
            if "7 years" in line and line.startswith("[E"):
                ret_h = line.split("]")[0][1:]
                break
        return json.dumps(
            {
                "answer": (
                    f"Financial audit records must be retained for 7 years "
                    f"[{ret_h}]."
                ),
                "claims": [
                    {
                        "text": (
                            "Financial audit records must be retained for "
                            "7 years in immutable archival vaults."
                        ),
                        "evidence_ids": [ret_h],
                    }
                ],
                "limitations": [],
                "sufficient_evidence": True,
            }
        )

    qa = GroundedQAPipeline(
        retrieval_pipeline=e2e_env["retrieval"],
        model_gateway=_build_gateway(responder),
        session_or_factory=e2e_env["factory"],
    )
    pub_ctx = SecurityContext(
        user_id="public-analyst",
        allowed_workspaces=[e2e_env["ws_id"]],
        allowed_security_domains=["public"],
    )

    # 1a. Standard mode grounded answer from ingested PDF
    std_ans = await qa.answer(
        GroundedQARequest(
            question="How long must financial audit records be retained?",
            workspace_id=e2e_env["ws_id"],
            model_profile_id="balanced-local",
            qa_mode="standard",
            semantic_profile_id=e2e_env["sem_profile"],
            active_document_version_ids=(
                e2e_env["ret_doc_ver"],
                e2e_env["enc_doc_ver"],
            ),
        ),
        security_context=pub_ctx,
    )
    assert std_ans.abstained is False
    assert std_ans.sufficient_evidence is True
    assert len(std_ans.claims) == 1
    assert std_ans.claims[0].verified is True
    assert std_ans.citations[0].chunk_id == e2e_env["ret_chunk_id"]
    assert std_ans.citations[0].document_version_id == e2e_env["ret_doc_ver"]
    assert std_ans.citations[0].page_numbers == (1,)
    assert len(std_ans.citations[0].bounding_boxes) >= 1

    # 1b. Decomposed mode across both PDFs with zero restricted leakage
    dec_ans = await qa.answer(
        GroundedQARequest(
            question=(
                "How long must financial audit records be retained and what "
                "encryption is required for archival vaults?"
            ),
            workspace_id=e2e_env["ws_id"],
            model_profile_id="balanced-local",
            decomposition_profile_id="decomposer-local",
            qa_mode="decomposed",
            semantic_profile_id=e2e_env["sem_profile"],
        ),
        security_context=pub_ctx,
    )
    assert dec_ans.abstained is False
    assert dec_ans.sufficient_evidence is True
    assert len(dec_ans.claims) == 2
    assert all(c.verified for c in dec_ans.claims)
    cited_chunks = {c.chunk_id for c in dec_ans.citations}
    assert cited_chunks == {
        e2e_env["ret_chunk_id"],
        e2e_env["enc_chunk_id"],
    }
    assert e2e_env["sec_chunk_id"] not in cited_chunks
    # Restricted text never entered any LLM prompt
    assert all("Alpha-9" not in prompt for prompt in seen_contexts)
    assert dec_ans.execution_metrics["decomposition"]["method"] == "llm"


@pytest.mark.asyncio
async def test_phase6_exit_criteria_curated_vs_extracted_distinction(
    e2e_env: Dict[str, Any],
) -> None:
    """Exit Criterion 4: curated vs extracted visibly distinguished."""
    seen_prompts: list[str] = []

    def misrep_responder(
        _prof: ModelProfile, msgs: Sequence[Any], _jm: bool
    ) -> str:
        seen_prompts.append(msgs[-1].content)
        # Attempt to falsely claim curated authority from candidate [A2]
        return json.dumps(
            {
                "answer": "Audit Retention Policy draft archive tier [A2].",
                "claims": [
                    {
                        "text": (
                            "Audit Retention Policy draft archive tier: "
                            "cold glacier 5 years."
                        ),
                        "evidence_ids": ["A2"],
                        "authority": "curated",
                    }
                ],
                "sufficient_evidence": True,
            }
        )

    qa_misrep = GroundedQAPipeline(
        retrieval_pipeline=e2e_env["retrieval"],
        model_gateway=_build_gateway(misrep_responder),
        session_or_factory=e2e_env["factory"],
    )
    pub_ctx = SecurityContext(
        user_id="steward-analyst",
        allowed_workspaces=[e2e_env["ws_id"]],
        allowed_security_domains=["public"],
    )

    # Misrepresenting extracted candidate [A2] as curated fails closed
    blocked = await qa_misrep.answer(
        GroundedQARequest(
            question="What is the draft archive tier for audit retention?",
            workspace_id=e2e_env["ws_id"],
            model_profile_id="balanced-local",
            qa_mode="curated_knowledge",
            semantic_profile_id=e2e_env["sem_profile"],
        ),
        security_context=pub_ctx,
    )
    assert blocked.abstained is True
    assert blocked.sufficient_evidence is False
    assert "[CURATED / APPROVED]" in seen_prompts[0]
    assert "[EXTRACTED / CANDIDATE — UNVERIFIED]" in seen_prompts[0]
    assert "Alpha-9" not in seen_prompts[0]

    # Properly labeled extracted-only answer emits explicit disclosure
    def honest_ext_responder(
        _prof: ModelProfile, _msgs: Sequence[Any], _jm: bool
    ) -> str:
        return json.dumps(
            {
                "answer": (
                    "Candidate extraction suggests cold glacier 5 years [A2]."
                ),
                "claims": [
                    {
                        "text": (
                            "Audit Retention Policy draft archive tier: "
                            "cold glacier 5 years."
                        ),
                        "evidence_ids": ["A2"],
                        "authority": "extracted",
                    }
                ],
                "sufficient_evidence": True,
            }
        )

    qa_honest = GroundedQAPipeline(
        retrieval_pipeline=e2e_env["retrieval"],
        model_gateway=_build_gateway(honest_ext_responder),
        session_or_factory=e2e_env["factory"],
    )
    disclosed = await qa_honest.answer(
        GroundedQARequest(
            question="What is the draft archive tier?",
            workspace_id=e2e_env["ws_id"],
            model_profile_id="balanced-local",
            qa_mode="curated_knowledge",
            semantic_profile_id=e2e_env["sem_profile"],
        ),
        security_context=pub_ctx,
    )
    assert disclosed.abstained is False
    assert disclosed.claims[0].authority == "extracted"
    assert any(
        "unapproved extracted" in lim.lower() for lim in disclosed.limitations
    )

    # Disallowing extracted-only via policy triggers explicit abstention
    abstained_ext = await qa_honest.answer(
        GroundedQARequest(
            question="What is the draft archive tier?",
            workspace_id=e2e_env["ws_id"],
            model_profile_id="balanced-local",
            qa_mode="curated_knowledge",
            semantic_profile_id=e2e_env["sem_profile"],
            citation_policy=CitationValidationPolicy(
                allow_extracted_only_answers=False
            ),
        ),
        security_context=pub_ctx,
    )
    assert abstained_ext.abstained is True


@pytest.mark.asyncio
async def test_phase6_exit_criteria_invalid_low_evidence_and_profiles(
    e2e_env: Dict[str, Any],
) -> None:
    """Exit Criteria 2, 3, and 5: bad citations, low evidence, bad profiles."""
    pub_ctx = SecurityContext(
        user_id="auditor",
        allowed_workspaces=[e2e_env["ws_id"]],
        allowed_security_domains=["public"],
    )

    # Exit Criterion 2a: Fabricated citation ID [E99] rejected
    qa_fab = GroundedQAPipeline(
        retrieval_pipeline=e2e_env["retrieval"],
        model_gateway=_build_gateway(
            lambda _p, _m, _j: json.dumps(
                {
                    "answer": "Records retained 7 years [E99].",
                    "claims": [
                        {
                            "text": "Records retained 7 years.",
                            "evidence_ids": ["E99"],
                        }
                    ],
                    "sufficient_evidence": True,
                }
            )
        ),
        session_or_factory=e2e_env["factory"],
    )
    fab_ans = await qa_fab.answer(
        GroundedQARequest(
            question="How long are financial audit records retained?",
            workspace_id=e2e_env["ws_id"],
            model_profile_id="balanced-local",
        ),
        security_context=pub_ctx,
    )
    assert fab_ans.abstained is True
    assert fab_ans.validation_report is not None
    assert "E99" in fab_ans.validation_report.invalid_citation_ids

    # Exit Criterion 2b: Superseded document revision rejected
    qa_ok = GroundedQAPipeline(
        retrieval_pipeline=e2e_env["retrieval"],
        model_gateway=_build_gateway(
            lambda _p, _m, _j: json.dumps(
                {
                    "answer": "Financial audit records retained 7 years [E1].",
                    "claims": [
                        {
                            "text": (
                                "Financial audit records must be retained "
                                "for 7 years."
                            ),
                            "evidence_ids": ["E1"],
                        }
                    ],
                    "sufficient_evidence": True,
                }
            )
        ),
        session_or_factory=e2e_env["factory"],
    )
    superseded_ans = await qa_ok.answer(
        GroundedQARequest(
            question="How long are financial audit records retained?",
            workspace_id=e2e_env["ws_id"],
            model_profile_id="balanced-local",
            superseded_document_version_ids=(
                e2e_env["ret_doc_ver"],
                e2e_env["enc_doc_ver"],
            ),
        ),
        security_context=pub_ctx,
    )
    assert superseded_ans.abstained is True
    assert superseded_ans.validation_report is not None
    assert "E1" in superseded_ans.validation_report.superseded_citation_ids

    # Exit Criterion 3: Low-evidence query triggers abstention
    low_ev_ans = await qa_ok.answer(
        GroundedQARequest(
            question="Explain lunar orbital mechanics.",
            workspace_id=e2e_env["ws_id"],
            model_profile_id="balanced-local",
            min_relevance_score=0.95,
        ),
        security_context=pub_ctx,
    )
    assert low_ev_ans.abstained is True
    assert low_ev_ans.sufficient_evidence is False

    # Exit Criterion 5: Unapproved draft, deprecated, and bad local_only URL
    for blocked_profile in [
        "unapproved-draft",
        "old-deprecated",
        "bad-remote-local",
    ]:
        with pytest.raises(ModelProfilePolicyError):
            await qa_ok.answer(
                GroundedQARequest(
                    question="Test governance gate.",
                    workspace_id=e2e_env["ws_id"],
                    model_profile_id=blocked_profile,
                ),
                security_context=pub_ctx,
            )
