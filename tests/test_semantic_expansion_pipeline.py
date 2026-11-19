"""Tests for unified SemanticQueryExpansionService and exact-term protection."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

from rag_foundry.db.models import (
    Base,
    Chunk,
    Document,
    EntityRecord,
    OntologyClassRecord,
    OntologyReleaseRecord,
)
from rag_foundry.db.session import get_sessionmaker
from rag_foundry.retrieval.embeddings import MockDeterministicEmbeddingService
from rag_foundry.retrieval.expansion import TaxonomyExpansionBridge
from rag_foundry.retrieval.lexical import LexicalRecord, LexicalRetriever
from rag_foundry.retrieval.models import RetrievalFilter, RetrievalQuery
from rag_foundry.retrieval.ontology_expansion import (
    EntityQueryExpander,
    ExpansionPolicy,
    OntologyQueryExpander,
)
from rag_foundry.retrieval.pipeline import RetrievalPipeline
from rag_foundry.retrieval.postgres_dense import PostgresDenseRetriever
from rag_foundry.retrieval.postgres_lexical import PostgresLexicalRetriever
from rag_foundry.retrieval.security import SecurityContext
from rag_foundry.taxonomy.models import (
    SKOSConceptModel,
    SKOSConceptSchemeModel,
)


def _banking_skos_scheme() -> SKOSConceptSchemeModel:
    """Build a small SKOS taxonomy scheme for banking capital terminology."""
    scheme_uri = "urn:scheme:banking"
    return SKOSConceptSchemeModel(
        scheme_id=str(uuid.uuid4()),
        uri=scheme_uri,
        title="Banking Taxonomy",
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


async def _seed_semantic_workspace(session):
    """Seed document, chunks, approved ontology, and workspace entity."""
    ws_id = uuid.uuid4()
    prof_id = uuid.uuid4()
    doc = Document(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        workspace_id=ws_id,
        title="Prudential Supervision Policy",
        mime_type="application/pdf",
        checksum="d" * 64,
        page_count=3,
        parser_name="native_pdf",
        parser_version="1.0.0",
        semantic_profile_id=prof_id,
    )
    release = OntologyReleaseRecord(
        id=uuid.uuid4(),
        ontology_uri="https://example.org/onto/supervision",
        version="1.0.0",
        title="Supervision Ontology",
        status="approved",
        published_at=datetime.now(timezone.utc),
    )
    session.add_all([doc, release])
    await session.flush()

    cls_regulator = OntologyClassRecord(
        release_id=release.id,
        uri="https://example.org/onto/FinancialRegulator",
        preferred_labels={"en": "Financial Regulator"},
        parent_class_uris=[],
        status="active",
    )
    cls_cb = OntologyClassRecord(
        release_id=release.id,
        uri="https://example.org/onto/CentralBank",
        preferred_labels={"en": "Central Bank"},
        parent_class_uris=["https://example.org/onto/FinancialRegulator"],
        status="active",
    )
    entity_bis = EntityRecord(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        semantic_profile_id=prof_id,
        canonical_uri="urn:entity:bis",
        ontology_class_uri="https://example.org/onto/FinancialRegulator",
        preferred_labels={"en": "Bank for International Settlements"},
        aliases={"en": ["BIS Basel", "Basel Committee"]},
        status="active",
    )
    session.add_all([cls_regulator, cls_cb, entity_bis])
    await session.flush()

    return ws_id, prof_id, doc, release, entity_bis


@pytest.mark.asyncio
async def test_semantic_expansion_service_composes_skos_ontology_entity() -> (
    None
):
    """Service merges SKOS, ontology, and entity expansions with trace."""
    from rag_foundry.retrieval.expansion import SemanticQueryExpansionService

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        ws_id, prof_id, _, release, entity_bis = (
            await _seed_semantic_workspace(session)
        )
        await session.commit()

        service = SemanticQueryExpansionService(
            taxonomy_scheme=_banking_skos_scheme(),
            ontology_expander=OntologyQueryExpander(session),
            entity_expander=EntityQueryExpander(session),
            policy=ExpansionPolicy(max_depth=1, max_expanded_terms=15),
            semantic_profile_id=prof_id,
        )
        sec_ctx = SecurityContext(
            user_id="analyst",
            allowed_workspaces=[ws_id],
            allowed_security_domains=["public"],
        )
        query = RetrievalQuery(
            query_text="BIS Basel Central Bank T1 Capital",
            filter=RetrievalFilter(
                workspace_id=ws_id, security_domains=["public"]
            ),
            enable_expansion=True,
        )
        expanded_q, trace = await service.expand_retrieval_query(
            query, security_context=sec_ctx
        )

        assert trace["expansion_applied"] is True
        assert set(trace["sources_consulted"]) == {
            "skos",
            "ontology",
            "entity",
        }
        assert str(release.id) in trace["release_ids"]
        assert expanded_q.original_query_text == query.query_text
        assert len(expanded_q.expanded_term_weights) >= 3

        by_term = {t["term"]: t for t in trace["expanded_terms"]}
        assert "Tier 1 Capital" in by_term
        assert by_term["Tier 1 Capital"]["source_type"] == "skos_concept"
        assert (
            by_term["Tier 1 Capital"]["source_uri"]
            == "urn:concept:tier1_capital"
        )
        assert "Financial Regulator" in by_term
        assert by_term["Financial Regulator"]["source_type"] == "ontology_class"
        assert by_term["Financial Regulator"]["release_id"] == str(release.id)
        assert "Bank for International Settlements" in by_term
        assert (
            by_term["Bank for International Settlements"]["entity_id"]
            == str(entity_bis.id)
        )


@pytest.mark.asyncio
async def test_pipeline_recall_gain_and_exact_term_top1_non_regression() -> (
    None
):
    """Expansion boosts alias/hierarchy recall without hurting exact-term #1."""
    from rag_foundry.retrieval.expansion import SemanticQueryExpansionService

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        ws_id, prof_id, doc, release, _ = await _seed_semantic_workspace(
            session
        )

        emb = MockDeterministicEmbeddingService(dimension=16)

        # Chunk 1: contains canonical entity + superclass (no 'BIS Basel' alias)
        c_recall = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc.id,
            workspace_id=ws_id,
            chunk_index=0,
            text=(
                "The Bank for International Settlements acts as a Financial "
                "Regulator coordinating global liquidity."
            ),
            security_domain="public",
            embedding=emb.embed_query(
                "The Bank for International Settlements acts as a Financial "
                "Regulator coordinating global liquidity."
            ),
            checksum="1" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=prof_id,
        )
        # Chunk 2: exact match for 'T1 Capital' and identifier 'ISO-27001-AC-4'
        c_exact = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc.id,
            workspace_id=ws_id,
            chunk_index=1,
            text=(
                "Clause ISO-27001-AC-4 mandates T1 Capital monitoring every "
                "quarter."
            ),
            security_domain="public",
            embedding=emb.embed_query(
                "Clause ISO-27001-AC-4 mandates T1 Capital monitoring every "
                "quarter."
            ),
            checksum="2" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=prof_id,
        )
        # Chunk 3: stuffed with expanded synonyms ONLY, no exact 'T1 Capital'
        c_synonyms_only = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc.id,
            workspace_id=ws_id,
            chunk_index=2,
            text=(
                "Tier 1 Capital, Core Capital, Capital Requirements, and "
                "Prudential Capital standards apply globally."
            ),
            security_domain="public",
            embedding=emb.embed_query(
                "Tier 1 Capital, Core Capital, Capital Requirements, and "
                "Prudential Capital standards apply globally."
            ),
            checksum="3" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=prof_id,
        )
        session.add_all([c_recall, c_exact, c_synonyms_only])
        await session.commit()

        expansion_service = SemanticQueryExpansionService(
            taxonomy_scheme=_banking_skos_scheme(),
            ontology_expander=OntologyQueryExpander(session),
            entity_expander=EntityQueryExpander(session),
            semantic_profile_id=prof_id,
        )
        dense = PostgresDenseRetriever(session, emb)
        lexical = PostgresLexicalRetriever(session)
        pipeline = RetrievalPipeline(
            dense_retriever=dense,
            lexical_retriever=lexical,
            expansion_bridge=expansion_service,
        )
        sec_ctx = SecurityContext(
            user_id="analyst",
            allowed_workspaces=[ws_id],
            allowed_security_domains=["public"],
        )

        # 1. Alias query gains lexical recall via entity expansion
        alias_res_off = await pipeline.execute(
            RetrievalQuery(
                query_text="BIS Basel",
                filter=RetrievalFilter(
                    workspace_id=ws_id, security_domains=["public"]
                ),
                enable_dense=False,
                enable_lexical=True,
                enable_expansion=False,
            ),
            security_context=sec_ctx,
        )
        assert alias_res_off.ranked_chunks == []

        alias_res_on = await pipeline.execute(
            RetrievalQuery(
                query_text="BIS Basel",
                filter=RetrievalFilter(
                    workspace_id=ws_id, security_domains=["public"]
                ),
                enable_dense=False,
                enable_lexical=True,
                enable_expansion=True,
            ),
            security_context=sec_ctx,
        )
        assert [c.chunk_id for c in alias_res_on.ranked_chunks] == [
            c_recall.id
        ]
        assert (
            alias_res_on.execution_metrics["expansion_trace"][
                "expansion_applied"
            ]
            is True
        )

        # 2. Exact-term non-regression: 'T1 Capital' MUST keep c_exact at #1
        # even though c_synonyms_only matches 4 expanded synonyms!
        exact_off = await pipeline.execute(
            RetrievalQuery(
                query_text="T1 Capital",
                filter=RetrievalFilter(
                    workspace_id=ws_id, security_domains=["public"]
                ),
                enable_expansion=False,
            ),
            security_context=sec_ctx,
        )
        exact_on = await pipeline.execute(
            RetrievalQuery(
                query_text="T1 Capital",
                filter=RetrievalFilter(
                    workspace_id=ws_id, security_domains=["public"]
                ),
                enable_expansion=True,
            ),
            security_context=sec_ctx,
        )
        assert exact_off.ranked_chunks[0].chunk_id == c_exact.id
        assert exact_on.ranked_chunks[0].chunk_id == c_exact.id
        # Recall also increases: c_synonyms_only is now recalled below c_exact
        recalled_ids = [c.chunk_id for c in exact_on.ranked_chunks]
        assert c_synonyms_only.id in recalled_ids

        # 3. Exact identifier query preserves top-1 parity
        id_off = await pipeline.execute(
            RetrievalQuery(
                query_text="ISO-27001-AC-4",
                filter=RetrievalFilter(
                    workspace_id=ws_id, security_domains=["public"]
                ),
                enable_expansion=False,
            ),
            security_context=sec_ctx,
        )
        id_on = await pipeline.execute(
            RetrievalQuery(
                query_text="ISO-27001-AC-4",
                filter=RetrievalFilter(
                    workspace_id=ws_id, security_domains=["public"]
                ),
                enable_expansion=True,
            ),
            security_context=sec_ctx,
        )
        assert id_off.ranked_chunks[0].chunk_id == c_exact.id
        assert id_on.ranked_chunks[0].chunk_id == c_exact.id

        # 4. Direct PostgresLexicalRetriever ranking also keeps c_exact at #1
        exp_q, _ = await expansion_service.expand_retrieval_query(
            RetrievalQuery(
                query_text="T1 Capital",
                filter=RetrievalFilter(
                    workspace_id=ws_id, security_domains=["public"]
                ),
            ),
            security_context=sec_ctx,
        )
        direct_pg_hits = await lexical.retrieve(exp_q)
        assert direct_pg_hits[0].chunk_id == c_exact.id

        # 5. PostgreSQL FTS query with original_query_text boosts exact match
        pg_sql = str(
            lexical.build_postgresql_query(exp_q).compile(
                dialect=postgresql.dialect()
            )
        )
        assert pg_sql.count("ts_rank_cd") >= 2


@pytest.mark.asyncio
async def test_legacy_taxonomy_bridge_and_inmemory_lexical_exact_protection() -> (
    None
):
    """Legacy TaxonomyExpansionBridge & LexicalRetriever protect exact hits."""
    ws_id = uuid.uuid4()
    c_exact_id = uuid.uuid4()
    c_syn_id = uuid.uuid4()

    lexical = LexicalRetriever()
    await lexical.index_records(
        [
            LexicalRecord(
                chunk_id=c_exact_id,
                workspace_id=ws_id,
                text="T1 Capital requirement is 6 percent.",
                security_domain="public",
            ),
            LexicalRecord(
                chunk_id=c_syn_id,
                workspace_id=ws_id,
                text=(
                    "Tier 1 Capital, Core Capital, and Capital Requirements "
                    "are defined in Basel III."
                ),
                security_domain="public",
            ),
        ]
    )

    bridge = TaxonomyExpansionBridge(scheme=_banking_skos_scheme())
    raw_query = RetrievalQuery(
        query_text="T1 Capital",
        filter=RetrievalFilter(
            workspace_id=ws_id, security_domains=["public"]
        ),
        enable_dense=False,
        enable_lexical=True,
        enable_expansion=True,
    )

    # Direct LexicalRetriever ranking must keep exact match #1 above synonyms
    expanded_q, _ = bridge.expand_retrieval_query(raw_query)
    direct_hits = await lexical.retrieve(expanded_q)
    assert direct_hits[0].chunk_id == c_exact_id
    assert c_syn_id in [c.chunk_id for c in direct_hits]

    pipeline = RetrievalPipeline(
        lexical_retriever=lexical,
        expansion_bridge=bridge,
    )
    res = await pipeline.execute(raw_query)
    assert res.ranked_chunks[0].chunk_id == c_exact_id
    assert res.execution_metrics["expansion_trace"]["expansion_applied"] is True


@pytest.mark.asyncio
async def test_semantic_expansion_service_authorization_and_disabled() -> None:
    """Service enforces authorization before DB access and handles disabled."""
    from rag_foundry.retrieval.expansion import SemanticQueryExpansionService
    from rag_foundry.retrieval.security import SecurityAuthorizationError

    ws_id = uuid.uuid4()
    other_ws = uuid.uuid4()

    class _ExplodingFactory:
        def __call__(self):
            raise AssertionError("Semantic store must not be queried.")

    exploding: object = _ExplodingFactory()
    service = SemanticQueryExpansionService(
        taxonomy_scheme=_banking_skos_scheme(),
        ontology_expander=OntologyQueryExpander(exploding),  # type: ignore[arg-type]
        entity_expander=EntityQueryExpander(exploding),  # type: ignore[arg-type]
    )

    # 1. Disabled expansion skips all semantic stores
    disabled_q = RetrievalQuery(
        query_text="T1 Capital",
        filter=RetrievalFilter(workspace_id=ws_id, security_domains=["public"]),
        enable_expansion=False,
    )
    out_q, trace = await service.expand_retrieval_query(disabled_q)
    assert out_q.query_text == "T1 Capital"
    assert trace["expansion_applied"] is False
    assert trace["reason"] == "disabled"

    # 2. Unauthorized workspace raises before querying stores
    unauth_ctx = SecurityContext(
        user_id="intruder",
        allowed_workspaces=[other_ws],
        allowed_security_domains=["public"],
    )
    active_q = RetrievalQuery(
        query_text="T1 Capital",
        filter=RetrievalFilter(workspace_id=ws_id, security_domains=["public"]),
        enable_expansion=True,
    )
    with pytest.raises(SecurityAuthorizationError):
        await service.expand_retrieval_query(
            active_q, security_context=unauth_ctx
        )

    # 3. Empty allowed security domains fails closed before querying stores
    empty_dom_ctx = SecurityContext(
        user_id="restricted",
        allowed_workspaces=[ws_id],
        allowed_security_domains=[],
    )
    closed_q, closed_trace = await service.expand_retrieval_query(
        active_q, security_context=empty_dom_ctx
    )
    assert closed_q.query_text == "T1 Capital"
    assert closed_trace["expansion_applied"] is False
    assert closed_trace["reason"] == "no_allowed_security_domains"
    assert closed_trace["sources_consulted"] == []

