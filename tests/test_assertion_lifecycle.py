"""Tests for semantic assertion models, storage and lifecycle (ADR-0014)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select

from rag_foundry.assertions import lifecycle as lc
from rag_foundry.assertions import models as am
from rag_foundry.db.models import AssertionRecord
from rag_foundry.entities import store as st

EX = "http://example.org/finance#"
ID = "http://id.example.org/entity/"
WS = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
PROFILE = uuid.UUID("00000000-0000-4000-8000-0000000000bb")


def _assertion(**kwargs):
    """Build an assertion model with sensible defaults."""
    fields = {
        "workspace_id": WS,
        "semantic_profile_id": PROFILE,
        "subject_entity_id": uuid.uuid4(),
        "property_uri": EX + "legalName",
        "literal_value": "PT Bank Central Asia Tbk",
        "source_chunk_ids": [uuid.uuid4()],
        "origin": "extracted",
        "extraction_method": "llm",
        "confidence": 0.8,
    }
    fields.update(kwargs)
    return am.SemanticAssertion(**fields)


# --- Model ----------------------------------------------------------------


def test_assertion_defaults():
    """A new assertion is an unflagged candidate."""
    assertion = _assertion()
    assert assertion.status == "candidate"
    assert assertion.requires_review is False
    assert assertion.review_reason is None
    assert assertion.superseded_by_id is None
    assert assertion.ontology_release_id is None
    assert assertion.created_at.tzinfo is not None


def test_origin_is_required():
    """Every assertion states whether it is curated or extracted."""
    fields = _assertion().model_dump()
    fields.pop("origin")
    with pytest.raises(ValidationError):
        am.SemanticAssertion(**fields)
    with pytest.raises(ValidationError):
        _assertion(origin="inferred")
    assert _assertion(origin="curated").origin == "curated"


def test_exactly_one_of_object_or_literal():
    """An assertion links to an entity or holds a literal, never both."""
    obj = _assertion(literal_value=None, object_entity_id=uuid.uuid4())
    assert obj.object_entity_id is not None
    with pytest.raises(ValidationError):
        _assertion(object_entity_id=uuid.uuid4())
    with pytest.raises(ValidationError):
        _assertion(literal_value=None)


@pytest.mark.parametrize("value", ["text", 7, 1.5, True, False, ""])
def test_literal_values_keep_their_type(value):
    """Literals are strict JSON scalars; no silent coercion."""
    literal = _assertion(literal_value=value).literal_value
    assert literal == value and type(literal) is type(value)


@pytest.mark.parametrize("value", [{"a": 1}, [1, 2]])
def test_structured_literals_are_rejected(value):
    """Only scalar literals are supported."""
    with pytest.raises(ValidationError):
        _assertion(literal_value=value)


@pytest.mark.parametrize(
    "field, value",
    [
        ("property_uri", "legalName"),
        ("confidence", 1.5),
        ("confidence", -0.1),
        ("extraction_method", " "),
        ("status", "published"),
    ],
)
def test_field_validation(field, value):
    """IRIs, confidence, method and status are validated."""
    with pytest.raises(ValidationError):
        _assertion(**{field: value})


def test_evidence_ids_are_unique():
    """A chunk is cited at most once."""
    chunk = uuid.uuid4()
    with pytest.raises(ValidationError):
        _assertion(source_chunk_ids=[chunk, chunk])


def test_validity_interval_is_ordered():
    """valid_from may not come after valid_to."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert _assertion(valid_from=start, valid_to=end).valid_to == end
    with pytest.raises(ValidationError):
        _assertion(valid_from=end, valid_to=start)


def test_review_reason_requires_the_flag():
    """A review reason only makes sense on a flagged assertion."""
    flagged = _assertion(requires_review=True, review_reason="Entity split")
    assert flagged.requires_review
    with pytest.raises(ValidationError):
        _assertion(requires_review=True)
    with pytest.raises(ValidationError):
        _assertion(review_reason="why")


# --- State machine --------------------------------------------------------


def test_allowed_transitions_follow_adr_0014():
    """The lifecycle is exactly the documented state machine."""
    assert lc.ALLOWED_TRANSITIONS == {
        "candidate": {"validated", "invalid"},
        "validated": {"approved", "rejected", "invalid"},
        "approved": {"superseded"},
        "invalid": set(),
        "rejected": set(),
        "superseded": set(),
    }


@pytest.mark.parametrize(
    "current, target",
    [
        ("candidate", "approved"),
        ("candidate", "rejected"),
        ("approved", "candidate"),
        ("approved", "validated"),
        ("invalid", "candidate"),
        ("rejected", "approved"),
        ("superseded", "approved"),
        ("validated", "validated"),
    ],
)
def test_invalid_transitions_raise(current, target):
    """Anything outside the state machine is refused."""
    with pytest.raises(lc.InvalidTransitionError):
        lc.check_transition(current, target)


def test_valid_transition_passes():
    """Allowed transitions return quietly."""
    lc.check_transition("candidate", "validated")
    lc.check_transition("approved", "superseded")


# --- Storage and transitions ----------------------------------------------


async def _entities(session):
    """Create a bank and a regulator; return their ids."""
    store = st.EntityStore(session)
    ids = []
    for name, cls in (("bca", "Bank"), ("ojk", "Regulator")):
        entity = await store.create_entity(
            workspace_id=WS, semantic_profile_id=PROFILE,
            canonical_uri=ID + name, ontology_class_uri=EX + cls,
            preferred_labels={"en": name.upper()},
        )
        ids.append(entity.id)
    return ids


async def _create(store, subject, **kwargs):
    """Create an assertion through the store."""
    fields = {
        "workspace_id": WS,
        "semantic_profile_id": PROFILE,
        "subject_entity_id": subject,
        "property_uri": EX + "legalName",
        "literal_value": "PT Bank Central Asia Tbk",
        "source_chunk_ids": [uuid.uuid4()],
        "origin": "extracted",
        "extraction_method": "llm",
        "extraction_model": "local-llm-7b",
        "extraction_prompt_version": "v2",
        "confidence": 0.8,
    }
    fields.update(kwargs)
    return await store.create_assertion(actor_id="extractor:1", **fields)


@pytest.mark.asyncio
async def test_create_and_get_assertion(session_factory):
    """Assertions persist with provenance and typed literals."""
    async with session_factory() as session:
        bca, ojk = await _entities(session)
        store = lc.AssertionStore(session)
        literal = await _create(store, bca, literal_value=3,
                                property_uri=EX + "riskTier")
        link = await _create(
            store, bca, property_uri=EX + "licensedBy", literal_value=None,
            object_entity_id=ojk, origin="curated",
            extraction_method="steward",
        )
        await session.commit()

    async with session_factory() as session:
        store = lc.AssertionStore(session)
        loaded = await store.get_assertion(literal.id)
        loaded_link = await store.get_assertion(link.id)
    assert loaded.literal_value == 3 and type(loaded.literal_value) is int
    assert loaded.extraction_model == "local-llm-7b"
    assert loaded.extraction_prompt_version == "v2"
    assert loaded.source_chunk_ids == literal.source_chunk_ids
    assert loaded.status == "candidate"
    assert loaded_link.object_entity_id == ojk
    assert loaded_link.literal_value is None
    assert loaded_link.origin == "curated"


@pytest.mark.asyncio
async def test_null_literal_is_stored_as_sql_null(session_factory):
    """Object assertions keep SQL NULL, not JSON null, as literal."""
    async with session_factory() as session:
        bca, ojk = await _entities(session)
        store = lc.AssertionStore(session)
        link = await _create(
            store, bca, property_uri=EX + "licensedBy", literal_value=None,
            object_entity_id=ojk,
        )
        stmt = select(AssertionRecord.id).where(
            AssertionRecord.literal_value.is_(None)
        )
        ids = (await session.execute(stmt)).scalars().all()
    assert ids == [link.id]


@pytest.mark.asyncio
async def test_create_requires_existing_entities(session_factory):
    """Subjects and objects must exist."""
    async with session_factory() as session:
        bca, _ = await _entities(session)
        store = lc.AssertionStore(session)
        with pytest.raises(st.EntityNotFoundError):
            await _create(store, uuid.uuid4())
        with pytest.raises(st.EntityNotFoundError):
            await _create(
                store, bca, literal_value=None,
                object_entity_id=uuid.uuid4(),
            )


@pytest.mark.asyncio
async def test_transitions_are_append_only_and_audited(session_factory):
    """Every status change is logged with actor, reason and time."""
    async with session_factory() as session:
        bca, _ = await _entities(session)
        store = lc.AssertionStore(session)
        assertion = await _create(store, bca)
        await store.transition(
            assertion.id, "validated", actor_id="system:validator"
        )
        approved = await store.transition(
            assertion.id, "approved", actor_id="steward:ana",
            reason="Matches the deed of establishment",
        )
        await session.commit()

    async with session_factory() as session:
        log = await lc.AssertionStore(session).list_transitions(
            assertion.id
        )
    assert approved.status == "approved"
    assert [(t.from_status, t.to_status, t.actor_id) for t in log] == [
        (None, "candidate", "extractor:1"),
        ("candidate", "validated", "system:validator"),
        ("validated", "approved", "steward:ana"),
    ]
    assert log[2].reason == "Matches the deed of establishment"
    assert all(t.created_at.tzinfo is not None for t in log)


@pytest.mark.asyncio
async def test_invalid_store_transitions_change_nothing(session_factory):
    """A refused transition leaves status and log untouched."""
    async with session_factory() as session:
        bca, _ = await _entities(session)
        store = lc.AssertionStore(session)
        assertion = await _create(store, bca)
        with pytest.raises(lc.InvalidTransitionError):
            await store.transition(assertion.id, "approved", actor_id="x")
        current = await store.get_assertion(assertion.id)
        log = await store.list_transitions(assertion.id)
    assert current.status == "candidate"
    assert len(log) == 1


@pytest.mark.asyncio
async def test_superseding_needs_the_dedicated_operation(session_factory):
    """'superseded' is reserved for supersede(), which applies its rules."""
    async with session_factory() as session:
        bca, _ = await _entities(session)
        store = lc.AssertionStore(session)
        assertion = await _create(store, bca)
        await store.transition(assertion.id, "validated", actor_id="v")
        await store.transition(assertion.id, "approved", actor_id="s")
        with pytest.raises(lc.AssertionStateError):
            await store.transition(assertion.id, "superseded", actor_id="s")


@pytest.mark.asyncio
async def test_actors_are_required(session_factory):
    """Creation and transitions name who acted."""
    async with session_factory() as session:
        bca, _ = await _entities(session)
        store = lc.AssertionStore(session)
        with pytest.raises(ValueError):
            await store.create_assertion(
                actor_id=" ", workspace_id=WS, semantic_profile_id=PROFILE,
                subject_entity_id=bca, property_uri=EX + "legalName",
                literal_value="x", source_chunk_ids=[], origin="curated",
                extraction_method="steward", confidence=1.0,
            )
        assertion = await _create(store, bca)
        with pytest.raises(ValueError):
            await store.transition(assertion.id, "validated", actor_id="")


@pytest.mark.asyncio
async def test_missing_assertion_raises(session_factory):
    """Unknown assertion ids raise AssertionNotFoundError."""
    async with session_factory() as session:
        store = lc.AssertionStore(session)
        with pytest.raises(lc.AssertionNotFoundError):
            await store.get_assertion(uuid.uuid4())
        with pytest.raises(lc.AssertionNotFoundError):
            await store.transition(uuid.uuid4(), "validated", actor_id="x")


@pytest.mark.asyncio
async def test_list_assertions_by_entity(session_factory):
    """Assertions can be listed by subject or object entity and status."""
    async with session_factory() as session:
        bca, ojk = await _entities(session)
        store = lc.AssertionStore(session)
        name = await _create(store, bca)
        link = await _create(
            store, bca, property_uri=EX + "licensedBy", literal_value=None,
            object_entity_id=ojk,
        )
        await store.transition(link.id, "validated", actor_id="v")
        about_bca = await store.list_assertions(entity_id=bca)
        about_ojk = await store.list_assertions(entity_id=ojk)
        validated = await store.list_assertions(
            entity_id=bca, statuses=["validated"]
        )
        names = await store.list_assertions(
            workspace_id=WS, property_uri=EX + "legalName"
        )
        elsewhere = await store.list_assertions(workspace_id=uuid.uuid4())
    assert [a.id for a in names] == [name.id]
    assert elsewhere == []
    assert {a.id for a in about_bca} == {name.id, link.id}
    assert [a.id for a in about_ojk] == [link.id]
    assert [a.id for a in validated] == [link.id]


# --- Migration ------------------------------------------------------------


def test_assertion_migration_upgrades_and_downgrades(tmp_path):
    """The assertion tables come and go with their migration."""
    db_path = tmp_path / "migrated.db"
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parent.parent / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")

    def tables():
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            return set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

    assertion_tables = {
        "semantic_assertions",
        "assertion_transitions",
        "assertion_validations",
    }
    command.upgrade(config, "head")
    assert assertion_tables <= tables()
    command.downgrade(config, "c3d54973f560")
    assert not assertion_tables & tables()
    assert "entity_lineage" in tables()
