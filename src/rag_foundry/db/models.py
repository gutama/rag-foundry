"""SQLAlchemy 2.0 ORM models for core RAG Foundry entities."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


class Document(Base):
    """Document ORM model representing canonical ingested document versions."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False, index=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(256), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parser_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_profile_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    chunks: Mapped[List["Chunk"]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """Chunk ORM model representing text chunks extracted from documents."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    section_path: Mapped[List[str]] = mapped_column(JSON, default=list)
    page_numbers: Mapped[List[int]] = mapped_column(JSON, default=list)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    chunker_name: Mapped[str] = mapped_column(String(128), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_profile_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    document: Mapped["Document"] = relationship(
        "Document", back_populates="chunks"
    )


class MetadataSchema(Base):
    """MetadataSchema ORM model representing versioned metadata schemas."""

    __tablename__ = "metadata_schemas"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(64), default="draft", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class TaxonomyConcept(Base):
    """TaxonomyConcept ORM model representing SKOS-compatible concepts."""

    __tablename__ = "taxonomy_concepts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    scheme_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False, index=True
    )
    uri: Mapped[str] = mapped_column(
        String(512), nullable=False, unique=True, index=True
    )
    pref_labels: Mapped[Dict[str, str]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    alt_labels: Mapped[Dict[str, List[str]]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    broader_uris: Mapped[List[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    related_uris: Mapped[List[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(64), default="draft", nullable=False
    )
    version: Mapped[str] = mapped_column(
        String(64), default="1.0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AuditEvent(Base):
    """AuditEvent ORM model representing immutable system audit events."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(256), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(256), nullable=False)
    details: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
