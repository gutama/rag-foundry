"""Tests for the effect of entity merges and splits on assertions."""

import pytest
import pytest_asyncio

from rag_foundry.assertions import lifecycle as lc
from rag_foundry.assertions import validation as av
from rag_foundry.entities import lineage as lin
from tests.assertion_helpers import ID, RELEASE, create_assertion, seed

STEWARD = "steward:ana"


@pytest_asyncio.fixture
async def world(session_factory):
    """Seed entities and evidence; yield (session, ids)."""
    async with session_factory() as session:
        yield session, await seed(session)


async def _approved(session, ids, **kwargs):
    """Create, validate and approve an assertion."""
    assertion = await create_assertion(session, ids, **kwargs)
    report = await av.AssertionValidator(session).validate(
        assertion.id, RELEASE
    )
    assert report.valid, report.findings
    return await lc.AssertionStore(session).transition(
        assertion.id, "approved", actor_id=STEWARD
    )


def _successors():
    """Two successors for splitting bca."""
    return [
        lin.SuccessorSpec(canonical_uri=ID + "bca-holding",
                          preferred_labels={"en": "BCA Holding"}),
        lin.SuccessorSpec(canonical_uri=ID + "bca-bank",
                          preferred_labels={"en": "BCA Bank"}),
    ]


async def _get(session, assertion):
    """Reload an assertion."""
    return await lc.AssertionStore(session).get_assertion(assertion.id)


# --- Splits ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_split_flags_validated_and_approved_assertions(world):
    """Trusted assertions about a split entity are flagged, not demoted."""
    session, ids = world
    as_subject = await _approved(session, ids)
    as_object = await _approved(session, ids, subject="ojk",
                                prop="supervises", object="bca")
    validated = await create_assertion(session, ids, prop="foundedOn",
                                       literal="1957-02-21")
    await av.AssertionValidator(session).validate(validated.id, RELEASE)
    candidate = await create_assertion(session, ids, prop="riskTier",
                                       literal="2")
    unrelated = await _approved(session, ids, subject="ojk")

    result = await lin.EntityLineageService(session).split(
        ids["bca"], _successors(), actor_id=STEWARD, reason="Conflated"
    )

    assert set(result.flagged_assertion_ids) == {
        as_subject.id, as_object.id, validated.id
    }
    for assertion in (as_subject, as_object):
        stored = await _get(session, assertion)
        assert stored.status == "approved"
        assert stored.requires_review is True
        assert str(ids["bca"]) in stored.review_reason
        assert str(result.event_id) in stored.review_reason
    assert (await _get(session, validated)).status == "validated"
    assert (await _get(session, candidate)).requires_review is False
    assert (await _get(session, unrelated)).requires_review is False


@pytest.mark.asyncio
async def test_revalidating_a_split_flagged_assertion_keeps_it_flagged(
    world,
):
    """The flag stays until a steward restates the fact."""
    session, ids = world
    approved = await _approved(session, ids)
    await lin.EntityLineageService(session).split(
        ids["bca"], _successors(), actor_id=STEWARD, reason="Conflated"
    )
    report = await av.AssertionValidator(session).validate(
        approved.id, RELEASE
    )
    stored = await _get(session, approved)
    assert [f.rule for f in report.findings] == ["entity_split"]
    assert stored.status == "approved"
    assert stored.requires_review is True
    assert "entity_split" in stored.review_reason


# --- Merges ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_revalidation_re_points_approved_assertions(world):
    """After a merge, revalidation moves references to the survivor."""
    session, ids = world
    approved = await _approved(session, ids, subject="bca-dup")
    await lin.EntityLineageService(session).merge(
        ids["bca"], ids["bca-dup"], actor_id=STEWARD, reason="Duplicate"
    )
    report = await av.AssertionValidator(session).validate(
        approved.id, RELEASE
    )
    stored = await _get(session, approved)
    log = await lc.AssertionStore(session).list_transitions(approved.id)
    assert report.valid
    assert [f.rule for f in report.findings] == ["entity_redirected"]
    assert stored.subject_entity_id == ids["bca"]
    assert stored.status == "approved"
    assert stored.requires_review is False
    assert [t.to_status for t in log] == ["candidate", "validated",
                                          "approved"]


@pytest.mark.asyncio
async def test_revalidate_for_entity_after_merge(world):
    """All live assertions naming a merged entity are re-pointed."""
    session, ids = world
    subject_side = await _approved(session, ids, subject="bca-dup")
    object_side = await _approved(session, ids, subject="ojk",
                                  prop="supervises", object="bca-dup")
    candidate = await create_assertion(session, ids, subject="bca-dup",
                                       prop="riskTier", literal="1")
    invalid = await create_assertion(session, ids, subject="bca-dup",
                                     prop="riskTier", literal="9")
    await av.AssertionValidator(session).validate(invalid.id, RELEASE)
    await lin.EntityLineageService(session).merge(
        ids["bca"], ids["bca-dup"], actor_id=STEWARD, reason="Duplicate"
    )

    reports = await av.AssertionValidator(session).revalidate_for_entity(
        ids["bca-dup"], RELEASE
    )

    assert {r.assertion_id for r in reports} == {
        subject_side.id, object_side.id, candidate.id
    }
    assert all(r.valid for r in reports)
    assert (await _get(session, subject_side)).subject_entity_id == \
        ids["bca"]
    assert (await _get(session, object_side)).object_entity_id == ids["bca"]
    assert (await _get(session, candidate)).status == "validated"
    assert (await _get(session, invalid)).subject_entity_id == \
        ids["bca-dup"]


# --- Approved revalidation in general --------------------------------------


@pytest.mark.asyncio
async def test_failed_revalidation_flags_but_never_demotes_approval(world):
    """Approval is never withdrawn silently; the assertion is flagged."""
    session, ids = world
    approved = await _approved(session, ids, confidence=0.6)
    strict = av.AssertionPolicy(policy_id="strict", min_confidence=0.8)
    validator = av.AssertionValidator(session)
    report = await validator.validate(approved.id, RELEASE, policy=strict)
    flagged = await _get(session, approved)
    assert not report.valid
    assert flagged.status == "approved"
    assert flagged.requires_review is True
    assert flagged.review_reason == "Failed checks: low_confidence"

    await validator.validate(approved.id, RELEASE)
    cleared = await _get(session, approved)
    assert cleared.requires_review is False
    assert cleared.review_reason is None
