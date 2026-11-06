"""Tests for the versioned OntologyRegistry service (ADR-0011)."""

import uuid

import pytest
from sqlalchemy import func, select

from rag_foundry.db.models import OntologyClassRecord
from rag_foundry.ontology import registry as reg
from rag_foundry.ontology.models import (
    OntologyClass,
    OntologyProperty,
    PropertyConstraint,
)

ONTO = "http://example.org/onto"
EX = ONTO + "#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def _cls(name, parents=(), **kwargs):
    """Build a draft OntologyClass."""
    return OntologyClass(
        uri=EX + name,
        preferred_labels={"en": name},
        parent_class_uris=[EX + p for p in parents],
        **kwargs,
    )


def _object_prop(name, domain, range_, **kwargs):
    """Build a draft object property."""
    return OntologyProperty(
        uri=EX + name,
        preferred_labels={"en": name},
        property_type="object",
        domain_class_uris=[EX + d for d in domain],
        range_class_uris=[EX + r for r in range_],
        **kwargs,
    )


def _data_prop(name, domain, datatype, **kwargs):
    """Build a draft data property."""
    return OntologyProperty(
        uri=EX + name,
        preferred_labels={"en": name},
        property_type="data",
        domain_class_uris=[EX + d for d in domain],
        datatype=XSD + datatype,
        **kwargs,
    )


async def _populated_draft(registry, version="1.0.0"):
    """Create a draft holding a small agent/organization ontology."""
    release = await registry.create_draft(
        ontology_uri=ONTO, version=version, title="Example Ontology"
    )
    for cls in (
        _cls("Agent"),
        _cls("Organization", ["Agent"]),
        _cls("Bank", ["Organization"]),
        _cls("Person", ["Agent"]),
    ):
        await registry.add_class(release.release_id, cls)
    await registry.add_property(
        release.release_id,
        _object_prop("employedBy", ["Person"], ["Organization"]),
    )
    await registry.add_property(
        release.release_id,
        _object_prop(
            "employs", ["Organization"], ["Person"],
            inverse_property_uri=EX + "employedBy",
        ),
    )
    return await registry.add_property(
        release.release_id,
        _data_prop(
            "status", ["Organization"], "string",
            constraints=[
                PropertyConstraint(kind="cardinality", max_count=1),
                PropertyConstraint(
                    kind="allowed_values",
                    allowed_values=["active", "dissolved"],
                ),
            ],
        ),
    )


# --- Drafts ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_draft(session_factory):
    """A new release is an empty, unpublished draft."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        release = await registry.create_draft(
            ontology_uri=ONTO,
            version="1.0.0",
            title="Example Ontology",
            description="First cut",
        )
        await session.commit()

    async with session_factory() as session:
        loaded = await reg.OntologyRegistry(session).get_release(
            release.release_id
        )
    assert loaded.status == "draft"
    assert loaded.version == "1.0.0"
    assert loaded.title == "Example Ontology"
    assert loaded.description == "First cut"
    assert loaded.classes == [] and loaded.properties == []
    assert loaded.published_at is None
    assert loaded.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_create_draft_rejects_duplicate_version(session_factory):
    """Each ontology version can be created once."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        await registry.create_draft(ONTO, "1.0.0", "Example")
        with pytest.raises(reg.DuplicateReleaseError):
            await registry.create_draft(ONTO, "1.0.0", "Again")


@pytest.mark.asyncio
async def test_get_release_missing_raises(session_factory):
    """Unknown release ids raise ReleaseNotFoundError."""
    async with session_factory() as session:
        with pytest.raises(reg.ReleaseNotFoundError):
            await reg.OntologyRegistry(session).get_release(uuid.uuid4())


@pytest.mark.asyncio
async def test_add_terms_persist_and_reload(session_factory):
    """Classes and properties added to a draft survive a reload."""
    async with session_factory() as session:
        release = await _populated_draft(reg.OntologyRegistry(session))
        await session.commit()

    async with session_factory() as session:
        loaded = await reg.OntologyRegistry(session).get_release(
            release.release_id
        )
    assert [c.uri for c in loaded.classes] == sorted(
        EX + n for n in ("Agent", "Organization", "Bank", "Person")
    )
    status = loaded.get_property(EX + "status")
    assert status.datatype == XSD + "string"
    assert status.constraint("cardinality").max_count == 1
    assert status.constraint("allowed_values").allowed_values == [
        "active",
        "dissolved",
    ]
    employs = loaded.get_property(EX + "employs")
    assert employs.inverse_property_uri == EX + "employedBy"
    assert all(c.status == "draft" for c in loaded.classes)


@pytest.mark.asyncio
async def test_add_class_with_undefined_parent_is_rejected(session_factory):
    """A term that would break release consistency is not stored."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        release = await registry.create_draft(ONTO, "1.0.0", "Example")
        with pytest.raises(reg.InvalidReleaseError):
            await registry.add_class(
                release.release_id, _cls("Bank", ["Organization"])
            )
        count = await session.scalar(
            select(func.count()).select_from(OntologyClassRecord)
        )
    assert count == 0


@pytest.mark.asyncio
async def test_add_property_with_undefined_domain_is_rejected(
    session_factory,
):
    """Domain and range classes must already be in the draft."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        release = await registry.create_draft(ONTO, "1.0.0", "Example")
        await registry.add_class(release.release_id, _cls("Person"))
        with pytest.raises(reg.InvalidReleaseError):
            await registry.add_property(
                release.release_id,
                _object_prop("employs", ["Organization"], ["Person"]),
            )


@pytest.mark.asyncio
async def test_add_duplicate_term_is_rejected(session_factory):
    """A class IRI cannot be added twice or reused as a property."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        release = await registry.create_draft(ONTO, "1.0.0", "Example")
        await registry.add_class(release.release_id, _cls("Person"))
        with pytest.raises(reg.InvalidReleaseError):
            await registry.add_class(release.release_id, _cls("Person"))
        with pytest.raises(reg.InvalidReleaseError):
            await registry.add_property(
                release.release_id,
                OntologyProperty(
                    uri=EX + "Person",
                    preferred_labels={"en": "person"},
                    property_type="data",
                    datatype=XSD + "string",
                ),
            )


@pytest.mark.asyncio
async def test_new_terms_must_be_drafts(session_factory):
    """Terms only become approved by publishing their release."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        release = await registry.create_draft(ONTO, "1.0.0", "Example")
        with pytest.raises(reg.InvalidReleaseError):
            await registry.add_class(
                release.release_id, _cls("Person", status="approved")
            )


@pytest.mark.asyncio
async def test_add_term_to_missing_release_raises(session_factory):
    """Editing an unknown release raises ReleaseNotFoundError."""
    async with session_factory() as session:
        with pytest.raises(reg.ReleaseNotFoundError):
            await reg.OntologyRegistry(session).add_class(
                uuid.uuid4(), _cls("Person")
            )


# --- Lookup ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_term_by_iri(session_factory):
    """find_term returns the class or property with the given IRI."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        release = await _populated_draft(registry)
        bank = await registry.find_term(release.release_id, EX + "Bank")
        employs = await registry.find_term(
            release.release_id, EX + "employs"
        )
        with pytest.raises(reg.TermNotFoundError):
            await registry.find_term(release.release_id, EX + "Missing")
    assert isinstance(bank, OntologyClass)
    assert isinstance(employs, OntologyProperty)


@pytest.mark.asyncio
async def test_subclass_closure_after_reload(session_factory):
    """Ancestors and descendants resolve on a persisted release."""
    async with session_factory() as session:
        release = await _populated_draft(reg.OntologyRegistry(session))
        await session.commit()

    async with session_factory() as session:
        loaded = await reg.OntologyRegistry(session).get_release(
            release.release_id
        )
    assert loaded.ancestors(EX + "Bank") == [EX + "Organization", EX + "Agent"]
    assert loaded.descendants(EX + "Agent") == [
        EX + "Organization",
        EX + "Person",
        EX + "Bank",
    ]
    assert loaded.is_subclass_of(EX + "Bank", EX + "Agent")


# --- Publication and immutability -----------------------------------------


@pytest.mark.asyncio
async def test_publish_approves_release_and_draft_terms(session_factory):
    """Publishing approves the release and its draft terms."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        release = await _populated_draft(registry)
        await registry.deprecate_term(release.release_id, EX + "Bank")
        published = await registry.publish(release.release_id)
        await session.commit()

    assert published.status == "approved"
    assert published.published_at is not None
    async with session_factory() as session:
        loaded = await reg.OntologyRegistry(session).get_release(
            release.release_id
        )
    assert loaded.status == "approved"
    assert loaded.published_at is not None
    statuses = {c.uri: c.status for c in loaded.classes}
    assert statuses[EX + "Bank"] == "deprecated"
    assert statuses[EX + "Agent"] == "approved"
    assert all(p.status == "approved" for p in loaded.properties)


@pytest.mark.asyncio
async def test_publish_empty_release_is_rejected(session_factory):
    """A release without classes cannot be published."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        release = await registry.create_draft(ONTO, "1.0.0", "Example")
        with pytest.raises(reg.InvalidReleaseError):
            await registry.publish(release.release_id)


@pytest.mark.asyncio
async def test_approved_release_is_immutable(session_factory):
    """No term or status edit is possible after publication."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        release = await _populated_draft(registry)
        await registry.publish(release.release_id)
        release_id = release.release_id

        with pytest.raises(reg.ReleaseStateError):
            await registry.add_class(release_id, _cls("Government"))
        with pytest.raises(reg.ReleaseStateError):
            await registry.add_property(
                release_id, _data_prop("name", ["Agent"], "string")
            )
        with pytest.raises(reg.ReleaseStateError):
            await registry.deprecate_term(release_id, EX + "Person")
        with pytest.raises(reg.ReleaseStateError):
            await registry.publish(release_id)

        loaded = await registry.get_release(release_id)
    assert loaded.get_class(EX + "Government") is None
    assert loaded.get_class(EX + "Person").status == "approved"


# --- Deprecation ----------------------------------------------------------


@pytest.mark.asyncio
async def test_deprecate_term(session_factory):
    """Draft terms of either kind can be deprecated."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        release = await _populated_draft(registry)
        await registry.deprecate_term(release.release_id, EX + "Bank")
        updated = await registry.deprecate_term(
            release.release_id, EX + "status"
        )
        with pytest.raises(reg.TermNotFoundError):
            await registry.deprecate_term(release.release_id, EX + "Nope")
    assert updated.get_class(EX + "Bank").status == "deprecated"
    assert updated.get_property(EX + "status").status == "deprecated"


@pytest.mark.asyncio
async def test_deprecate_release(session_factory):
    """Only approved releases can be deprecated."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        release = await _populated_draft(registry)
        with pytest.raises(reg.ReleaseStateError):
            await registry.deprecate_release(release.release_id)
        await registry.publish(release.release_id)
        deprecated = await registry.deprecate_release(release.release_id)
        with pytest.raises(reg.ReleaseStateError):
            await registry.deprecate_release(release.release_id)
    assert deprecated.status == "deprecated"


# --- New versions ---------------------------------------------------------


@pytest.mark.asyncio
async def test_create_draft_from_approved_release(session_factory):
    """A new draft copies the terms and records its predecessor."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        first = await _populated_draft(registry)
        await registry.publish(first.release_id)
        second = await registry.create_draft_from(
            first.release_id, version="1.1.0"
        )
        await registry.add_class(
            second.release_id, _cls("CentralBank", ["Bank"])
        )
        await session.commit()

    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        old = await registry.get_release(first.release_id)
        new = await registry.get_release(second.release_id)
    assert new.status == "draft"
    assert new.previous_release_id == first.release_id
    assert new.title == old.title
    assert new.ontology_uri == ONTO
    assert new.get_class(EX + "Bank").status == "approved"
    assert new.get_class(EX + "CentralBank").status == "draft"
    assert old.get_class(EX + "CentralBank") is None
    assert {p.uri for p in new.properties} == {p.uri for p in old.properties}


@pytest.mark.asyncio
async def test_create_draft_from_rules(session_factory):
    """Derive only from published releases, with a fresh version."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        first = await _populated_draft(registry)
        with pytest.raises(reg.ReleaseStateError):
            await registry.create_draft_from(first.release_id, "1.1.0")
        await registry.publish(first.release_id)
        with pytest.raises(reg.DuplicateReleaseError):
            await registry.create_draft_from(first.release_id, "1.0.0")
        with pytest.raises(reg.ReleaseNotFoundError):
            await registry.create_draft_from(uuid.uuid4(), "9.9.9")


@pytest.mark.asyncio
async def test_list_releases_and_latest_approved(session_factory):
    """Releases list oldest first; latest_approved finds the newest."""
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        assert await registry.latest_approved(ONTO) is None
        first = await _populated_draft(registry, "1.0.0")
        await registry.publish(first.release_id)
        second = await registry.create_draft_from(first.release_id, "1.1.0")
        await registry.publish(second.release_id)
        await registry.create_draft_from(second.release_id, "1.2.0")
        await registry.create_draft("http://example.org/other", "1", "Other")

        releases = await registry.list_releases(ONTO)
        latest = await registry.latest_approved(ONTO)
    assert [r.version for r in releases] == ["1.0.0", "1.1.0", "1.2.0"]
    assert latest.version == "1.1.0"
