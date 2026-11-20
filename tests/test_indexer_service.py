"""Tests for IndexerService and IngestionPipeline ingest_and_index wiring."""

import tempfile
import uuid
from typing import List

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from rag_foundry.chunking import ChunkingConfig, StructuralChunker
from rag_foundry.db.models import Base, Chunk, Document
from rag_foundry.db.session import get_sessionmaker
from rag_foundry.ingestion.pipeline import (
    IngestionJobStatus,
    IngestionPipeline,
)
from rag_foundry.parsing.models import CanonicalDocument, DocumentElement
from rag_foundry.retrieval.embeddings import (
    EmbeddingService,
    MockDeterministicEmbeddingService,
)
from rag_foundry.retrieval.models import RetrievalFilter, RetrievalQuery
from rag_foundry.retrieval.postgres_dense import PostgresDenseRetriever
from rag_foundry.retrieval.postgres_lexical import PostgresLexicalRetriever
from rag_foundry.storage.provider import LocalStorageProvider


def _sample_canonical_doc() -> CanonicalDocument:
    """Build a multi-section CanonicalDocument with bbox and table elements."""
    return CanonicalDocument(
        title="Risk Controls Handbook",
        source_filename="risk_controls.pdf",
        mime_type="application/pdf",
        page_count=2,
        parser_name="native_pdf",
        parser_version="1.0.0",
        elements=[
            DocumentElement(
                element_type="heading",
                text="Liquidity Controls",
                page_number=1,
                bounding_box=(0.1, 0.1, 0.8, 0.18),
                sequence_number=0,
                metadata={"level": 1},
            ),
            DocumentElement(
                element_type="paragraph",
                text=(
                    "Treasury operations must maintain a 100 percent liquidity "
                    "coverage ratio across all stress horizons."
                ),
                page_number=1,
                bounding_box=(0.1, 0.22, 0.9, 0.35),
                sequence_number=1,
            ),
            DocumentElement(
                element_type="table",
                text="| Metric | Minimum |\n| --- | --- |\n| LCR | 100% |",
                page_number=2,
                bounding_box=(0.1, 0.15, 0.85, 0.4),
                sequence_number=2,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_indexer_persists_chunks_with_embeddings_acl_idempotency() -> (
    None
):
    """IndexerService persists chunks atomically and re-indexes idempotently."""
    from rag_foundry.ingestion.indexer import IndexerService

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        ws_id = uuid.uuid4()
        prof_id = uuid.uuid4()
        doc = Document(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            workspace_id=ws_id,
            title="Risk Controls Handbook",
            mime_type="application/pdf",
            checksum="a" * 64,
            page_count=2,
            parser_name="native_pdf",
            parser_version="1.0.0",
            semantic_profile_id=prof_id,
        )
        session.add(doc)
        await session.commit()

        emb = MockDeterministicEmbeddingService(dimension=384)
        indexer = IndexerService(
            session_or_factory=session,
            embedding_service=emb,
            chunker=StructuralChunker(
                ChunkingConfig(target_chars=400, max_chars=500)
            ),
            embedding_model_name="mock-det-384",
        )
        canonical = _sample_canonical_doc()

        # First indexing run
        res1 = await indexer.index_document(
            canonical_doc=canonical,
            document_version_id=doc.id,
            workspace_id=ws_id,
            semantic_profile_id=prof_id,
            security_domain="finance",
            metadata={"department": "treasury", "year": 2026},
        )
        assert res1.document_version_id == doc.id
        assert res1.workspace_id == ws_id
        assert res1.chunk_count == 2
        assert len(res1.chunk_ids) == 2
        assert res1.replaced_chunk_count == 0
        assert res1.embedding_model == "mock-det-384"
        assert res1.embedding_dim == 384

        rows = (
            (
                await session.execute(
                    select(Chunk)
                    .where(Chunk.document_version_id == doc.id)
                    .order_by(Chunk.chunk_index.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        assert rows[0].section_path == ["Liquidity Controls"]
        assert rows[0].page_numbers == [1]
        assert len(rows[0].bounding_boxes) == 1
        assert rows[0].bounding_boxes[0]["page"] == 1
        assert rows[0].security_domain == "finance"
        assert rows[0].chunk_metadata["department"] == "treasury"
        assert rows[0].chunk_metadata["year"] == 2026
        assert rows[0].embedding is not None
        assert len(rows[0].embedding) == 384
        assert rows[0].embedding_model == "mock-det-384"
        assert rows[0].embedding_dim == 384
        assert rows[0].search_vector is not None
        assert rows[1].page_numbers == [2]
        assert rows[1].section_path == ["Liquidity Controls"]

        # Re-indexing same document replaces existing chunks idempotently
        res2 = await indexer.index_document(
            canonical_doc=canonical,
            document_version_id=doc.id,
            workspace_id=ws_id,
            semantic_profile_id=prof_id,
            security_domain="finance",
            metadata={"department": "treasury", "year": 2026},
        )
        assert res2.chunk_count == 2
        assert res2.replaced_chunk_count == 2
        assert res2.chunk_ids == res1.chunk_ids

        rows_after = (
            (
                await session.execute(
                    select(Chunk).where(Chunk.document_version_id == doc.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows_after) == 2

        # PostgreSQL FTS update SQL compiles cleanly with to_tsvector
        pg_sql = str(
            indexer.build_postgresql_fts_update(doc.id).compile(
                dialect=postgresql.dialect()
            )
        )
        assert "UPDATE chunks" in pg_sql
        assert "to_tsvector" in pg_sql
        assert "document_version_id" in pg_sql


@pytest.mark.asyncio
async def test_indexer_atomicity_preserves_chunks_on_embedding_error() -> None:
    """Embedding failure aborts cleanly before deleting existing chunks."""
    from rag_foundry.ingestion.indexer import IndexerService

    class _FailingEmbedder(EmbeddingService):
        @property
        def dimension(self) -> int:
            return 384

        def embed_query(self, text: str) -> List[float]:
            raise RuntimeError("Embedding endpoint unavailable")

        def embed_texts(self, texts: List[str]) -> List[List[float]]:
            raise RuntimeError("Embedding endpoint unavailable")

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        ws_id = uuid.uuid4()
        prof_id = uuid.uuid4()
        doc = Document(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            workspace_id=ws_id,
            title="Atomic Doc",
            mime_type="application/pdf",
            checksum="b" * 64,
            page_count=1,
            parser_name="native_pdf",
            parser_version="1.0.0",
            semantic_profile_id=prof_id,
        )
        session.add(doc)
        await session.commit()

        good_indexer = IndexerService(
            session_or_factory=session,
            embedding_service=MockDeterministicEmbeddingService(dimension=384),
        )
        canonical = _sample_canonical_doc()
        await good_indexer.index_document(
            canonical_doc=canonical,
            document_version_id=doc.id,
            workspace_id=ws_id,
            semantic_profile_id=prof_id,
        )

        failing_indexer = IndexerService(
            session_or_factory=session,
            embedding_service=_FailingEmbedder(),
        )
        with pytest.raises(RuntimeError, match="unavailable"):
            await failing_indexer.index_document(
                canonical_doc=canonical,
                document_version_id=doc.id,
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
            )

        remaining = (
            (
                await session.execute(
                    select(Chunk).where(Chunk.document_version_id == doc.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(remaining) == 2


@pytest.mark.asyncio
async def test_ingestion_pipeline_ingest_and_index_searchable(
    sample_pdf_bytes: bytes,
) -> None:
    """IngestionPipeline.ingest_and_index parses, chunks, and indexes."""
    from rag_foundry.ingestion.indexer import IndexerService

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        emb = MockDeterministicEmbeddingService(dimension=384)
        indexer = IndexerService(
            session_or_factory=session,
            embedding_service=emb,
        )
        ws_id = uuid.uuid4()
        prof_id = uuid.uuid4()

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = LocalStorageProvider(base_path=tmp_dir)
            pipeline = IngestionPipeline(
                storage_provider=storage,
                session=session,
                indexer=indexer,
            )
            result = await pipeline.ingest_and_index(
                file_bytes=sample_pdf_bytes,
                filename="policy.pdf",
                mime_type="application/pdf",
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
                security_domain="compliance",
                metadata={"source": "internal"},
            )

            assert result.status == IngestionJobStatus.INDEXED
            assert result.indexing_result is not None
            assert result.indexing_result.chunk_count >= 1
            assert (
                result.indexing_result.document_version_id == result.document_id
            )

            # Indexed chunks are immediately searchable via DB retrievers
            dense = PostgresDenseRetriever(session, emb)
            lexical = PostgresLexicalRetriever(session)

            query = RetrievalQuery(
                query_text="canonical parsing model",
                filter=RetrievalFilter(
                    workspace_id=ws_id,
                    security_domains=["compliance"],
                    metadata_filters={"source": "internal"},
                ),
                top_k=5,
            )
            dense_hits = await dense.retrieve(query)
            lex_hits = await lexical.retrieve(query)
            assert len(dense_hits) >= 1
            assert len(lex_hits) >= 1
            assert dense_hits[0].document_version_id == result.document_id
            assert lex_hits[0].document_version_id == result.document_id
            assert lex_hits[0].section_path == [
                "Institutional Architecture Report"
            ]

            # Without an indexer configured, ingest_and_index raises ValueError
            plain_pipeline = IngestionPipeline(
                storage_provider=storage,
                session=session,
            )
            with pytest.raises(ValueError, match="IndexerService"):
                await plain_pipeline.ingest_and_index(
                    file_bytes=sample_pdf_bytes,
                    filename="no_indexer.pdf",
                    mime_type="application/pdf",
                    workspace_id=ws_id,
                    semantic_profile_id=prof_id,
                )

            # Corrupted bytes return FAILED without crashing
            bad_res = await pipeline.ingest_and_index(
                file_bytes=b"Not a valid PDF",
                filename="bad.pdf",
                mime_type="application/pdf",
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
            )
            assert bad_res.status == IngestionJobStatus.FAILED
            assert bad_res.indexing_result is None


@pytest.mark.asyncio
async def test_indexer_validation_and_empty_doc_reindex() -> None:
    """Indexer validates domain/schema dim and clears stale chunks."""
    from rag_foundry.ingestion.indexer import IndexerService
    from rag_foundry.retrieval.embeddings import HttpEmbeddingService

    class _WrongDimEmbedder(EmbeddingService):
        @property
        def dimension(self) -> int:
            return 384

        def embed_query(self, text: str) -> List[float]:
            return [0.1] * 8

        def embed_texts(self, texts: List[str]) -> List[List[float]]:
            return [[0.1] * 8 for _ in texts]

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        ws_id = uuid.uuid4()
        prof_id = uuid.uuid4()
        doc = Document(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            workspace_id=ws_id,
            title="Validation Doc",
            mime_type="application/pdf",
            checksum="c" * 64,
            page_count=1,
            parser_name="native_pdf",
            parser_version="1.0.0",
            semantic_profile_id=prof_id,
        )
        session.add(doc)
        await session.commit()

        # Early failure when embedding service dimension != schema vector(384)
        wrong_schema_svc = HttpEmbeddingService(
            base_url="http://localhost:11434",
            model_name="nomic-embed-text",
            dimension=768,
        )
        with pytest.raises(ValueError, match="Chunk.embedding schema"):
            IndexerService(
                session_or_factory=session,
                embedding_service=wrong_schema_svc,
            )

        indexer = IndexerService(
            session_or_factory=session,
            embedding_service=MockDeterministicEmbeddingService(dimension=384),
        )
        canonical = _sample_canonical_doc()

        # Blank security_domain rejected
        with pytest.raises(ValueError, match="security_domain"):
            await indexer.index_document(
                canonical_doc=canonical,
                document_version_id=doc.id,
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
                security_domain="   ",
            )

        # Wrong runtime vector length rejected before DB writes
        bad_dim_indexer = IndexerService(
            session_or_factory=session,
            embedding_service=_WrongDimEmbedder(),
        )
        with pytest.raises(ValueError, match="dimension mismatch"):
            await bad_dim_indexer.index_document(
                canonical_doc=canonical,
                document_version_id=doc.id,
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
            )

        # Indexing then re-indexing with an empty document deletes stale chunks
        first = await indexer.index_document(
            canonical_doc=canonical,
            document_version_id=doc.id,
            workspace_id=ws_id,
            semantic_profile_id=prof_id,
        )
        assert first.chunk_count == 2

        empty_doc = CanonicalDocument(
            title="Empty",
            source_filename="empty.pdf",
            mime_type="application/pdf",
            page_count=1,
            parser_name="native_pdf",
            parser_version="1.0.0",
            elements=[],
        )
        cleared = await indexer.index_document(
            canonical_doc=empty_doc,
            document_version_id=doc.id,
            workspace_id=ws_id,
            semantic_profile_id=prof_id,
        )
        assert cleared.chunk_count == 0
        assert cleared.replaced_chunk_count == 2


@pytest.mark.asyncio
async def test_indexer_default_expire_on_commit_and_commit_false_rollback(
    tmp_path,
) -> None:
    """Indexer works with expire_on_commit=True and respects commit=False."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from rag_foundry.ingestion.indexer import IndexerService

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'expire_test.db'}"
    engine = create_async_engine(db_url)
    # Default SQLAlchemy async_sessionmaker has expire_on_commit=True!
    default_factory = async_sessionmaker(engine)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        ws_id = uuid.uuid4()
        prof_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        async with default_factory() as setup_sess:
            setup_sess.add(
                Document(
                    id=doc_id,
                    document_id=uuid.uuid4(),
                    workspace_id=ws_id,
                    title="Expire Test Doc",
                    mime_type="application/pdf",
                    checksum="e" * 64,
                    page_count=2,
                    parser_name="native_pdf",
                    parser_version="1.0.0",
                    semantic_profile_id=prof_id,
                )
            )
            await setup_sess.commit()

        emb = MockDeterministicEmbeddingService(dimension=384)
        canonical = _sample_canonical_doc()

        # 1. Default sessionmaker (expire_on_commit=True): no DetachedInstance
        factory_indexer = IndexerService(
            session_or_factory=default_factory,
            embedding_service=emb,
        )
        res_factory = await factory_indexer.index_document(
            canonical_doc=canonical,
            document_version_id=doc_id,
            workspace_id=ws_id,
            semantic_profile_id=prof_id,
        )
        assert res_factory.chunk_count == 2
        assert len(res_factory.chunk_ids) == 2

        # commit=False on a sessionmaker raises ValueError
        with pytest.raises(ValueError, match="commit=False"):
            await factory_indexer.index_document(
                canonical_doc=canonical,
                document_version_id=doc_id,
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
                commit=False,
            )

        # 2. Shared session (expire_on_commit=True) + active txn + commit=True
        async with default_factory() as shared_sess:
            await shared_sess.execute(select(Document).limit(1))
            assert shared_sess.in_transaction()
            shared_indexer = IndexerService(
                session_or_factory=shared_sess,
                embedding_service=emb,
            )
            res_shared = await shared_indexer.index_document(
                canonical_doc=canonical,
                document_version_id=doc_id,
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
                commit=True,
            )
            assert res_shared.chunk_count == 2
            assert res_shared.chunk_ids == res_factory.chunk_ids

        # 3. Fresh session (not in_transaction) + commit=False + rollback
        doc_id_2 = uuid.uuid4()
        async with default_factory() as setup_sess:
            setup_sess.add(
                Document(
                    id=doc_id_2,
                    document_id=uuid.uuid4(),
                    workspace_id=ws_id,
                    title="Rollback Test Doc",
                    mime_type="application/pdf",
                    checksum="f" * 64,
                    page_count=2,
                    parser_name="native_pdf",
                    parser_version="1.0.0",
                    semantic_profile_id=prof_id,
                )
            )
            await setup_sess.commit()

        async with default_factory() as fresh_sess:
            assert not fresh_sess.in_transaction()
            uncommitted_indexer = IndexerService(
                session_or_factory=fresh_sess,
                embedding_service=emb,
            )
            res_uncommitted = await uncommitted_indexer.index_document(
                canonical_doc=canonical,
                document_version_id=doc_id_2,
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
                commit=False,
            )
            assert res_uncommitted.chunk_count == 2
            assert fresh_sess.in_transaction()
            await fresh_sess.rollback()

        # Verify rollback left zero rows visible to a brand-new session
        async with default_factory() as verify_sess:
            persisted = (
                (
                    await verify_sess.execute(
                        select(Chunk).where(
                            Chunk.document_version_id == doc_id_2
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert persisted == []

        # 4. commit=False followed by explicit commit() persists rows cleanly
        async with default_factory() as commit_later_sess:
            indexer_later = IndexerService(
                session_or_factory=commit_later_sess,
                embedding_service=emb,
            )
            await indexer_later.index_document(
                canonical_doc=canonical,
                document_version_id=doc_id_2,
                workspace_id=ws_id,
                semantic_profile_id=prof_id,
                commit=False,
            )
            await commit_later_sess.commit()

        async with default_factory() as verify_sess:
            persisted_after = (
                (
                    await verify_sess.execute(
                        select(Chunk).where(
                            Chunk.document_version_id == doc_id_2
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(persisted_after) == 2
    finally:
        await engine.dispose()

