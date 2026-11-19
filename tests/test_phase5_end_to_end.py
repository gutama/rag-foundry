"""End-to-end Phase 5 exit-criteria integration and regression test suite.

Validates all four Phase 5 exit criteria from ingestion through DB-backed
retrieval and governed semantic expansion:
1. Zero unauthorized chunk entry across workspaces and security domains.
2. Deterministic, reproducible rankings and tie-breaking across runs.
3. Complete semantic expansion provenance traces (approved sources only).
4. Alias/hierarchy recall gains with zero exact-term top-1 regression.
"""

import io
import tempfile
import uuid
from datetime import datetime, timezone
from typing import List, Sequence, Tuple

import docx
import fitz
import openpyxl
import pytest

from rag_foundry.chunking import ChunkingConfig, StructuralChunker
from rag_foundry.db.models import (
    AssertionRecord,
    EntityRecord,
    OntologyClassRecord,
    OntologyReleaseRecord,
)
from rag_foundry.ingestion.indexer import IndexerService
from rag_foundry.ingestion.pipeline import (
    IngestionJobStatus,
    IngestionPipeline,
)
from rag_foundry.retrieval.dense import DenseVectorRecord, DenseVectorRetriever
from rag_foundry.retrieval.embeddings import MockDeterministicEmbeddingService
from rag_foundry.retrieval.expansion import SemanticQueryExpansionService
from rag_foundry.retrieval.fusion import ReciprocalRankFusion
from rag_foundry.retrieval.lexical import LexicalRecord, LexicalRetriever
from rag_foundry.retrieval.models import (
    RankedChunk,
    RetrievalFilter,
    RetrievalQuery,
)
from rag_foundry.retrieval.ontology_expansion import (
    EntityQueryExpander,
    ExpansionPolicy,
    OntologyQueryExpander,
)
from rag_foundry.retrieval.pipeline import RetrievalPipeline
from rag_foundry.retrieval.postgres_dense import PostgresDenseRetriever
from rag_foundry.retrieval.postgres_lexical import PostgresLexicalRetriever
from rag_foundry.retrieval.reranking import (
    CrossEncoderReranker,
    ScoringReranker,
)
from rag_foundry.retrieval.security import (
    SecurityAuthorizationError,
    SecurityContext,
)
from rag_foundry.storage.provider import LocalStorageProvider
from rag_foundry.taxonomy.models import (
    SKOSConceptModel,
    SKOSConceptSchemeModel,
)


def _make_pdf_bytes(heading: str, body: str) -> bytes:
    """Create a real digital PDF containing a heading and paragraph."""
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((50, 60), heading, fontsize=18)
    page.insert_text((50, 110), body, fontsize=12)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _make_docx_bytes(heading: str, paragraphs: List[str]) -> bytes:
    """Create a real DOCX document containing a heading and paragraphs."""
    document = docx.Document()
    document.add_heading(heading, level=1)
    for para in paragraphs:
        document.add_paragraph(para)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _make_xlsx_bytes(sheet_title: str, rows: List[List[str]]) -> bytes:
    """Create a real XLSX workbook containing tabular rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _banking_skos_scheme() -> SKOSConceptSchemeModel:
    """Build a small SKOS taxonomy scheme for capital adequacy queries."""
    scheme_uri = "urn:scheme:phase5-banking"
    return SKOSConceptSchemeModel(
        scheme_id=str(uuid.uuid4()),
        uri=scheme_uri,
        title="Phase 5 Banking Taxonomy",
        version="1.0",
        concepts=[
            SKOSConceptModel(
                scheme_uri=scheme_uri,
                uri="urn:concept:capital_requirements",
                pref_label="Capital Requirements",
                alt_labels=["Prudential Capital"],
                broader_uris=[],
            ),
            SKOSConceptModel(
                scheme_uri=scheme_uri,
                uri="urn:concept:tier1_capital",
                pref_label="Tier 1 Capital",
                alt_labels=["Core Capital", "T1 Capital"],
                broader_uris=["urn:concept:capital_requirements"],
            ),
        ],
    )


async def _seed_governed_semantics(
    session,
    workspace_id: uuid.UUID,
    semantic_profile_id: uuid.UUID,
) -> Tuple[OntologyReleaseRecord, OntologyReleaseRecord, EntityRecord]:
    """Seed approved/draft releases, redirected entity, and candidate."""
    approved_rel = OntologyReleaseRecord(
        id=uuid.uuid4(),
        ontology_uri="https://example.org/onto/phase5",
        version="1.0.0",
        title="Approved Supervision Ontology",
        status="approved",
        published_at=datetime.now(timezone.utc),
    )
    draft_rel = OntologyReleaseRecord(
        id=uuid.uuid4(),
        ontology_uri="https://example.org/onto/phase5",
        version="2.0.0-draft",
        title="Unpublished Draft Ontology",
        status="draft",
    )
    session.add_all([approved_rel, draft_rel])
    await session.flush()

    cls_regulator = OntologyClassRecord(
        release_id=approved_rel.id,
        uri="https://example.org/onto/FinancialRegulator",
        preferred_labels={"en": "Financial Regulator"},
        parent_class_uris=[],
        status="active",
    )
    cls_central_bank = OntologyClassRecord(
        release_id=approved_rel.id,
        uri="https://example.org/onto/CentralBank",
        preferred_labels={"en": "Central Bank"},
        parent_class_uris=["https://example.org/onto/FinancialRegulator"],
        status="active",
    )
    cls_draft = OntologyClassRecord(
        release_id=draft_rel.id,
        uri="https://example.org/onto/DraftSecretConcept",
        preferred_labels={"en": "DraftSecretConcept"},
        parent_class_uris=["https://example.org/onto/CentralBank"],
        status="active",
    )

    entity_survivor = EntityRecord(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        semantic_profile_id=semantic_profile_id,
        canonical_uri="urn:entity:bis",
        ontology_class_uri="https://example.org/onto/FinancialRegulator",
        preferred_labels={"en": "Bank for International Settlements"},
        aliases={"en": ["BIS Basel"]},
        status="active",
    )
    session.add_all(
        [cls_regulator, cls_central_bank, cls_draft, entity_survivor]
    )
    await session.flush()

    entity_merged = EntityRecord(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        semantic_profile_id=semantic_profile_id,
        canonical_uri="urn:entity:old-basel",
        ontology_class_uri="https://example.org/onto/FinancialRegulator",
        preferred_labels={"en": "Old Basel Org"},
        aliases={"en": ["Legacy Basel Body"]},
        status="merged",
        merged_into_id=entity_survivor.id,
    )
    unapproved_assertion = AssertionRecord(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        semantic_profile_id=semantic_profile_id,
        subject_entity_id=entity_survivor.id,
        property_uri="https://example.org/onto/hasAlias",
        literal_value="Unapproved Hallucinated Alias",
        source_chunk_ids=[],
        origin="extracted",
        extraction_method="llm_test",
        confidence=0.99,
        status="candidate",
    )
    session.add_all([entity_merged, unapproved_assertion])
    await session.commit()
    return approved_rel, draft_rel, entity_survivor


@pytest.mark.asyncio
async def test_deterministic_tie_breaking_across_components() -> None:
    """Tied scores always order ascending by str(chunk_id) across components."""
    ws_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    id_a = uuid.UUID("00000000-0000-0000-0000-000000000001")
    id_b = uuid.UUID("00000000-0000-0000-0000-000000000002")

    chunk_a = RankedChunk(
        chunk_id=id_a,
        document_version_id=doc_id,
        workspace_id=ws_id,
        text="Identical capital control text.",
        score=0.5,
    )
    chunk_b = RankedChunk(
        chunk_id=id_b,
        document_version_id=doc_id,
        workspace_id=ws_id,
        text="Identical capital control text.",
        score=0.5,
    )

    # 1. ReciprocalRankFusion deterministic tie-breaking independent of order
    rrf = ReciprocalRankFusion(k=60)
    fused_1 = rrf.fuse(
        {"dense": [chunk_b], "lexical": [chunk_a]},
        top_k=2,
    )
    fused_2 = rrf.fuse(
        {"lexical": [chunk_a], "dense": [chunk_b]},
        top_k=2,
    )
    assert [c.chunk_id for c in fused_1] == [id_a, id_b]
    assert [c.chunk_id for c in fused_2] == [id_a, id_b]

    # 2. DenseVectorRetriever deterministic tie-breaking with identical vectors
    emb = MockDeterministicEmbeddingService(dimension=16)
    shared_vec = emb.embed_query("identical query")
    dense = DenseVectorRetriever(emb)
    await dense.index_records(
        [
            DenseVectorRecord(
                chunk_id=id_b,
                document_version_id=doc_id,
                workspace_id=ws_id,
                text="Identical text",
                vector=list(shared_vec),
                security_domain="public",
            ),
            DenseVectorRecord(
                chunk_id=id_a,
                document_version_id=doc_id,
                workspace_id=ws_id,
                text="Identical text",
                vector=list(shared_vec),
                security_domain="public",
            ),
        ]
    )
    q = RetrievalQuery(
        query_text="identical query",
        filter=RetrievalFilter(workspace_id=ws_id, security_domains=["public"]),
        top_k=2,
    )
    dense_hits = await dense.retrieve(q)
    assert [c.chunk_id for c in dense_hits] == [id_a, id_b]

    # 3. LexicalRetriever & ScoringReranker deterministic tie-breaking
    lexical = LexicalRetriever()
    await lexical.index_records(
        [
            LexicalRecord(
                chunk_id=id_b,
                document_version_id=doc_id,
                workspace_id=ws_id,
                text="Identical capital control text.",
                security_domain="public",
            ),
            LexicalRecord(
                chunk_id=id_a,
                document_version_id=doc_id,
                workspace_id=ws_id,
                text="Identical capital control text.",
                security_domain="public",
            ),
        ]
    )
    lex_hits = await lexical.retrieve(
        RetrievalQuery(
            query_text="capital control",
            filter=RetrievalFilter(
                workspace_id=ws_id, security_domains=["public"]
            ),
            top_k=2,
        )
    )
    assert [c.chunk_id for c in lex_hits] == [id_a, id_b]

    reranker = ScoringReranker()
    reranked = reranker.rerank("capital control", [chunk_b, chunk_a], top_k=2)
    assert [c.chunk_id for c in reranked] == [id_a, id_b]


@pytest.mark.asyncio
async def test_phase5_e2e_zero_unauthorized_leakage_across_workspaces_domains(
    session_factory,
) -> None:
    """Exit Criterion 1: zero unauthorized chunks enter any retrieval stage."""
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()
    prof_id = uuid.uuid4()
    emb = MockDeterministicEmbeddingService(dimension=32)

    async with session_factory() as session:
        indexer = IndexerService(
            session_or_factory=session,
            embedding_service=emb,
            chunker=StructuralChunker(
                ChunkingConfig(target_chars=400, max_chars=500)
            ),
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = LocalStorageProvider(base_path=tmp_dir)
            ingest = IngestionPipeline(
                storage_provider=storage,
                session=session,
                indexer=indexer,
            )

            pub_res = await ingest.ingest_and_index(
                file_bytes=_make_pdf_bytes(
                    "Public Liquidity Guide",
                    "Standard liquidity reserve policy for public reporting.",
                ),
                filename="public_guide.pdf",
                mime_type="application/pdf",
                workspace_id=ws_a,
                semantic_profile_id=prof_id,
                security_domain="public",
            )
            restricted_res = await ingest.ingest_and_index(
                file_bytes=_make_docx_bytes(
                    "Confidential Merger Plan",
                    [
                        "Project Obsidian Secret details restricted treasury "
                        "allocations."
                    ],
                ),
                filename="restricted.docx",
                mime_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                workspace_id=ws_a,
                semantic_profile_id=prof_id,
                security_domain="restricted",
            )
            other_ws_res = await ingest.ingest_and_index(
                file_bytes=_make_xlsx_bytes(
                    "WorkspaceB",
                    [
                        ["Code", "Description"],
                        [
                            "WSB-999",
                            "WorkspaceB Exclusive Token confidential ledger.",
                        ],
                    ],
                ),
                filename="ws_b.xlsx",
                mime_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                workspace_id=ws_b,
                semantic_profile_id=prof_id,
                security_domain="public",
            )
            assert pub_res.status == IngestionJobStatus.INDEXED
            assert restricted_res.status == IngestionJobStatus.INDEXED
            assert other_ws_res.status == IngestionJobStatus.INDEXED

            pipeline = RetrievalPipeline(
                dense_retriever=PostgresDenseRetriever(session, emb),
                lexical_retriever=PostgresLexicalRetriever(session),
                reranker=ScoringReranker(),
            )

            # 1a. Public-only caller with unfiltered query never sees restricted
            public_ctx = SecurityContext(
                user_id="public_user",
                allowed_workspaces=[ws_a],
                allowed_security_domains=["public"],
            )
            res_secret = await pipeline.execute(
                query=RetrievalQuery(
                    query_text="Project Obsidian Secret",
                    filter=RetrievalFilter(workspace_id=ws_a),
                    top_k=10,
                ),
                security_context=public_ctx,
            )
            assert res_secret.execution_metrics["lexical_candidate_count"] == 0
            assert all(
                "Obsidian" not in c.text and c.workspace_id == ws_a
                for c in res_secret.ranked_chunks
            )
            assert all(
                "Obsidian" not in ev.snippet
                for ev in res_secret.evidence_items
            )

            # 1b. Explicitly requesting unauthorized domain raises immediately
            with pytest.raises(SecurityAuthorizationError):
                await pipeline.execute(
                    query=RetrievalQuery(
                        query_text="Project Obsidian Secret",
                        filter=RetrievalFilter(
                            workspace_id=ws_a,
                            security_domains=["public", "restricted"],
                        ),
                        top_k=10,
                    ),
                    security_context=public_ctx,
                )

            # 2. Cross-workspace request raises SecurityAuthorizationError
            with pytest.raises(SecurityAuthorizationError):
                await pipeline.execute(
                    query=RetrievalQuery(
                        query_text="WorkspaceB Exclusive Token",
                        filter=RetrievalFilter(
                            workspace_id=ws_b, security_domains=["public"]
                        ),
                        top_k=5,
                    ),
                    security_context=public_ctx,
                )

            # 3. Empty allowed_security_domains fails closed (zero chunks)
            no_domain_ctx = SecurityContext(
                user_id="locked_user",
                allowed_workspaces=[ws_a],
                allowed_security_domains=[],
            )
            closed_res = await pipeline.execute(
                query=RetrievalQuery(
                    query_text="Standard liquidity reserve policy",
                    filter=RetrievalFilter(workspace_id=ws_a),
                    top_k=5,
                ),
                security_context=no_domain_ctx,
            )
            assert closed_res.execution_metrics["dense_candidate_count"] == 0
            assert closed_res.execution_metrics["lexical_candidate_count"] == 0
            assert closed_res.ranked_chunks == []
            assert closed_res.evidence_items == []

            # 4. Authorized restricted caller retrieves restricted DOCX cleanly
            privileged_ctx = SecurityContext(
                user_id="privileged_user",
                allowed_workspaces=[ws_a],
                allowed_security_domains=["public", "restricted"],
            )
            priv_res = await pipeline.execute(
                query=RetrievalQuery(
                    query_text="Project Obsidian Secret",
                    filter=RetrievalFilter(
                        workspace_id=ws_a,
                        security_domains=["restricted"],
                    ),
                    top_k=5,
                ),
                security_context=privileged_ctx,
            )
            assert len(priv_res.ranked_chunks) >= 1
            assert "Obsidian" in priv_res.ranked_chunks[0].text
            assert priv_res.ranked_chunks[0].section_path == [
                "Confidential Merger Plan"
            ]


@pytest.mark.asyncio
async def test_phase5_e2e_reproducible_ranking_and_semantic_provenance(
    session_factory,
) -> None:
    """Exit Criteria 2 & 3: reproducible ranking and semantic provenance."""
    ws_id = uuid.uuid4()
    prof_id = uuid.uuid4()
    emb = MockDeterministicEmbeddingService(dimension=32)

    async with session_factory() as session:
        approved_rel, draft_rel, entity_survivor = (
            await _seed_governed_semantics(session, ws_id, prof_id)
        )
        indexer = IndexerService(
            session_or_factory=session,
            embedding_service=emb,
            chunker=StructuralChunker(
                ChunkingConfig(target_chars=400, max_chars=500)
            ),
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = LocalStorageProvider(base_path=tmp_dir)
            ingest = IngestionPipeline(
                storage_provider=storage,
                session=session,
                indexer=indexer,
            )
            await ingest.ingest_and_index(
                file_bytes=_make_pdf_bytes(
                    "Global Supervision",
                    (
                        "The Bank for International Settlements acts as a "
                        "Financial Regulator overseeing Tier 1 Capital."
                    ),
                ),
                filename="supervision.pdf",
                mime_type="application/pdf",
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
                security_domain="public",
            )
            await ingest.ingest_and_index(
                file_bytes=_make_docx_bytes(
                    "Capital Buffers",
                    [
                        "Prudential Capital adequacy requires resilient "
                        "Capital Requirements across stress scenarios."
                    ],
                ),
                filename="buffers.docx",
                mime_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
                security_domain="public",
            )

            expansion_service = SemanticQueryExpansionService(
                taxonomy_scheme=_banking_skos_scheme(),
                ontology_expander=OntologyQueryExpander(session),
                entity_expander=EntityQueryExpander(session),
                policy=ExpansionPolicy(max_depth=1, max_expanded_terms=15),
                semantic_profile_id=prof_id,
            )

            def _custom_ce_scorer(
                pairs: List[Tuple[str, str]],
            ) -> Sequence[float]:
                return [
                    3.0 if "Bank for International Settlements" in txt else 0.5
                    for _, txt in pairs
                ]

            pipeline = RetrievalPipeline(
                dense_retriever=PostgresDenseRetriever(session, emb),
                lexical_retriever=PostgresLexicalRetriever(session),
                reranker=CrossEncoderReranker(
                    scorer=_custom_ce_scorer,
                    allow_fallback=False,
                    normalization="sigmoid",
                ),
                expansion_bridge=expansion_service,
            )

            sec_ctx = SecurityContext(
                user_id="auditor",
                allowed_workspaces=[ws_id],
                allowed_security_domains=["public"],
            )
            query = RetrievalQuery(
                query_text="Old Basel Org Central Bank T1 Capital",
                filter=RetrievalFilter(
                    workspace_id=ws_id, security_domains=["public"]
                ),
                top_k=5,
                enable_expansion=True,
            )

            runs = [
                await pipeline.execute(query=query, security_context=sec_ctx)
                for _ in range(3)
            ]

            # Exit Criterion 2: Identical rankings, scores, evidence, & trace
            baseline = runs[0]
            assert len(baseline.ranked_chunks) >= 1
            assert all(0.0 <= c.score <= 1.0 for c in baseline.ranked_chunks)
            for run in runs[1:]:
                assert [c.chunk_id for c in run.ranked_chunks] == [
                    c.chunk_id for c in baseline.ranked_chunks
                ]
                assert [c.score for c in run.ranked_chunks] == [
                    c.score for c in baseline.ranked_chunks
                ]
                assert [
                    (
                        e.chunk_id,
                        e.confidence_score,
                        e.section_path,
                        e.page_numbers,
                    )
                    for e in run.evidence_items
                ] == [
                    (
                        e.chunk_id,
                        e.confidence_score,
                        e.section_path,
                        e.page_numbers,
                    )
                    for e in baseline.evidence_items
                ]
                run_trace = {
                    k: v
                    for k, v in run.execution_metrics[
                        "expansion_trace"
                    ].items()
                    if k != "duration_ms"
                }
                base_trace = {
                    k: v
                    for k, v in baseline.execution_metrics[
                        "expansion_trace"
                    ].items()
                    if k != "duration_ms"
                }
                assert run_trace == base_trace

            # Exit Criterion 3: Complete governed provenance trace
            trace = baseline.execution_metrics["expansion_trace"]
            assert trace["expansion_applied"] is True
            assert set(trace["sources_consulted"]) == {
                "skos",
                "ontology",
                "entity",
            }
            assert str(approved_rel.id) in trace["release_ids"]
            assert str(draft_rel.id) not in trace["release_ids"]

            expanded_terms = {t["term"]: t for t in trace["expanded_terms"]}
            assert "Bank for International Settlements" in expanded_terms
            assert (
                expanded_terms["Bank for International Settlements"][
                    "entity_id"
                ]
                == str(entity_survivor.id)
            )
            assert "Financial Regulator" in expanded_terms
            assert (
                expanded_terms["Financial Regulator"]["release_id"]
                == str(approved_rel.id)
            )
            assert "Tier 1 Capital" in expanded_terms
            assert "DraftSecretConcept" not in expanded_terms
            assert "Unapproved Hallucinated Alias" not in expanded_terms


@pytest.mark.asyncio
async def test_phase5_e2e_recall_gain_and_exact_term_top1_non_regression(
    session_factory,
) -> None:
    """Exit Criterion 4: alias recall gain with zero exact-term regression."""
    ws_id = uuid.uuid4()
    prof_id = uuid.uuid4()
    emb = MockDeterministicEmbeddingService(dimension=32)
    docx_mime = (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    )

    async with session_factory() as session:
        await _seed_governed_semantics(session, ws_id, prof_id)
        indexer = IndexerService(
            session_or_factory=session,
            embedding_service=emb,
            chunker=StructuralChunker(
                ChunkingConfig(target_chars=400, max_chars=500)
            ),
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = LocalStorageProvider(base_path=tmp_dir)
            ingest = IngestionPipeline(
                storage_provider=storage,
                session=session,
                indexer=indexer,
            )

            doc_alias_target = await ingest.ingest_and_index(
                file_bytes=_make_docx_bytes(
                    "Institutional Mandate",
                    [
                        "The Bank for International Settlements acts as a "
                        "Financial Regulator supervising liquidity standards."
                    ],
                ),
                filename="mandate.docx",
                mime_type=docx_mime,
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
                security_domain="public",
            )
            doc_exact_target = await ingest.ingest_and_index(
                file_bytes=_make_docx_bytes(
                    "Control Schedule",
                    [
                        "Control ID ISO-27001-AC-4 enforces T1 Capital ratio "
                        "verification every quarter."
                    ],
                ),
                filename="control.docx",
                mime_type=docx_mime,
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
                security_domain="public",
            )
            await ingest.ingest_and_index(
                file_bytes=_make_docx_bytes(
                    "General Glossary",
                    [
                        "Tier 1 Capital and Core Capital and Capital "
                        "Requirements overview for general reporting."
                    ],
                ),
                filename="glossary.docx",
                mime_type=docx_mime,
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
                security_domain="public",
            )

            expansion_service = SemanticQueryExpansionService(
                taxonomy_scheme=_banking_skos_scheme(),
                ontology_expander=OntologyQueryExpander(session),
                entity_expander=EntityQueryExpander(session),
                policy=ExpansionPolicy(max_depth=1, max_expanded_terms=15),
                semantic_profile_id=prof_id,
            )
            pipeline = RetrievalPipeline(
                dense_retriever=PostgresDenseRetriever(session, emb),
                lexical_retriever=PostgresLexicalRetriever(session),
                reranker=ScoringReranker(),
                expansion_bridge=expansion_service,
            )
            sec_ctx = SecurityContext(
                user_id="analyst",
                allowed_workspaces=[ws_id],
                allowed_security_domains=["public"],
            )

            # 1. Alias query improves lexical recall when expanded
            alias_no_exp = await pipeline.execute(
                query=RetrievalQuery(
                    query_text="Old Basel Org",
                    filter=RetrievalFilter(
                        workspace_id=ws_id, security_domains=["public"]
                    ),
                    top_k=5,
                    enable_dense=False,
                    enable_expansion=False,
                ),
                security_context=sec_ctx,
            )
            alias_with_exp = await pipeline.execute(
                query=RetrievalQuery(
                    query_text="Old Basel Org",
                    filter=RetrievalFilter(
                        workspace_id=ws_id, security_domains=["public"]
                    ),
                    top_k=5,
                    enable_dense=False,
                    enable_expansion=True,
                ),
                security_context=sec_ctx,
            )
            assert (
                alias_no_exp.execution_metrics["lexical_candidate_count"] == 0
            )
            assert alias_no_exp.ranked_chunks == []
            assert (
                alias_with_exp.execution_metrics["lexical_candidate_count"] >= 1
            )
            assert (
                alias_with_exp.ranked_chunks[0].document_version_id
                == doc_alias_target.document_id
            )

            # 2. Exact-term + identifier query preserves rank #1 parity
            exact_no_exp = await pipeline.execute(
                query=RetrievalQuery(
                    query_text="ISO-27001-AC-4 T1 Capital",
                    filter=RetrievalFilter(
                        workspace_id=ws_id, security_domains=["public"]
                    ),
                    top_k=5,
                    enable_expansion=False,
                ),
                security_context=sec_ctx,
            )
            exact_with_exp = await pipeline.execute(
                query=RetrievalQuery(
                    query_text="ISO-27001-AC-4 T1 Capital",
                    filter=RetrievalFilter(
                        workspace_id=ws_id, security_domains=["public"]
                    ),
                    top_k=5,
                    enable_expansion=True,
                ),
                security_context=sec_ctx,
            )
            assert (
                exact_no_exp.ranked_chunks[0].document_version_id
                == doc_exact_target.document_id
            )
            assert (
                exact_with_exp.ranked_chunks[0].document_version_id
                == doc_exact_target.document_id
            )
            assert (
                exact_with_exp.ranked_chunks[0].chunk_id
                == exact_no_exp.ranked_chunks[0].chunk_id
            )
