"""SQLAlchemy 2.0 ORM models for core RAG Foundry entities."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
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


class OntologyReleaseRecord(Base):
    """A versioned ontology release (ADR-0011).

    Approved releases are immutable; edits go into a new draft release that
    records the release it was derived from in ``previous_release_id``.
    """

    __tablename__ = "ontology_releases"
    __table_args__ = (
        UniqueConstraint(
            "ontology_uri", "version", name="uq_ontology_release_version"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    ontology_uri: Mapped[str] = mapped_column(
        String(512), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="draft", nullable=False
    )
    previous_release_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("ontology_releases.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    classes: Mapped[List["OntologyClassRecord"]] = relationship(
        "OntologyClassRecord",
        back_populates="release",
        cascade="all, delete-orphan",
    )
    properties: Mapped[List["OntologyPropertyRecord"]] = relationship(
        "OntologyPropertyRecord",
        back_populates="release",
        cascade="all, delete-orphan",
    )


class OntologyClassRecord(Base):
    """An ontology class within one release.

    The IRI is unique per release, not globally, so the same term keeps its
    identifier from one release to the next.
    """

    __tablename__ = "ontology_classes"
    __table_args__ = (
        UniqueConstraint("release_id", "uri", name="uq_ontology_class_uri"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ontology_releases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uri: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    preferred_labels: Mapped[Dict[str, str]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    parent_class_uris: Mapped[List[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    description: Mapped[Dict[str, str]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    identity_rules: Mapped[List[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft", nullable=False
    )

    release: Mapped["OntologyReleaseRecord"] = relationship(
        "OntologyReleaseRecord", back_populates="classes"
    )


class OntologyPropertyRecord(Base):
    """An object or data property within one release.

    Constraints are stored as a JSON list of ``PropertyConstraint`` dumps and
    re-validated by the domain model on load.
    """

    __tablename__ = "ontology_properties"
    __table_args__ = (
        UniqueConstraint(
            "release_id", "uri", name="uq_ontology_property_uri"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ontology_releases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uri: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    preferred_labels: Mapped[Dict[str, str]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    description: Mapped[Dict[str, str]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    property_type: Mapped[str] = mapped_column(String(16), nullable=False)
    domain_class_uris: Mapped[List[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    range_class_uris: Mapped[List[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    datatype: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    inverse_property_uri: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    temporal: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    provenance_required: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    constraints: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft", nullable=False
    )

    release: Mapped["OntologyReleaseRecord"] = relationship(
        "OntologyReleaseRecord", back_populates="properties"
    )
