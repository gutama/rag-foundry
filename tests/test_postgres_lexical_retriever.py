"""Tests for compact-profile PostgresLexicalRetriever (ADR-0004/ADR-0005)."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from rag_foundry.db.models import Base, Chunk, Document
from rag_foundry.db.session import get_sessionmaker
from rag_foundry.retrieval.models import RetrievalFilter, RetrievalQuery
from rag_foundry.retrieval.protocols import LexicalRetrieverProtocol


async def _seed_document(session, workspace_id: uuid.UUID) -> Document:
    """Create and flush a Document row for Chunk foreign-key satisfaction."""
    doc = Document(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        workspace_id=workspace_id,
        title="Compliance Handbook",
        mime_type="application/pdf",
        checksum=uuid.uuid4().hex * 2,
        page_count=5,
        parser_name="native_pdf",
        parser_version="1.0.0",
        semantic_profile_id=uuid.uuid4(),
    )
    session.add(doc)
    await session.flush()
    return doc


def test_postgres_lexical_protocol_conformance() -> None:
    """PostgresLexicalRetriever satisfies LexicalRetrieverProtocol."""
    from rag_foundry.retrieval.postgres_lexical import PostgresLexicalRetriever

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    retriever = PostgresLexicalRetriever(session_or_factory=sessionmaker)
    assert isinstance(retriever, LexicalRetrieverProtocol)


@pytest.mark.asyncio
async def test_postgres_lexical_phrase_token_and_acl_isolation() -> None:
    """Enforces workspace/domain ACL pushdown, phrase boost, and fail-closed."""
    from rag_foundry.retrieval.postgres_lexical import PostgresLexicalRetriever

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        ws_a = uuid.uuid4()
        ws_b = uuid.uuid4()
        doc_a = await _seed_document(session, ws_a)
        doc_b = await _seed_document(session, ws_b)

        c_exact_phrase = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc_a.id,
            workspace_id=ws_a,
            chunk_index=0,
            text="Our zero trust architecture governs retrieval pipelines.",
            section_path=["Security", "Zero Trust"],
            page_numbers=[2],
            bounding_boxes=[
                {"page": 2, "l": 0.1, "t": 0.2, "r": 0.85, "b": 0.35}
            ],
            security_domain="public",
            chunk_metadata={"topic": "security"},
            checksum="a" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=doc_a.semantic_profile_id,
        )
        c_partial_token = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc_a.id,
            workspace_id=ws_a,
            chunk_index=1,
            text="This architecture uses modular parsing with zero downtime.",
            section_path=["Overview"],
            page_numbers=[1],
            security_domain="public",
            chunk_metadata={"topic": "security"},
            checksum="b" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=doc_a.semantic_profile_id,
        )
        c_restricted = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc_a.id,
            workspace_id=ws_a,
            chunk_index=2,
            text="Secret zero trust architecture keys for internal admins.",
            section_path=["Secrets"],
            page_numbers=[3],
            security_domain="restricted_admin",
            chunk_metadata={"topic": "security"},
            checksum="c" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=doc_a.semantic_profile_id,
        )
        c_other_ws = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc_b.id,
            workspace_id=ws_b,
            chunk_index=0,
            text="Zero trust architecture in another tenant workspace.",
            section_path=["Other"],
            page_numbers=[1],
            security_domain="public",
            chunk_metadata={"topic": "security"},
            checksum="d" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=doc_b.semantic_profile_id,
        )
        session.add_all(
            [c_exact_phrase, c_partial_token, c_restricted, c_other_ws]
        )
        await session.commit()

        retriever = PostgresLexicalRetriever(session_or_factory=session)
        results = await retriever.retrieve(
            RetrievalQuery(
                query_text='"zero trust architecture"',
                filter=RetrievalFilter(
                    workspace_id=ws_a,
                    security_domains=["public"],
                ),
                top_k=5,
            )
        )
        # Only authorized workspace/domain matches; exact phrase ranks #1
        assert [r.chunk_id for r in results] == [c_exact_phrase.id]
        assert results[0].lexical_rank == 1
        assert results[0].retrieval_sources == ["lexical"]
        assert results[0].section_path == ["Security", "Zero Trust"]
        assert results[0].page_numbers == [2]
        assert len(results[0].bounding_boxes) == 1

        # Token query matches both authorized chunks with exact phrase higher
        token_results = await retriever.retrieve(
            RetrievalQuery(
                query_text='"zero trust architecture" OR architecture',
                filter=RetrievalFilter(
                    workspace_id=ws_a,
                    security_domains=["public"],
                ),
                top_k=5,
            )
        )
        assert [r.chunk_id for r in token_results] == [
            c_exact_phrase.id,
            c_partial_token.id,
        ]
        assert token_results[0].score > token_results[1].score

        # Fail closed when security_domains is empty
        closed_results = await retriever.retrieve(
            RetrievalQuery(
                query_text="zero trust architecture",
                filter=RetrievalFilter(
                    workspace_id=ws_a,
                    security_domains=[],
                ),
                top_k=5,
            )
        )
        assert closed_results == []


@pytest.mark.asyncio
async def test_postgres_lexical_doc_metadata_filters_and_tie_breaking() -> None:
    """Supports document_ids, metadata_filters, min_score, and chunk_id ties."""
    from rag_foundry.retrieval.postgres_lexical import PostgresLexicalRetriever

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        ws = uuid.uuid4()
        doc1 = await _seed_document(session, ws)
        doc2 = await _seed_document(session, ws)

        id_a = uuid.UUID("00000000-0000-0000-0000-00000000000a")
        id_b = uuid.UUID("00000000-0000-0000-0000-00000000000b")
        id_doc2 = uuid.UUID("00000000-0000-0000-0000-00000000000c")

        session.add_all(
            [
                Chunk(
                    id=id_b,
                    document_version_id=doc1.id,
                    workspace_id=ws,
                    chunk_index=0,
                    text="Identical compliance audit policy text.",
                    security_domain="general",
                    chunk_metadata={"dept": "audit"},
                    checksum="1" * 64,
                    chunker_name="structural",
                    chunker_version="1.0.0",
                    semantic_profile_id=doc1.semantic_profile_id,
                ),
                Chunk(
                    id=id_a,
                    document_version_id=doc1.id,
                    workspace_id=ws,
                    chunk_index=1,
                    text="Identical compliance audit policy text.",
                    security_domain="general",
                    chunk_metadata={"dept": "audit"},
                    checksum="2" * 64,
                    chunker_name="structural",
                    chunker_version="1.0.0",
                    semantic_profile_id=doc1.semantic_profile_id,
                ),
                Chunk(
                    id=id_doc2,
                    document_version_id=doc2.id,
                    workspace_id=ws,
                    chunk_index=0,
                    text="Identical compliance audit policy text.",
                    security_domain="general",
                    chunk_metadata={"dept": "finance"},
                    checksum="3" * 64,
                    chunker_name="structural",
                    chunker_version="1.0.0",
                    semantic_profile_id=doc2.semantic_profile_id,
                ),
            ]
        )
        await session.commit()

        retriever = PostgresLexicalRetriever(session_or_factory=session)
        results = await retriever.retrieve(
            RetrievalQuery(
                query_text="compliance audit",
                filter=RetrievalFilter(
                    workspace_id=ws,
                    document_ids=[doc1.id],
                    security_domains=["general"],
                    metadata_filters={"dept": "audit"},
                ),
                top_k=5,
            )
        )
        assert [r.chunk_id for r in results] == [id_a, id_b]
        assert [r.lexical_rank for r in results] == [1, 2]

        # Explicit empty document_ids whitelist returns []
        empty_doc_res = await retriever.retrieve(
            RetrievalQuery(
                query_text="compliance",
                filter=RetrievalFilter(
                    workspace_id=ws,
                    document_ids=[],
                    security_domains=["general"],
                ),
                top_k=5,
            )
        )
        assert empty_doc_res == []


def test_postgres_lexical_compiles_fts_sql_with_acl_pushdown() -> None:
    """PostgreSQL FTS query pushes ACL predicates before ts_rank_cd ORDER BY."""
    from rag_foundry.retrieval.postgres_lexical import PostgresLexicalRetriever

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    retriever = PostgresLexicalRetriever(session_or_factory=sessionmaker)

    ws_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    query = RetrievalQuery(
        query_text='"data governance" policy',
        filter=RetrievalFilter(
            workspace_id=ws_id,
            document_ids=[doc_id],
            security_domains=["public", "governance"],
            metadata_filters={"region": "eu"},
        ),
        top_k=8,
    )
    stmt = retriever.build_postgresql_query(query)
    assert stmt is not None

    sql = str(stmt.compile(dialect=postgresql.dialect()))
    where_idx = sql.index("WHERE")
    order_idx = sql.index("ORDER BY")
    limit_idx = sql.index("LIMIT")
    assert where_idx < order_idx < limit_idx

    where_clause = sql[where_idx:order_idx]
    order_clause = sql[order_idx:limit_idx]
    assert "chunks.workspace_id" in where_clause
    assert "chunks.security_domain IN" in where_clause
    assert "chunks.document_version_id IN" in where_clause
    assert "chunks.chunk_metadata" in where_clause
    assert "websearch_to_tsquery" in where_clause
    assert "@@" in where_clause
    assert "to_tsvector" in where_clause
    assert "ts_rank_cd" in sql
    assert "chunks.id ASC" in order_clause

    # Empty security domains fails closed
    closed_stmt = retriever.build_postgresql_query(
        RetrievalQuery(
            query_text="governance",
            filter=RetrievalFilter(workspace_id=ws_id, security_domains=[]),
        )
    )
    assert closed_stmt is None


@pytest.mark.asyncio
async def test_postgres_lexical_postgresql_execution_path() -> None:
    """PostgreSQL dialect branch normalizes ts_rank_cd scores and filters."""
    from rag_foundry.retrieval.postgres_lexical import PostgresLexicalRetriever

    ws_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    c1 = Chunk(
        id=uuid.UUID("00000000-0000-0000-0000-000000000101"),
        document_version_id=doc_id,
        workspace_id=ws_id,
        chunk_index=0,
        text="High rank lexical hit",
        security_domain="public",
        chunk_metadata={},
        checksum="m" * 64,
        chunker_name="structural",
        chunker_version="1.0.0",
        semantic_profile_id=uuid.uuid4(),
    )
    c2 = Chunk(
        id=uuid.UUID("00000000-0000-0000-0000-000000000102"),
        document_version_id=doc_id,
        workspace_id=ws_id,
        chunk_index=1,
        text="Low rank lexical hit",
        security_domain="public",
        chunk_metadata={},
        checksum="n" * 64,
        chunker_name="structural",
        chunker_version="1.0.0",
        semantic_profile_id=uuid.uuid4(),
    )

    class _FakePgResult:
        def all(self):
            return [(c1, 0.8), (c2, 0.05)]

    class _FakePgSession:
        def __init__(self) -> None:
            self.executed: list = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get_bind(self):
            return SimpleNamespace(dialect=postgresql.dialect())

        async def execute(self, stmt):
            self.executed.append(stmt)
            return _FakePgResult()

    fake = _FakePgSession()
    retriever = PostgresLexicalRetriever(
        session_or_factory=lambda: fake  # type: ignore[arg-type]
    )
    res = await retriever.retrieve(
        RetrievalQuery(
            query_text="lexical hit",
            filter=RetrievalFilter(
                workspace_id=ws_id,
                security_domains=["public"],
            ),
            top_k=5,
            min_relevance_score=0.5,
        )
    )
    assert len(fake.executed) == 1
    assert [r.chunk_id for r in res] == [c1.id]
    assert 0.5 <= res[0].score <= 1.0
    assert res[0].lexical_rank == 1


def test_postgres_lexical_expanded_or_match_and_metadata_parity() -> None:
    """Expanded PG FTS ORs original tsquery; metadata filters match exactly."""
    from rag_foundry.retrieval.postgres_filters import matches_metadata_filters
    from rag_foundry.retrieval.postgres_lexical import PostgresLexicalRetriever

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    retriever = PostgresLexicalRetriever(session_or_factory=sessionmaker)
    ws_id = uuid.uuid4()

    # Finding 4: expanded query must OR original websearch_to_tsquery into
    # WHERE so non-contiguous original-query hits are never dropped on PG.
    expanded_q = RetrievalQuery(
        query_text='revenue recognition policy for subsidiaries OR "IFRS 15"',
        original_query_text="revenue recognition policy for subsidiaries",
        expanded_term_weights={"ifrs 15": 0.7},
        filter=RetrievalFilter(
            workspace_id=ws_id,
            security_domains=["public"],
            metadata_filters={"tags": ["finance"], "classification": None},
        ),
        top_k=5,
    )
    stmt = retriever.build_postgresql_query(expanded_q)
    assert stmt is not None
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    where_clause = sql[sql.index("WHERE") : sql.index("ORDER BY")]

    # Both original and expanded websearch_to_tsquery appear in WHERE @@ match
    assert where_clause.count("websearch_to_tsquery") >= 4
    assert "chunks.search_vector @@ websearch_to_tsquery" in where_clause
    assert "->" in where_clause
    assert "@>" not in where_clause

    # Finding 10: exact metadata filter parity with PostgreSQL JSONB '='
    assert matches_metadata_filters(
        {"tags": ["finance"]}, {"tags": ["finance"]}
    )
    assert not matches_metadata_filters(
        {"tags": ["finance", "hr"]}, {"tags": ["finance"]}
    )
    assert not matches_metadata_filters(
        {"nested": {"a": 1, "b": 2}}, {"nested": {"a": 1}}
    )
    assert matches_metadata_filters(
        {"classification": None}, {"classification": None}
    )
    assert not matches_metadata_filters({}, {"classification": None})
    assert not matches_metadata_filters({"flag": 1}, {"flag": True})
    assert matches_metadata_filters({"flag": True}, {"flag": True})
