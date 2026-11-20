"""Tests for dialect-aware pgvector/FTS types, Chunk ORM schema, and migration."""

import io
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from rag_foundry.db.models import Base, Chunk, Document
from rag_foundry.db.session import get_sessionmaker


def _make_alembic_config(url: str, output_buffer: io.StringIO | None = None) -> Config:
    """Create an Alembic Config pointing at the repo migrations directory."""
    repo_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    if output_buffer is not None:
        cfg.output_buffer = output_buffer
    return cfg


def test_vector_and_tsvector_dialect_compilation_and_serialization() -> None:
    """VectorType and TSVectorType compile and bind cleanly across dialects."""
    from rag_foundry.db.types import TSVectorType, VectorType

    pg = postgresql.dialect()
    sq = sqlite.dialect()

    vec_fixed = VectorType(dim=384)
    vec_unbounded = VectorType()
    ts_vec = TSVectorType()

    assert vec_fixed.compile(dialect=pg) == "vector(384)"
    assert vec_unbounded.compile(dialect=pg) == "vector"
    assert vec_fixed.compile(dialect=sq).upper() == "JSON"
    assert ts_vec.compile(dialect=pg).upper() == "TSVECTOR"
    assert ts_vec.compile(dialect=sq).upper() == "TEXT"

    with pytest.raises(ValueError):
        VectorType(dim=0)

    sample = [0.25, -0.5, 0.75]
    pg_bound = vec_fixed.process_bind_param(sample, pg)
    assert pg_bound == "[0.25,-0.5,0.75]"
    assert vec_fixed.process_result_value(pg_bound, pg) == sample
    assert vec_fixed.process_result_value("[]", pg) == []
    assert vec_fixed.process_bind_param(None, pg) is None
    assert vec_fixed.process_result_value(None, pg) is None

    sq_bound = vec_fixed.process_bind_param(sample, sq)
    assert sq_bound == sample
    assert vec_fixed.process_result_value(sq_bound, sq) == sample


def test_chunk_orm_postgresql_ddl_and_operators() -> None:
    """Chunk table DDL emits pgvector, TSVECTOR, HNSW, GIN, and ACL indexes."""
    pg = postgresql.dialect()
    table = Chunk.__table__

    expected_cols = {
        "chunk_index",
        "bounding_boxes",
        "security_domain",
        "chunk_metadata",
        "embedding",
        "embedding_model",
        "embedding_dim",
        "search_vector",
    }
    assert expected_cols.issubset(set(table.columns.keys()))

    ddl = str(CreateTable(table).compile(dialect=pg))
    assert "embedding vector(384)" in ddl
    assert "search_vector TSVECTOR" in ddl
    assert "security_domain VARCHAR(128) DEFAULT 'general' NOT NULL" in ddl

    index_ddls = {
        idx.name: str(CreateIndex(idx).compile(dialect=pg))
        for idx in table.indexes
    }
    assert "ix_chunks_workspace_security_domain" in index_ddls
    assert (
        "(workspace_id, security_domain)"
        in index_ddls["ix_chunks_workspace_security_domain"]
    )
    assert "ix_chunks_search_vector_gin" in index_ddls
    assert "USING gin" in index_ddls["ix_chunks_search_vector_gin"]
    assert "ix_chunks_embedding_hnsw" in index_ddls
    assert "USING hnsw" in index_ddls["ix_chunks_embedding_hnsw"]
    assert "vector_cosine_ops" in index_ddls["ix_chunks_embedding_hnsw"]

    # Verify pgvector <=> returns Float (not VectorType) and processes float
    # results cleanly under PostgreSQL / asyncpg dialects (no TypeError).
    from sqlalchemy import Float
    from sqlalchemy.dialects.postgresql import asyncpg as pg_asyncpg

    dist_expr = Chunk.embedding.cosine_distance([0.1, 0.2, 0.3])
    assert isinstance(dist_expr.type, Float)
    for dialect in (pg, pg_asyncpg.dialect()):
        proc = dist_expr.type.result_processor(dialect, None)
        processed = proc(0.123) if proc is not None else 0.123
        assert processed == pytest.approx(0.123)

    dist_stmt = select(Chunk.id, dist_expr.label("cosine_distance")).order_by(
        dist_expr
    )
    compiled_dist = str(dist_stmt.compile(dialect=pg))
    assert "<=>" in compiled_dist

    fts_stmt = select(Chunk.id).where(
        Chunk.search_vector.op("@@")(
            func.websearch_to_tsquery("english", "governance policy")
        )
    )
    compiled_fts = str(fts_stmt.compile(dialect=pg))
    assert "@@" in compiled_fts
    assert "websearch_to_tsquery" in compiled_fts


def test_default_embedding_dim_env_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG_FOUNDRY_EMBEDDING_DIM configures DEFAULT_EMBEDDING_DIM safely."""
    from rag_foundry.db.types import _resolve_default_embedding_dim

    monkeypatch.delenv("RAG_FOUNDRY_EMBEDDING_DIM", raising=False)
    assert _resolve_default_embedding_dim() == 384

    monkeypatch.setenv("RAG_FOUNDRY_EMBEDDING_DIM", "768")
    assert _resolve_default_embedding_dim() == 768

    monkeypatch.setenv("RAG_FOUNDRY_EMBEDDING_DIM", "0")
    with pytest.raises(ValueError, match="positive"):
        _resolve_default_embedding_dim()

    monkeypatch.setenv("RAG_FOUNDRY_EMBEDDING_DIM", "not-an-int")
    with pytest.raises(ValueError, match="Invalid"):
        _resolve_default_embedding_dim()


@pytest.mark.asyncio
async def test_chunk_sqlite_roundtrip_with_embeddings_and_provenance() -> None:
    """Chunk ORM persists new retrieval, provenance, and ACL fields on SQLite."""
    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        ws_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        doc = Document(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            workspace_id=ws_id,
            title="Policy Manual",
            mime_type="application/pdf",
            checksum="a" * 64,
            page_count=3,
            parser_name="native_pdf",
            parser_version="1.0.0",
            semantic_profile_id=profile_id,
        )
        session.add(doc)
        await session.flush()

        chunk_full = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc.id,
            workspace_id=ws_id,
            chunk_index=2,
            text="Governed chunks carry bounding boxes and embeddings.",
            section_path=["Security", "Access Control"],
            page_numbers=[1, 2],
            bounding_boxes=[
                {"page": 1, "l": 0.1, "t": 0.2, "r": 0.8, "b": 0.35}
            ],
            security_domain="restricted_legal",
            chunk_metadata={"classification": "internal", "region": "eu"},
            embedding=[0.5, 0.5, -0.5, 0.5],
            embedding_model="mock-deterministic-384",
            embedding_dim=4,
            search_vector="governed chunks carry bounding boxes embeddings",
            checksum="b" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=profile_id,
        )
        chunk_defaults = Chunk(
            id=uuid.uuid4(),
            document_version_id=doc.id,
            workspace_id=ws_id,
            text="Default column values stay backward compatible.",
            checksum="c" * 64,
            chunker_name="structural",
            chunker_version="1.0.0",
            semantic_profile_id=profile_id,
        )
        session.add_all([chunk_full, chunk_defaults])
        await session.commit()

        res_full = await session.execute(
            select(Chunk).where(Chunk.id == chunk_full.id)
        )
        loaded_full = res_full.scalar_one()
        assert loaded_full.chunk_index == 2
        assert loaded_full.bounding_boxes == [
            {"page": 1, "l": 0.1, "t": 0.2, "r": 0.8, "b": 0.35}
        ]
        assert loaded_full.security_domain == "restricted_legal"
        assert loaded_full.chunk_metadata == {
            "classification": "internal",
            "region": "eu",
        }
        assert loaded_full.embedding == [0.5, 0.5, -0.5, 0.5]
        assert loaded_full.embedding_model == "mock-deterministic-384"
        assert loaded_full.embedding_dim == 4
        assert loaded_full.search_vector is not None

        res_def = await session.execute(
            select(Chunk).where(Chunk.id == chunk_defaults.id)
        )
        loaded_def = res_def.scalar_one()
        assert loaded_def.chunk_index == 0
        assert loaded_def.bounding_boxes == []
        assert loaded_def.security_domain == "general"
        assert loaded_def.chunk_metadata == {}
        assert loaded_def.embedding is None
        assert loaded_def.embedding_model is None
        assert loaded_def.embedding_dim is None
        assert loaded_def.search_vector is None


def test_alembic_migration_sqlite_upgrade_and_downgrade(
    tmp_path: Path,
) -> None:
    """Migration upgrades cleanly from e2b84f6c9a31 to head and downgrades."""
    db_path = tmp_path / "alembic_chunks.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"
    cfg = _make_alembic_config(async_url)

    # Upgrade to the prior head revision
    command.upgrade(cfg, "e2b84f6c9a31")

    sync_engine = create_engine(sync_url)
    with sync_engine.begin() as conn:
        cols_before = {c["name"] for c in inspect(conn).get_columns("chunks")}
        assert "embedding" not in cols_before
        assert "security_domain" not in cols_before

        # Insert an existing row before upgrading to verify server defaults
        doc_id = uuid.uuid4().hex
        chunk_id = uuid.uuid4().hex
        ws_id = uuid.uuid4().hex
        prof_id = uuid.uuid4().hex
        conn.execute(
            text(
                "INSERT INTO documents "
                "(id, document_id, workspace_id, title, mime_type, checksum, "
                "parser_name, parser_version, semantic_profile_id, created_at) "
                "VALUES (:id, :doc_id, :ws, 'Old', 'text/plain', 'h1', "
                "'p', '1', :prof, '2026-01-01 00:00:00')"
            ),
            {"id": doc_id, "doc_id": doc_id, "ws": ws_id, "prof": prof_id},
        )
        conn.execute(
            text(
                "INSERT INTO chunks "
                "(id, document_version_id, workspace_id, text, section_path, "
                "page_numbers, checksum, chunker_name, chunker_version, "
                "semantic_profile_id, created_at) "
                "VALUES (:id, :doc, :ws, 'Legacy chunk', '[]', '[]', 'h2', "
                "'legacy', '1', :prof, '2026-01-01 00:00:00')"
            ),
            {"id": chunk_id, "doc": doc_id, "ws": ws_id, "prof": prof_id},
        )

    # Upgrade to new head
    command.upgrade(cfg, "head")

    with sync_engine.connect() as conn:
        cols_after = {c["name"] for c in inspect(conn).get_columns("chunks")}
        expected_new = {
            "chunk_index",
            "bounding_boxes",
            "security_domain",
            "chunk_metadata",
            "embedding",
            "embedding_model",
            "embedding_dim",
            "search_vector",
        }
        assert expected_new.issubset(cols_after)

        idx_names = {i["name"] for i in inspect(conn).get_indexes("chunks")}
        assert "ix_chunks_security_domain" in idx_names
        assert "ix_chunks_workspace_security_domain" in idx_names

        row = conn.execute(
            text("SELECT chunk_index, security_domain FROM chunks")
        ).fetchone()
        assert row is not None
        assert row[0] == 0
        assert row[1] == "general"

    # Downgrade back to prior head
    command.downgrade(cfg, "e2b84f6c9a31")

    with sync_engine.connect() as conn:
        cols_down = {c["name"] for c in inspect(conn).get_columns("chunks")}
        for col in expected_new:
            assert col not in cols_down
        idx_down = {i["name"] for i in inspect(conn).get_indexes("chunks")}
        assert "ix_chunks_workspace_security_domain" not in idx_down

    sync_engine.dispose()


def test_alembic_migration_postgresql_offline_sql() -> None:
    """Offline PostgreSQL migration SQL emits pgvector extension and indexes."""
    buf = io.StringIO()
    cfg = _make_alembic_config(
        "postgresql+asyncpg://user:pass@localhost:5432/rag_foundry",
        output_buffer=buf,
    )
    command.upgrade(cfg, "e2b84f6c9a31:head", sql=True)
    sql_output = buf.getvalue()

    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql_output
    assert "vector(384)" in sql_output
    assert "TSVECTOR" in sql_output
    assert "ix_chunks_workspace_security_domain" in sql_output
    assert "USING gin" in sql_output
    assert "USING hnsw" in sql_output
    assert "vector_cosine_ops" in sql_output
