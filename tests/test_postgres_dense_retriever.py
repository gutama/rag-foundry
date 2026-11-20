"""Tests for retriever protocols and compact-profile PostgresDenseRetriever."""

import uuid
from typing import List

import pytest
from sqlalchemy.dialects import postgresql

from rag_foundry.db.models import Base, Chunk, Document
from rag_foundry.db.session import get_sessionmaker
from rag_foundry.retrieval.dense import DenseVectorRetriever
from rag_foundry.retrieval.embeddings import (
    EmbeddingService,
    MockDeterministicEmbeddingService,
)
from rag_foundry.retrieval.lexical import LexicalRetriever
from rag_foundry.retrieval.models import RetrievalFilter, RetrievalQuery


class _StaticEmbeddingService(EmbeddingService):
    """Fixed-vector embedding stub for deterministic cosine similarity tests."""

    def __init__(self, vectors: dict[str, List[float]], dim: int = 4) -> None:
        self._vectors = vectors
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_query(self, text: str) -> List[float]:
        return self._vectors[text]

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [self._vectors[t] for t in texts]


async def _seed_document(session, workspace_id: uuid.UUID) -> Document:
    """Create and flush a Document row for Chunk foreign-key satisfaction."""
    doc = Document(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        workspace_id=workspace_id,
        title="Governance Policy",
        mime_type="application/pdf",
        checksum=uuid.uuid4().hex * 2,
        page_count=4,
        parser_name="native_pdf",
        parser_version="1.0.0",
        semantic_profile_id=uuid.uuid4(),
    )
    session.add(doc)
    await session.flush()
    return doc


def test_retriever_protocols_conformance() -> None:
    """In-memory and DB retrievers satisfy runtime-checkable protocols."""
    from rag_foundry.retrieval.postgres_dense import PostgresDenseRetriever
    from rag_foundry.retrieval.protocols import (
        DenseRetrieverProtocol,
        LexicalRetrieverProtocol,
    )

    emb = MockDeterministicEmbeddingService(dimension=8)
    in_mem_dense = DenseVectorRetriever(embedding_service=emb)
    in_mem_lexical = LexicalRetriever()

    assert isinstance(in_mem_dense, DenseRetrieverProtocol)
    assert isinstance(in_mem_lexical, LexicalRetrieverProtocol)

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    pg_dense = PostgresDenseRetriever(
        session_or_factory=sessionmaker,
        embedding_service=emb,
    )
    assert isinstance(pg_dense, DenseRetrieverProtocol)


@pytest.mark.asyncio
async def test_postgres_dense_workspace_and_security_domain_isolation() -> None:
    """Only chunks matching workspace_id and allowed security_domains return."""
    from rag_foundry.retrieval.postgres_dense import PostgresDenseRetriever

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        ws_a = uuid.uuid4()
        ws_b = uuid.uuid4()
        doc_a = await _seed_document(session, ws_a)
        doc_b = await _seed_document(session, ws_b)

        c_allowed = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc_a.id,
            workspace_id=ws_a,
            chunk_index=0,
            text="Authorized public governance chunk.",
            section_path=["Governance"],
            page_numbers=[1],
            bounding_boxes=[
                {"page": 1, "l": 0.1, "t": 0.1, "r": 0.9, "b": 0.25}
            ],
            security_domain="public",
            chunk_metadata={"region": "us"},
            embedding=[1.0, 0.0, 0.0, 0.0],
            embedding_model="stub",
            embedding_dim=4,
            checksum="a" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=doc_a.semantic_profile_id,
        )
        c_restricted = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc_a.id,
            workspace_id=ws_a,
            chunk_index=1,
            text="Restricted executive compensation chunk.",
            section_path=["Restricted"],
            page_numbers=[2],
            security_domain="executive_secret",
            chunk_metadata={"region": "us"},
            embedding=[1.0, 0.0, 0.0, 0.0],
            embedding_model="stub",
            embedding_dim=4,
            checksum="b" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=doc_a.semantic_profile_id,
        )
        c_other_ws = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc_b.id,
            workspace_id=ws_b,
            chunk_index=0,
            text="Other workspace public chunk.",
            section_path=["Other"],
            page_numbers=[1],
            security_domain="public",
            chunk_metadata={"region": "us"},
            embedding=[1.0, 0.0, 0.0, 0.0],
            embedding_model="stub",
            embedding_dim=4,
            checksum="c" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=doc_b.semantic_profile_id,
        )
        session.add_all([c_allowed, c_restricted, c_other_ws])
        await session.commit()

        emb = _StaticEmbeddingService({"q": [1.0, 0.0, 0.0, 0.0]})
        retriever = PostgresDenseRetriever(
            session_or_factory=session,
            embedding_service=emb,
            embedding_model_name="stub",
        )

        results = await retriever.retrieve(
            RetrievalQuery(
                query_text="q",
                filter=RetrievalFilter(
                    workspace_id=ws_a,
                    security_domains=["public"],
                ),
                top_k=5,
            )
        )
        assert [r.chunk_id for r in results] == [c_allowed.id]
        assert results[0].score == 1.0
        assert results[0].dense_rank == 1
        assert results[0].retrieval_sources == ["dense"]
        assert results[0].section_path == ["Governance"]
        assert results[0].page_numbers == [1]
        assert len(results[0].bounding_boxes) == 1
        assert results[0].bounding_boxes[0].page == 1

        # Fail closed when allowed security_domains is empty
        empty_results = await retriever.retrieve(
            RetrievalQuery(
                query_text="q",
                filter=RetrievalFilter(
                    workspace_id=ws_a,
                    security_domains=[],
                ),
                top_k=5,
            )
        )
        assert empty_results == []


@pytest.mark.asyncio
async def test_postgres_dense_document_metadata_filters_and_tie_breaking() -> (
    None
):
    """Supports document_ids, metadata_filters, min score, and chunk_id ties."""
    from rag_foundry.retrieval.postgres_dense import PostgresDenseRetriever

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        ws = uuid.uuid4()
        doc1 = await _seed_document(session, ws)
        doc2 = await _seed_document(session, ws)

        id_low = uuid.UUID("00000000-0000-0000-0000-000000000001")
        id_high = uuid.UUID("00000000-0000-0000-0000-000000000002")
        id_orthogonal = uuid.UUID("00000000-0000-0000-0000-000000000003")
        id_doc2 = uuid.UUID("00000000-0000-0000-0000-000000000004")

        chunks = [
            Chunk(
                id=id_high,
                document_version_id=doc1.id,
                workspace_id=ws,
                chunk_index=0,
                text="Tie chunk B",
                security_domain="general",
                chunk_metadata={"category": "policy", "year": 2026},
                embedding=[1.0, 0.0, 0.0, 0.0],
                embedding_model="_StaticEmbeddingService",
                embedding_dim=4,
                checksum="1" * 64,
                chunker_name="structural",
                chunker_version="1.0.0",
                semantic_profile_id=doc1.semantic_profile_id,
            ),
            Chunk(
                id=id_low,
                document_version_id=doc1.id,
                workspace_id=ws,
                chunk_index=1,
                text="Tie chunk A",
                security_domain="general",
                chunk_metadata={"category": "policy", "year": 2026},
                embedding=[1.0, 0.0, 0.0, 0.0],
                embedding_model="_StaticEmbeddingService",
                embedding_dim=4,
                checksum="2" * 64,
                chunker_name="structural",
                chunker_version="1.0.0",
                semantic_profile_id=doc1.semantic_profile_id,
            ),
            Chunk(
                id=id_orthogonal,
                document_version_id=doc1.id,
                workspace_id=ws,
                chunk_index=2,
                text="Orthogonal chunk",
                security_domain="general",
                chunk_metadata={"category": "policy", "year": 2026},
                embedding=[0.0, 1.0, 0.0, 0.0],
                embedding_model="_StaticEmbeddingService",
                embedding_dim=4,
                checksum="3" * 64,
                chunker_name="structural",
                chunker_version="1.0.0",
                semantic_profile_id=doc1.semantic_profile_id,
            ),
            Chunk(
                id=id_doc2,
                document_version_id=doc2.id,
                workspace_id=ws,
                chunk_index=0,
                text="Other document chunk",
                security_domain="general",
                chunk_metadata={"category": "memo", "year": 2026},
                embedding=[1.0, 0.0, 0.0, 0.0],
                embedding_model="_StaticEmbeddingService",
                embedding_dim=4,
                checksum="4" * 64,
                chunker_name="structural",
                chunker_version="1.0.0",
                semantic_profile_id=doc2.semantic_profile_id,
            ),
            Chunk(
                id=uuid.uuid4(),
                document_version_id=doc1.id,
                workspace_id=ws,
                chunk_index=3,
                text="Unembedded chunk should be skipped",
                security_domain="general",
                chunk_metadata={"category": "policy", "year": 2026},
                embedding=None,
                checksum="5" * 64,
                chunker_name="structural",
                chunker_version="1.0.0",
                semantic_profile_id=doc1.semantic_profile_id,
            ),
        ]
        session.add_all(chunks)
        await session.commit()

        emb = _StaticEmbeddingService({"q": [1.0, 0.0, 0.0, 0.0]})
        retriever = PostgresDenseRetriever(
            session_or_factory=session, embedding_service=emb
        )

        # Deterministic tie-breaking puts id_low before id_high
        res = await retriever.retrieve(
            RetrievalQuery(
                query_text="q",
                filter=RetrievalFilter(
                    workspace_id=ws,
                    document_ids=[doc1.id],
                    security_domains=["general"],
                    metadata_filters={"category": "policy"},
                ),
                top_k=10,
                min_relevance_score=0.6,
            )
        )
        assert [r.chunk_id for r in res] == [id_low, id_high]
        assert [r.dense_rank for r in res] == [1, 2]

        # Explicit empty document_ids whitelist returns empty list
        res_empty_docs = await retriever.retrieve(
            RetrievalQuery(
                query_text="q",
                filter=RetrievalFilter(
                    workspace_id=ws,
                    document_ids=[],
                    security_domains=["general"],
                ),
                top_k=5,
            )
        )
        assert res_empty_docs == []


def test_postgres_dense_compiles_pgvector_sql_with_acl_pushdown() -> None:
    """PostgreSQL query pushes ACL & model WHERE before <=> ORDER BY/LIMIT."""
    from rag_foundry.retrieval.postgres_dense import PostgresDenseRetriever

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    emb = MockDeterministicEmbeddingService(dimension=4)
    retriever = PostgresDenseRetriever(
        session_or_factory=sessionmaker,
        embedding_service=emb,
        embedding_model_name="bge-small",
    )

    ws_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    query = RetrievalQuery(
        query_text="pgvector query",
        filter=RetrievalFilter(
            workspace_id=ws_id,
            document_ids=[doc_id],
            security_domains=["public", "finance"],
            metadata_filters={"region": "eu", "classification": None},
        ),
        top_k=7,
    )
    stmt = retriever.build_postgresql_query(query, [0.5, 0.5, 0.5, 0.5])
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
    assert "chunks.embedding IS NOT NULL" in where_clause
    assert "chunks.embedding_model" in where_clause
    assert "chunks.embedding_dim" in where_clause
    # Exact per-key JSONB equality (not @> containment)
    assert "->" in where_clause
    assert "@>" not in where_clause
    assert "<=>" in order_clause
    assert "chunks.id ASC" in order_clause

    # Empty security domains fails closed and builds no SQL statement
    empty_stmt = retriever.build_postgresql_query(
        RetrievalQuery(
            query_text="pgvector query",
            filter=RetrievalFilter(workspace_id=ws_id, security_domains=[]),
        ),
        [0.5, 0.5, 0.5, 0.5],
    )
    assert empty_stmt is None


@pytest.mark.asyncio
async def test_postgres_dense_postgresql_execution_path_and_sessionmaker() -> (
    None
):
    """PostgreSQL branch sets HNSW iterative_scan and converts <=> distances."""
    from types import SimpleNamespace

    from rag_foundry.retrieval.postgres_dense import PostgresDenseRetriever

    ws_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    c1 = Chunk(
        id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
        document_version_id=doc_id,
        workspace_id=ws_id,
        chunk_index=0,
        text="High similarity PostgreSQL chunk",
        section_path=["Sec"],
        page_numbers=[1],
        bounding_boxes=[
            {"page": 1, "l": 0.1, "t": 0.1, "r": 0.5, "b": 0.2},
            {"bad": True},
        ],
        security_domain="public",
        chunk_metadata={},
        embedding=[1.0, 0.0, 0.0, 0.0],
        embedding_model="_StaticEmbeddingService",
        embedding_dim=4,
        checksum="x" * 64,
        chunker_name="structural",
        chunker_version="1.0.0",
        semantic_profile_id=uuid.uuid4(),
    )
    c2 = Chunk(
        id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
        document_version_id=doc_id,
        workspace_id=ws_id,
        chunk_index=1,
        text="Low similarity PostgreSQL chunk",
        security_domain="public",
        chunk_metadata={},
        embedding=[0.0, 1.0, 0.0, 0.0],
        embedding_model="_StaticEmbeddingService",
        embedding_dim=4,
        checksum="y" * 64,
        chunker_name="structural",
        chunker_version="1.0.0",
        semantic_profile_id=uuid.uuid4(),
    )

    class _FakePgResult:
        def all(self):
            return [(c1, 0.2), (c2, 1.8)]

    class _FakePgSession:
        def __init__(self) -> None:
            self.executed_stmts: list = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get_bind(self):
            return SimpleNamespace(dialect=postgresql.dialect())

        async def execute(self, stmt):
            self.executed_stmts.append(stmt)
            return _FakePgResult()

    fake_session = _FakePgSession()
    retriever = PostgresDenseRetriever(
        session_or_factory=lambda: fake_session,  # type: ignore[arg-type]
        embedding_service=_StaticEmbeddingService({"q": [1.0, 0.0, 0.0, 0.0]}),
    )
    results = await retriever.retrieve(
        RetrievalQuery(
            query_text="q",
            filter=RetrievalFilter(
                workspace_id=ws_id,
                security_domains=["public"],
            ),
            top_k=5,
            min_relevance_score=0.5,
        )
    )
    # 1st statement sets hnsw.iterative_scan; 2nd executes the dense SELECT
    assert len(fake_session.executed_stmts) == 2
    assert "hnsw.iterative_scan = relaxed_order" in str(
        fake_session.executed_stmts[0]
    )
    assert [r.chunk_id for r in results] == [c1.id]
    assert results[0].score == 0.9
    assert len(results[0].bounding_boxes) == 1

    # Cosine edge cases (dimension mismatch, empty, zero norm)
    assert retriever._cosine_similarity([1.0, 0.0], [1.0]) == 0.0
    assert retriever._cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    with pytest.raises(ValueError, match="hnsw_iterative_scan"):
        PostgresDenseRetriever(
            session_or_factory=lambda: fake_session,  # type: ignore[arg-type]
            embedding_service=_StaticEmbeddingService({"q": [1.0]}),
            hnsw_iterative_scan="invalid",
        )
    with pytest.raises(ValueError, match="hnsw_ef_search"):
        PostgresDenseRetriever(
            session_or_factory=lambda: fake_session,  # type: ignore[arg-type]
            embedding_service=_StaticEmbeddingService({"q": [1.0]}),
            hnsw_ef_search=0,
        )


@pytest.mark.asyncio
async def test_postgres_dense_filters_by_embedding_model_and_nonblocking() -> (
    None
):
    """Dense search never mixes vectors across models and offloads blocking."""
    import asyncio
    import time

    from rag_foundry.retrieval.embeddings import HttpEmbeddingService
    from rag_foundry.retrieval.postgres_dense import PostgresDenseRetriever

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        ws = uuid.uuid4()
        doc = await _seed_document(session, ws)

        c_old_model = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc.id,
            workspace_id=ws,
            chunk_index=0,
            text="Embedded with old model A",
            security_domain="public",
            chunk_metadata={},
            embedding=[1.0, 0.0, 0.0, 0.0],
            embedding_model="old-model-a",
            embedding_dim=4,
            checksum="1" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=doc.semantic_profile_id,
        )
        c_new_model = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc.id,
            workspace_id=ws,
            chunk_index=1,
            text="Embedded with new model B",
            security_domain="public",
            chunk_metadata={},
            embedding=[0.6, 0.8, 0.0, 0.0],
            embedding_model="bge-small",
            embedding_dim=4,
            checksum="2" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=doc.semantic_profile_id,
        )
        session.add_all([c_old_model, c_new_model])
        await session.commit()

        # Blocking HTTP transport sleeps 0.15s; concurrent coroutine must tick
        def _slow_transport(url, payload, headers, timeout):
            time.sleep(0.15)
            return {"embeddings": [[1.0, 0.0, 0.0, 0.0]]}

        http_emb = HttpEmbeddingService(
            base_url="http://localhost:11434",
            model_name="bge-small",
            dimension=4,
            transport=_slow_transport,
        )
        retriever = PostgresDenseRetriever(
            session_or_factory=session,
            embedding_service=http_emb,
        )

        ticks = 0

        async def _ticker() -> None:
            nonlocal ticks
            for _ in range(3):
                await asyncio.sleep(0.02)
                ticks += 1

        results, _ = await asyncio.gather(
            retriever.retrieve(
                RetrievalQuery(
                    query_text="model isolation",
                    filter=RetrievalFilter(
                        workspace_id=ws, security_domains=["public"]
                    ),
                    top_k=5,
                )
            ),
            _ticker(),
        )
        # Event loop was NOT blocked while HTTP transport slept
        assert ticks == 3
        # Only bge-small chunk returned; old-model-a chunk strictly excluded
        assert [r.chunk_id for r in results] == [c_new_model.id]

