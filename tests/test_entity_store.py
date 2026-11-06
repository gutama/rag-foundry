"""Persistence tests for entities, identifiers and mentions (ADR-0012)."""

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rag_foundry.db.models import Base, EntityIdentifierRecord, EntityRecord
from rag_foundry.entities import store as st

EX = "http://example.org/finance#"
ID = "http://id.example.org/entity/"
WS = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
OTHER_WS = uuid.UUID("00000000-0000-4000-8000-0000000000cc")
PROFILE = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
REPO_ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY_REVISION = "c1949d0ff61b"
ENTITY_TABLES = {
    "entities",
    "entity_identifiers",
    "entity_mentions",
    "resolution_candidates",
}


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """Yield a session factory bound to a fresh SQLite schema."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'e.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _bank(store, name="bca", workspace=WS, **kwargs):
    """Create a bank entity."""
    return await store.create_entity(
        workspace_id=workspace,
        semantic_profile_id=PROFILE,
        canonical_uri=ID + name,
        ontology_class_uri=EX + "Bank",
        preferred_labels=kwargs.pop("labels", {"en": name.upper()}),
        **kwargs,
    )


# --- Entities -------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_entity(session_factory):
    """Entities persist with labels, aliases and identifiers."""
    async with session_factory() as session:
        created = await _bank(
            st.EntityStore(session),
            labels={"en": "Bank Central Asia", "id": "BCA"},
            aliases={"en": ["BCA", "Bank BCA"]},
            identifiers={
                "lei": "5493001KJTIIGC8Y1R12",
                "swift_bic": "CENAIDJA",
            },
        )
        await session.commit()

    async with session_factory() as session:
        loaded = await st.EntityStore(session).get_entity(created.id)
    assert loaded.canonical_uri == ID + "bca"
    assert loaded.ontology_class_uri == EX + "Bank"
    assert loaded.preferred_labels == {"en": "Bank Central Asia", "id": "BCA"}
    assert loaded.aliases == {"en": ["BCA", "Bank BCA"]}
    assert loaded.identifiers == {
        "lei": "5493001KJTIIGC8Y1R12",
        "swift_bic": "CENAIDJA",
    }
    assert loaded.status == "active"
    assert loaded.workspace_id == WS
    assert loaded.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_get_missing_entity_raises(session_factory):
    """Unknown entity ids raise EntityNotFoundError."""
    async with session_factory() as session:
        with pytest.raises(st.EntityNotFoundError):
            await st.EntityStore(session).get_entity(uuid.uuid4())


@pytest.mark.asyncio
async def test_canonical_uri_is_unique_per_workspace(session_factory):
    """A workspace cannot hold two entities with one canonical IRI."""
    async with session_factory() as session:
        store = st.EntityStore(session)
        await _bank(store)
        with pytest.raises(st.DuplicateEntityError):
            await _bank(store)
        other = await _bank(store, workspace=OTHER_WS)
    assert other.workspace_id == OTHER_WS


@pytest.mark.asyncio
async def test_identifiers_are_unique_per_scheme(session_factory):
    """An identifier value names at most one entity per workspace."""
    async with session_factory() as session:
        store = st.EntityStore(session)
        await _bank(store, identifiers={"lei": "LEI-1"})
        with pytest.raises(st.DuplicateIdentifierError):
            await _bank(store, "mandiri", identifiers={"lei": "LEI-1"})
        same_value_other_scheme = await _bank(
            store, "bri", identifiers={"swift_bic": "LEI-1"}
        )
        other_workspace = await _bank(
            store, workspace=OTHER_WS, identifiers={"lei": "LEI-1"}
        )
    assert same_value_other_scheme.identifiers == {"swift_bic": "LEI-1"}
    assert other_workspace.identifiers == {"lei": "LEI-1"}


@pytest.mark.asyncio
async def test_identifier_uniqueness_is_enforced_by_the_database(
    session_factory,
):
    """The unique constraint holds even when the store is bypassed."""
    async with session_factory() as session:
        first = await _bank(st.EntityStore(session), identifiers={"lei": "L"})
        second = await _bank(st.EntityStore(session), "bni")
        session.add(
            EntityIdentifierRecord(
                entity_id=second.id, workspace_id=WS, scheme="lei", value="L"
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
    assert first.identifiers == {"lei": "L"}


@pytest.mark.asyncio
async def test_add_identifier(session_factory):
    """Identifiers can be added; conflicts and reuse are refused."""
    async with session_factory() as session:
        store = st.EntityStore(session)
        bca = await _bank(store, identifiers={"lei": "L1"})
        bni = await _bank(store, "bni")
        updated = await store.add_identifier(bca.id, "swift_bic", "CENAIDJA")
        same_again = await store.add_identifier(bca.id, "lei", "L1")
        with pytest.raises(st.DuplicateIdentifierError):
            await store.add_identifier(bca.id, "lei", "L2")
        with pytest.raises(st.DuplicateIdentifierError):
            await store.add_identifier(bni.id, "lei", "L1")
        with pytest.raises(ValueError):
            await store.add_identifier(bni.id, "LEI", "L9")
    assert updated.identifiers == {"lei": "L1", "swift_bic": "CENAIDJA"}
    assert same_again.identifiers == updated.identifiers


@pytest.mark.asyncio
async def test_find_by_identifier(session_factory):
    """Entities can be looked up by a typed identifier."""
    async with session_factory() as session:
        store = st.EntityStore(session)
        bca = await _bank(store, identifiers={"lei": "L1"})
        found = await store.find_by_identifier(WS, "lei", "L1")
        missing = await store.find_by_identifier(WS, "lei", "L2")
        elsewhere = await store.find_by_identifier(OTHER_WS, "lei", "L1")
    assert found.id == bca.id
    assert missing is None and elsewhere is None


@pytest.mark.asyncio
async def test_add_alias(session_factory):
    """Aliases are stored per language; repeats are ignored."""
    async with session_factory() as session:
        store = st.EntityStore(session)
        bca = await _bank(store)
        await store.add_alias(bca.id, "en", "Bank BCA")
        await store.add_alias(bca.id, "id", "PT Bank Central Asia Tbk")
        await store.add_alias(bca.id, "en", "Bank BCA")
        await session.commit()
        with pytest.raises(ValueError):
            await store.add_alias(bca.id, "en_US", "BCA")

    async with session_factory() as session:
        loaded = await st.EntityStore(session).get_entity(bca.id)
    assert loaded.aliases == {
        "en": ["Bank BCA"],
        "id": ["PT Bank Central Asia Tbk"],
    }


@pytest.mark.asyncio
async def test_only_active_entities_can_be_edited(session_factory):
    """Aliases and identifiers cannot be added to inactive entities."""
    async with session_factory() as session:
        store = st.EntityStore(session)
        bca = await _bank(store)
        record = await session.get(EntityRecord, bca.id)
        record.status = "deprecated"
        await session.flush()
        with pytest.raises(st.EntityStateError):
            await store.add_alias(bca.id, "en", "BCA")
        with pytest.raises(st.EntityStateError):
            await store.add_identifier(bca.id, "lei", "L1")


@pytest.mark.asyncio
async def test_list_entities(session_factory):
    """Entities list per workspace and status, sorted by IRI."""
    async with session_factory() as session:
        store = st.EntityStore(session)
        await _bank(store, "mandiri")
        await _bank(store, "bca")
        old = await _bank(store, "bdn")
        await _bank(store, "bri", workspace=OTHER_WS)
        (await session.get(EntityRecord, old.id)).status = "deprecated"
        await session.flush()
        active = await store.list_entities(WS)
        everything = await store.list_entities(WS, statuses=None)
    assert [e.canonical_uri for e in active] == [ID + "bca", ID + "mandiri"]
    assert len(everything) == 3


# --- Mentions -------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_and_get_mention(session_factory):
    """Mentions persist with span, class hint and identifier hints."""
    chunk = uuid.uuid4()
    async with session_factory() as session:
        mention = await st.EntityStore(session).record_mention(
            workspace_id=WS,
            semantic_profile_id=PROFILE,
            chunk_id=chunk,
            start_offset=120,
            end_offset=143,
            surface_text="PT Bank Central Asia Tbk",
            ontology_class_uri=EX + "Bank",
            identifiers={"swift_bic": "CENAIDJA"},
        )
        await session.commit()

    async with session_factory() as session:
        loaded = await st.EntityStore(session).get_mention(mention.id)
    assert loaded.chunk_id == chunk
    assert (loaded.start_offset, loaded.end_offset) == (120, 143)
    assert loaded.surface_text == "PT Bank Central Asia Tbk"
    assert loaded.ontology_class_uri == EX + "Bank"
    assert loaded.identifiers == {"swift_bic": "CENAIDJA"}
    assert loaded.resolution_status == "unresolved"


@pytest.mark.asyncio
async def test_invalid_mention_is_refused(session_factory):
    """Mention fields are validated before anything is stored."""
    async with session_factory() as session:
        with pytest.raises(ValueError):
            await st.EntityStore(session).record_mention(
                workspace_id=WS,
                semantic_profile_id=PROFILE,
                chunk_id=uuid.uuid4(),
                start_offset=5,
                end_offset=2,
                surface_text="BCA",
            )


@pytest.mark.asyncio
async def test_get_missing_mention_raises(session_factory):
    """Unknown mention ids raise MentionNotFoundError."""
    async with session_factory() as session:
        with pytest.raises(st.MentionNotFoundError):
            await st.EntityStore(session).get_mention(uuid.uuid4())


# --- Migrations -----------------------------------------------------------


def _alembic_config(db_path):
    """Build an Alembic config for a SQLite file, without logging setup."""
    config = Config()
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return config


def _tables(db_path):
    """List the tables of a SQLite file."""
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_entity_migration_upgrades_and_downgrades(tmp_path):
    """The entity tables come and go with their migration."""
    db_path = tmp_path / "migrated.db"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")
    assert ENTITY_TABLES <= _tables(db_path)
    command.downgrade(config, ONTOLOGY_REVISION)
    tables = _tables(db_path)
    assert not ENTITY_TABLES & tables
    assert "ontology_releases" in tables
