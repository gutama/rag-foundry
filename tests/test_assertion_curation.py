"""Tests for curated-versus-extracted protection (ADR-0013)."""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from rag_foundry.assertions import curation as cu
from rag_foundry.assertions import lifecycle as lc
from rag_foundry.assertions import validation as av
from tests.assertion_helpers import (
    PROFILE,
    RELEASE,
    WS,
    make_chunk,
    seed,
)
from tests.ontology_samples import EX

STEWARD = "steward:ana"


@pytest_asyncio.fixture
async def world(session_factory):
    """Seed entities and evidence; yield (session, ids)."""
    async with session_factory() as session:
        yield session, await seed(session)


async def _extract(session, ids, subject="bca", prop="legalName",
                   chunk=None, **kwargs):
    """Record an extraction through the curation service."""
    fields = {
        "actor_id": "extractor:1",
        "workspace_id": WS,
        "semantic_profile_id": PROFILE,
        "subject_entity_id": ids[subject],
        "property_uri": EX + prop,
        "extraction_method": "llm",
        "extraction_model": "local-llm-7b",
        "confidence": 0.7,
        "source_chunk_ids": [chunk or ids["chunk"]],
    }
    if "object" in kwargs:
        fields["object_entity_id"] = ids[kwargs.pop("object")]
    else:
        fields["literal_value"] = kwargs.pop("literal", "PT BCA Tbk")
    fields.update(kwargs)
    return await cu.CurationService(session).record_extraction(**fields)


async def _curate(session, ids, subject="bca", prop="legalName", **kwargs):
    """Create a curated assertion."""
    fields = {
        "actor_id": STEWARD,
        "workspace_id": WS,
        "semantic_profile_id": PROFILE,
        "subject_entity_id": ids[subject],
        "property_uri": EX + prop,
        "source_chunk_ids": [ids["chunk"]],
    }
    if "object" in kwargs:
        fields["object_entity_id"] = ids[kwargs.pop("object")]
    else:
        fields["literal_value"] = kwargs.pop("literal", "PT BCA Tbk")
    fields.update(kwargs)
    return await cu.CurationService(session).create_curated(**fields)


async def _approve(session, assertion):
    """Validate and approve an assertion."""
    report = await av.AssertionValidator(session).validate(
        assertion.id, RELEASE
    )
    assert report.valid, report.findings
    return await lc.AssertionStore(session).transition(
        assertion.id, "approved", actor_id=STEWARD, reason="Reviewed"
    )


# --- Recording extractions ------------------------------------------------


@pytest.mark.asyncio
async def test_new_extraction_creates_a_candidate(world):
    """A first extraction becomes an extracted candidate."""
    session, ids = world
    result = await _extract(session, ids)
    assert result.created is True
    assert result.added_evidence == [ids["chunk"]]
    assert result.assertion.origin == "extracted"
    assert result.assertion.status == "candidate"
    assert result.assertion.extraction_model == "local-llm-7b"


@pytest.mark.asyncio
async def test_re_extraction_adds_evidence_without_changing_status(world):
    """Seeing the same fact again strengthens evidence, not authority."""
    session, ids = world
    first = await _extract(session, ids)
    other_chunk = await make_chunk(session)
    again = await _extract(session, ids, chunk=other_chunk, confidence=0.99)
    repeat = await _extract(session, ids, chunk=other_chunk)
    stored = await lc.AssertionStore(session).get_assertion(
        first.assertion.id
    )
    assert again.created is False
    assert again.assertion.id == first.assertion.id
    assert again.added_evidence == [other_chunk]
    assert repeat.added_evidence == []
    assert stored.source_chunk_ids == [ids["chunk"], other_chunk]
    assert stored.status == "candidate"
    assert stored.confidence == 0.7
    assert len(await lc.AssertionStore(session).list_assertions(
        entity_id=ids["bca"]
    )) == 1


@pytest.mark.asyncio
async def test_re_extraction_never_touches_a_curated_assertion(world):
    """Extractions matching curated knowledge only add evidence to it."""
    session, ids = world
    curated = await _approve(session, await _curate(session, ids))
    other_chunk = await make_chunk(session)
    result = await _extract(session, ids, chunk=other_chunk)
    stored = await lc.AssertionStore(session).get_assertion(curated.id)
    assert result.created is False
    assert result.assertion.id == curated.id
    assert stored.origin == "curated"
    assert stored.status == "approved"
    assert stored.extraction_method == "steward"
    assert stored.source_chunk_ids == [ids["chunk"], other_chunk]


@pytest.mark.asyncio
async def test_matching_is_type_strict(world):
    """1, True and '1' are different values."""
    session, ids = world
    results = [
        await _extract(session, ids, prop="riskTier", literal=value)
        for value in (1, True, "1", 1)
    ]
    assert [r.created for r in results] == [True, True, True, False]
    assert results[3].assertion.id == results[0].assertion.id


@pytest.mark.asyncio
async def test_matching_respects_objects_and_validity(world):
    """Different objects or validity intervals are different facts."""
    session, ids = world
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    supervised_bank = await _extract(
        session, ids, subject="ojk", prop="supervises", object="bca"
    )
    supervised_person = await _extract(
        session, ids, subject="ojk", prop="supervises", object="budi"
    )
    since_2020 = await _extract(session, ids, valid_from=start)
    plain = await _extract(session, ids)
    again_since_2020 = await _extract(session, ids, valid_from=start)
    assert supervised_bank.created and supervised_person.created
    assert since_2020.created and plain.created
    assert again_since_2020.assertion.id == since_2020.assertion.id


@pytest.mark.asyncio
async def test_terminal_assertions_are_not_matched(world):
    """A rejected or invalid fact can be extracted afresh."""
    session, ids = world
    first = await _extract(session, ids, confidence=0.1)
    await av.AssertionValidator(session).validate(
        first.assertion.id, RELEASE
    )
    again = await _extract(session, ids)
    assert again.created is True
    assert again.assertion.id != first.assertion.id


@pytest.mark.asyncio
async def test_new_evidence_must_resolve_in_the_workspace(world):
    """Evidence added to an existing assertion is checked first."""
    session, ids = world
    await _extract(session, ids)
    with pytest.raises(ValueError):
        await _extract(session, ids, chunk=uuid.uuid4())
    with pytest.raises(ValueError):
        await _extract(session, ids, chunk=ids["far-chunk"])


@pytest.mark.asyncio
async def test_conflicting_extraction_cannot_displace_curated_value(world):
    """A rival value is a separate candidate that fails maxCount."""
    session, ids = world
    await _approve(session, await _curate(
        session, ids, prop="licenceStatus", literal="active"
    ))
    rival = await _extract(session, ids, prop="licenceStatus",
                           literal="revoked")
    report = await av.AssertionValidator(session).validate(
        rival.assertion.id, RELEASE
    )
    assert rival.created
    assert [f.rule for f in report.findings] == ["max_count"]


@pytest.mark.asyncio
async def test_create_curated(world):
    """Curated assertions are authored by stewards."""
    session, ids = world
    curated = await _curate(session, ids, extraction_method="okf-import")
    log = await lc.AssertionStore(session).list_transitions(curated.id)
    assert curated.origin == "curated"
    assert curated.confidence == 1.0
    assert curated.extraction_method == "okf-import"
    assert log[0].actor_id == STEWARD


# --- Supersession ---------------------------------------------------------


@pytest.mark.asyncio
async def test_approved_assertion_can_be_retired_without_replacement(
    world,
):
    """A steward can retire a fact before approving its successor."""
    session, ids = world
    old = await _approve(session, await _curate(session, ids))
    service = cu.CurationService(session)
    new = await _curate(session, ids, literal="PT Bank Central Asia Tbk")
    store = lc.AssertionStore(session)
    # Retire the old value first; while it is approved, maxCount 1 makes
    # the new name invalid.
    await service.supersede(old.id, None, actor_id=STEWARD,
                            reason="Legal name changed")
    await _approve(session, new)
    stored = await store.get_assertion(old.id)
    log = await store.list_transitions(old.id)
    assert stored.status == "superseded"
    assert stored.superseded_by_id is None
    assert (log[-1].from_status, log[-1].to_status) == (
        "approved", "superseded"
    )
    assert log[-1].reason == "Legal name changed"


@pytest.mark.asyncio
async def test_supersede_records_the_replacement(world):
    """With a replacement, the old assertion points at it."""
    session, ids = world
    old = await _approve(session, await _curate(
        session, ids, prop="supervises", subject="ojk", object="bca"
    ))
    new = await _approve(session, await _curate(
        session, ids, prop="supervises", subject="ojk", object="budi"
    ))
    result = await cu.CurationService(session).supersede(
        old.id, new.id, actor_id=STEWARD, reason="Corrected object"
    )
    assert result.status == "superseded"
    assert result.superseded_by_id == new.id


@pytest.mark.asyncio
async def test_extracted_cannot_supersede_curated(world):
    """Machine output never replaces institutional knowledge."""
    session, ids = world
    curated = await _approve(session, await _curate(
        session, ids, prop="supervises", subject="ojk", object="bca"
    ))
    extracted = await _extract(
        session, ids, subject="ojk", prop="supervises", object="budi"
    )
    await _approve(session, extracted.assertion)
    with pytest.raises(cu.CuratedProtectionError):
        await cu.CurationService(session).supersede(
            curated.id, extracted.assertion.id, actor_id=STEWARD,
            reason="Model says so",
        )
    stored = await lc.AssertionStore(session).get_assertion(curated.id)
    assert stored.status == "approved"


@pytest.mark.asyncio
async def test_other_supersessions_are_allowed(world):
    """Curated may replace extracted, and extracted may replace extracted."""
    session, ids = world
    service = cu.CurationService(session)
    first = await _extract(session, ids, subject="ojk", prop="supervises",
                           object="bca")
    second = await _extract(session, ids, subject="ojk",
                            prop="supervises", object="budi")
    third = await _curate(session, ids, subject="ojk", prop="supervises",
                          object="bca", valid_from=datetime(
                              2021, 1, 1, tzinfo=timezone.utc))
    for assertion in (first.assertion, second.assertion, third):
        await _approve(session, assertion)
    by_extracted = await service.supersede(
        first.assertion.id, second.assertion.id, actor_id=STEWARD,
        reason="newer extraction",
    )
    by_curated = await service.supersede(
        second.assertion.id, third.id, actor_id=STEWARD, reason="curated"
    )
    assert by_extracted.status == by_curated.status == "superseded"


@pytest.mark.asyncio
async def test_supersede_preconditions(world):
    """Both sides approved, distinct, and about the same subject/property."""
    session, ids = world
    service = cu.CurationService(session)
    approved = await _approve(session, await _curate(
        session, ids, subject="ojk", prop="supervises", object="bca"
    ))
    pending = await _curate(session, ids, subject="ojk", prop="supervises",
                            object="budi")
    other_property = await _approve(session, await _curate(session, ids))
    with pytest.raises(lc.AssertionStateError):
        await service.supersede(pending.id, approved.id, actor_id=STEWARD,
                                reason="x")
    with pytest.raises(lc.AssertionStateError):
        await service.supersede(approved.id, pending.id, actor_id=STEWARD,
                                reason="x")
    with pytest.raises(cu.CurationError):
        await service.supersede(approved.id, approved.id, actor_id=STEWARD,
                                reason="x")
    with pytest.raises(cu.CurationError):
        await service.supersede(approved.id, other_property.id,
                                actor_id=STEWARD, reason="x")
    with pytest.raises(ValueError):
        await service.supersede(approved.id, None, actor_id=STEWARD,
                                reason=" ")
