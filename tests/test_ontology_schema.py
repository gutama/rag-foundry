"""Persistence tests for ontology releases, classes and properties."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from rag_foundry.db.models import (
    Base,
    OntologyClassRecord,
    OntologyPropertyRecord,
    OntologyReleaseRecord,
)

EX = "http://example.org/onto#"
XSD = "http://www.w3.org/2001/XMLSchema#"
REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_REVISION = "a545ddc30037"
ONTOLOGY_TABLES = {
    "ontology_releases",
    "ontology_classes",
    "ontology_properties",
}


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """Yield a session factory bound to a fresh SQLite schema."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'o.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _release(version="1.0.0", **kwargs):
    """Build an OntologyReleaseRecord."""
    return OntologyReleaseRecord(
        id=uuid.uuid4(),
        ontology_uri="http://example.org/onto",
        version=version,
        title="Example Ontology",
        **kwargs,
    )


def _class(name, **kwargs):
    """Build an OntologyClassRecord."""
    return OntologyClassRecord(
        uri=EX + name, preferred_labels={"en": name}, **kwargs
    )


@pytest.mark.asyncio
async def test_release_round_trip(session_factory):
    """A release with classes and properties persists and reloads intact."""
    release = _release(description="First cut")
    release.classes = [
        _class("Organization"),
        _class(
            "Bank",
            parent_class_uris=[EX + "Organization"],
            description={"en": "A licensed bank"},
            identity_rules=["same national bank code"],
        ),
    ]
    release.properties = [
        OntologyPropertyRecord(
            uri=EX + "status",
            preferred_labels={"en": "status", "id": "status"},
            property_type="data",
            domain_class_uris=[EX + "Organization"],
            datatype=XSD + "string",
            temporal=True,
            provenance_required=False,
            constraints=[
                {"kind": "cardinality", "min_count": None, "max_count": 1,
                 "allowed_values": []},
            ],
        )
    ]
    async with session_factory() as session:
        session.add(release)
        await session.commit()

    async with session_factory() as session:
        stmt = (
            select(OntologyReleaseRecord)
            .where(OntologyReleaseRecord.id == release.id)
            .options(
                selectinload(OntologyReleaseRecord.classes),
                selectinload(OntologyReleaseRecord.properties),
            )
        )
        loaded = (await session.execute(stmt)).scalar_one()

    assert loaded.status == "draft"
    assert loaded.description == "First cut"
    assert loaded.previous_release_id is None
    assert loaded.published_at is None
    assert loaded.created_at is not None
    classes = {c.uri: c for c in loaded.classes}
    assert set(classes) == {EX + "Organization", EX + "Bank"}
    bank = classes[EX + "Bank"]
    assert bank.parent_class_uris == [EX + "Organization"]
    assert bank.description == {"en": "A licensed bank"}
    assert bank.identity_rules == ["same national bank code"]
    assert bank.status == "draft"
    assert classes[EX + "Organization"].parent_class_uris == []

    (prop,) = loaded.properties
    assert prop.property_type == "data"
    assert prop.preferred_labels == {"en": "status", "id": "status"}
    assert prop.datatype == XSD + "string"
    assert prop.range_class_uris == []
    assert prop.inverse_property_uri is None
    assert prop.temporal is True
    assert prop.provenance_required is False
    assert prop.constraints[0]["max_count"] == 1
    assert prop.release_id == release.id


@pytest.mark.asyncio
async def test_release_lineage_and_publication_columns(session_factory):
    """A release can point at the release it was derived from."""
    published_at = datetime(2026, 11, 6, tzinfo=timezone.utc)
    first = _release(status="approved", published_at=published_at)
    second = _release(version="1.1.0", previous_release_id=first.id)
    async with session_factory() as session:
        session.add_all([first, second])
        await session.commit()

    async with session_factory() as session:
        loaded = await session.get(OntologyReleaseRecord, second.id)
        loaded_first = await session.get(OntologyReleaseRecord, first.id)
    assert loaded.previous_release_id == first.id
    assert loaded_first.status == "approved"
    assert loaded_first.published_at.replace(tzinfo=timezone.utc) == (
        published_at
    )


@pytest.mark.asyncio
async def test_release_version_is_unique_per_ontology(session_factory):
    """Two releases of one ontology cannot share a version."""
    async with session_factory() as session:
        session.add_all([_release(), _release()])
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_class_iri_is_unique_within_a_release(session_factory):
    """A release cannot hold two classes with the same IRI."""
    release = _release()
    release.classes = [_class("Bank"), _class("Bank")]
    async with session_factory() as session:
        session.add(release)
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_property_iri_is_unique_within_a_release(session_factory):
    """A release cannot hold two properties with the same IRI."""
    release = _release()
    release.properties = [
        OntologyPropertyRecord(
            uri=EX + "name",
            preferred_labels={"en": "name"},
            property_type="data",
            datatype=XSD + "string",
        )
        for _ in range(2)
    ]
    async with session_factory() as session:
        session.add(release)
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_same_iri_can_appear_in_successive_releases(session_factory):
    """Term IRIs stay stable across releases (ADR-0011)."""
    first, second = _release(), _release(version="2.0.0")
    first.classes = [_class("Bank")]
    second.classes = [_class("Bank")]
    async with session_factory() as session:
        session.add_all([first, second])
        await session.commit()
        rows = (
            await session.execute(
                select(OntologyClassRecord).where(
                    OntologyClassRecord.uri == EX + "Bank"
                )
            )
        ).scalars().all()
    assert {row.release_id for row in rows} == {first.id, second.id}


# --- Migrations -----------------------------------------------------------


def _alembic_config(db_path):
    """Build an Alembic config for a SQLite file, without logging setup."""
    config = Config()
    config.set_main_option(
        "script_location", str(REPO_ROOT / "migrations")
    )
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return config


def test_migrations_create_ontology_tables(tmp_path):
    """Upgrading to head creates the ontology tables."""
    db_path = tmp_path / "migrated.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert ONTOLOGY_TABLES <= tables


def test_migrations_match_orm_models(tmp_path):
    """The schema at head has no drift from the ORM metadata."""
    db_path = tmp_path / "migrated.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            diff = compare_metadata(
                MigrationContext.configure(conn), Base.metadata
            )
    finally:
        engine.dispose()
    assert diff == []


def test_ontology_migration_downgrades_cleanly(tmp_path):
    """Downgrading to the baseline removes only the ontology tables."""
    db_path = tmp_path / "migrated.db"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")
    command.downgrade(config, BASELINE_REVISION)
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert not ONTOLOGY_TABLES & tables
    assert {"documents", "chunks", "taxonomy_concepts"} <= tables
