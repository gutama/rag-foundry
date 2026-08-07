"""Tests for core ORM models: Document, Chunk, MetadataSchema, TaxonomyConcept, AuditEvent."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_document_model_crud():
    """Test CRUD operations for Document ORM model."""
    from rag_foundry.db.models import Base, Document
    from rag_foundry.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        # Create tables
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        doc_id = uuid.uuid4()
        workspace_id = uuid.uuid4()
        profile_id = uuid.uuid4()

        doc = Document(
            id=doc_id,
            document_id=uuid.uuid4(),
            workspace_id=workspace_id,
            title="Test Architecture Document",
            mime_type="application/pdf",
            checksum="abc123hash",
            page_count=42,
            parser_name="docling",
            parser_version="1.0.0",
            semantic_profile_id=profile_id,
        )
        session.add(doc)
        await session.commit()

        result = await session.execute(
            select(Document).where(Document.id == doc_id)
        )
        fetched_doc = result.scalar_one()
        assert fetched_doc.title == "Test Architecture Document"
        assert fetched_doc.mime_type == "application/pdf"
        assert fetched_doc.page_count == 42


@pytest.mark.asyncio
async def test_chunk_model_crud():
    """Test CRUD operations for Chunk ORM model with relationship to Document."""
    from rag_foundry.db.models import Base, Chunk, Document
    from rag_foundry.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        doc_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        doc = Document(
            id=doc_id,
            document_id=uuid.uuid4(),
            workspace_id=workspace_id,
            title="Document for Chunk Test",
            mime_type="text/plain",
            checksum="def456hash",
            parser_name="native",
            parser_version="1.0",
            semantic_profile_id=uuid.uuid4(),
        )
        session.add(doc)
        await session.commit()

        chunk_id = uuid.uuid4()
        chunk = Chunk(
            id=chunk_id,
            document_version_id=doc_id,
            workspace_id=workspace_id,
            text="This is a test chunk content.",
            section_path=["Introduction", "Background"],
            page_numbers=[1, 2],
            checksum="chunkhash789",
            chunker_name="structural",
            chunker_version="1.0",
            semantic_profile_id=uuid.uuid4(),
        )
        session.add(chunk)
        await session.commit()

        result = await session.execute(
            select(Chunk).where(Chunk.id == chunk_id)
        )
        fetched_chunk = result.scalar_one()
        assert fetched_chunk.text == "This is a test chunk content."
        assert fetched_chunk.section_path == ["Introduction", "Background"]
        assert fetched_chunk.page_numbers == [1, 2]


@pytest.mark.asyncio
async def test_metadata_schema_model_crud():
    """Test CRUD operations for MetadataSchema ORM model."""
    from rag_foundry.db.models import Base, MetadataSchema
    from rag_foundry.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        schema_id = uuid.uuid4()
        schema = MetadataSchema(
            id=schema_id,
            name="institutional_doc_v1",
            version="1.0.0",
            schema_json={
                "type": "object",
                "properties": {"author": {"type": "string"}},
            },
            status="approved",
        )
        session.add(schema)
        await session.commit()

        result = await session.execute(
            select(MetadataSchema).where(MetadataSchema.id == schema_id)
        )
        fetched = result.scalar_one()
        assert fetched.name == "institutional_doc_v1"
        assert fetched.schema_json["properties"]["author"]["type"] == "string"


@pytest.mark.asyncio
async def test_taxonomy_concept_model_crud():
    """Test CRUD operations for TaxonomyConcept ORM model."""
    from rag_foundry.db.models import Base, TaxonomyConcept
    from rag_foundry.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        concept_id = uuid.uuid4()
        concept = TaxonomyConcept(
            id=concept_id,
            scheme_id=uuid.uuid4(),
            uri="http://example.org/taxonomies/finance",
            pref_labels={"en": "Finance", "id": "Keuangan"},
            alt_labels={"en": ["Banking", "Fiscal"]},
            broader_uris=["http://example.org/taxonomies/economics"],
            related_uris=[],
            status="approved",
            version="1.0",
        )
        session.add(concept)
        await session.commit()

        result = await session.execute(
            select(TaxonomyConcept).where(TaxonomyConcept.id == concept_id)
        )
        fetched = result.scalar_one()
        assert fetched.uri == "http://example.org/taxonomies/finance"
        assert fetched.pref_labels["id"] == "Keuangan"


@pytest.mark.asyncio
async def test_audit_event_model_crud():
    """Test CRUD operations for AuditEvent ORM model."""
    from rag_foundry.db.models import Base, AuditEvent
    from rag_foundry.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        event_id = uuid.uuid4()
        event = AuditEvent(
            id=event_id,
            event_type="document.ingested",
            actor_id="user_steward_01",
            resource_type="document",
            resource_id="doc_123",
            details={"status": "success", "file_size": 1024},
        )
        session.add(event)
        await session.commit()

        result = await session.execute(
            select(AuditEvent).where(AuditEvent.id == event_id)
        )
        fetched = result.scalar_one()
        assert fetched.event_type == "document.ingested"
        assert fetched.details["file_size"] == 1024
