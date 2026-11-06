"""Tests for the assertion validation pipeline (ADR-0011, ADR-0014)."""

import uuid

import pytest
import pytest_asyncio

from rag_foundry.assertions import lifecycle as lc
from rag_foundry.assertions import validation as av
from rag_foundry.db.models import EntityRecord
from rag_foundry.entities import lineage as lin
from tests.assertion_helpers import (
    ID,
    RELEASE,
    create_assertion,
    seed,
)
from tests.ontology_samples import build_finance_release


@pytest_asyncio.fixture
async def world(session_factory):
    """Seed entities and evidence; yield (session, ids)."""
    async with session_factory() as session:
        yield session, await seed(session)


_assert = create_assertion


async def _validate(session, assertion, **kwargs):
    """Validate an assertion against the approved sample release."""
    return await av.AssertionValidator(session).validate(
        assertion.id, RELEASE, **kwargs
    )


def _errors(report):
    """List the error rules of a report."""
    return [f.rule for f in report.findings if f.severity == "error"]


async def _status(session, assertion):
    """Reload an assertion's status."""
    return (await lc.AssertionStore(session).get_assertion(assertion.id)) \
        .status


# --- Valid assertions -----------------------------------------------------


@pytest.mark.asyncio
async def test_valid_candidate_becomes_validated(world):
    """A sound assertion passes and records a pinned report."""
    session, ids = world
    assertion = await _assert(session, ids)
    report = await _validate(session, assertion)
    stored = await lc.AssertionStore(session).get_assertion(assertion.id)
    log = await lc.AssertionStore(session).list_transitions(assertion.id)
    assert report.valid
    assert report.findings == []
    assert report.ontology_release_id == RELEASE.release_id
    assert report.ontology_version == "1.0.0"
    assert (report.policy_id, report.policy_version) == ("default", "1")
    assert report.created_at.tzinfo is not None
    assert stored.status == "validated"
    assert stored.ontology_release_id == RELEASE.release_id
    assert (log[-1].from_status, log[-1].to_status, log[-1].actor_id) == (
        "candidate", "validated", "system:validator"
    )


@pytest.mark.asyncio
async def test_object_assertion_with_subclasses_is_valid(world):
    """Domain and range checks use the pinned release's hierarchy."""
    session, ids = world
    assertion = await _assert(session, ids, prop="licensedBy",
                              object="ojk")
    # licensedBy restricts allowed values to the ojk and bankIndonesia
    # IRIs, which our entity's canonical IRI is not.
    report = await _validate(session, assertion)
    assert _errors(report) == ["allowed_values"]
    supervises = await _assert(session, ids, subject="ojk",
                               prop="supervises", object="bca")
    assert (await _validate(session, supervises)).valid


# --- Evidence -------------------------------------------------------------


@pytest.mark.asyncio
async def test_extracted_assertions_need_evidence(world):
    """No evidence means the assertion cannot be validated."""
    session, ids = world
    assertion = await _assert(session, ids, source_chunk_ids=[])
    report = await _validate(session, assertion)
    assert _errors(report) == ["missing_evidence"]
    assert await _status(session, assertion) == "invalid"


@pytest.mark.asyncio
async def test_evidence_must_resolve(world):
    """Cited chunks must exist."""
    session, ids = world
    assertion = await _assert(
        session, ids, source_chunk_ids=[ids["chunk"], uuid.uuid4()]
    )
    assert _errors(await _validate(session, assertion)) == [
        "unknown_evidence"
    ]


@pytest.mark.asyncio
async def test_evidence_must_share_the_workspace(world):
    """Evidence from another workspace is refused (ADR-0005)."""
    session, ids = world
    assertion = await _assert(
        session, ids, source_chunk_ids=[ids["far-chunk"]]
    )
    assert _errors(await _validate(session, assertion)) == [
        "evidence_workspace"
    ]


@pytest.mark.asyncio
async def test_curated_evidence_follows_provenance_required(world):
    """Curated assertions skip evidence only where the property allows."""
    session, ids = world
    tier = await _assert(
        session, ids, prop="riskTier", literal="2", origin="curated",
        extraction_method="steward", source_chunk_ids=[],
    )
    name = await _assert(
        session, ids, origin="curated", extraction_method="steward",
        source_chunk_ids=[],
    )
    assert (await _validate(session, tier)).valid
    assert _errors(await _validate(session, name)) == ["missing_evidence"]


# --- Ontology constraints -------------------------------------------------


@pytest.mark.asyncio
async def test_domain_violation_is_invalid(world):
    """A person cannot be licensed by a regulator in this ontology."""
    session, ids = world
    assertion = await _assert(session, ids, subject="budi",
                              prop="supervises", object="bca")
    assert _errors(await _validate(session, assertion)) == ["domain"]
    assert await _status(session, assertion) == "invalid"


@pytest.mark.asyncio
async def test_range_violation_is_invalid(world):
    """Regulators supervise banks or persons, not regulators."""
    session, ids = world
    assertion = await _assert(session, ids, subject="ojk",
                              prop="supervises", object="ojk")
    assert _errors(await _validate(session, assertion)) == ["range"]


@pytest.mark.asyncio
async def test_datatype_violation_is_invalid(world):
    """Literals must fit the property's datatype."""
    session, ids = world
    assertion = await _assert(session, ids, prop="foundedOn",
                              literal="1957-02-30")
    assert _errors(await _validate(session, assertion)) == ["datatype"]


@pytest.mark.asyncio
async def test_unknown_property_is_invalid(world):
    """Properties outside the pinned release are refused."""
    session, ids = world
    assertion = await _assert(session, ids, prop="nickname")
    assert _errors(await _validate(session, assertion)) == [
        "unknown_property"
    ]


@pytest.mark.asyncio
async def test_cardinality_counts_validated_and_approved(world):
    """A second legal name for one bank exceeds maxCount 1."""
    session, ids = world
    first = await _assert(session, ids, literal="PT BCA Tbk")
    second = await _assert(session, ids, literal="Bank BCA")
    assert (await _validate(session, first)).valid
    report = await _validate(session, second)
    assert _errors(report) == ["max_count"]


@pytest.mark.asyncio
async def test_cardinality_ignores_invalid_assertions(world):
    """Only validated and approved assertions count towards the limit."""
    session, ids = world
    first = await _assert(session, ids, source_chunk_ids=[])
    await _validate(session, first)
    second = await _assert(session, ids, literal="Bank BCA")
    assert (await _validate(session, second)).valid


# --- Entities -------------------------------------------------------------


@pytest.mark.asyncio
async def test_merged_entities_are_followed_and_re_pointed(world):
    """A merged subject redirects to its survivor, noted in the report."""
    session, ids = world
    assertion = await _assert(session, ids, subject="bca-dup")
    await lin.EntityLineageService(session).merge(
        ids["bca"], ids["bca-dup"], actor_id="steward:ana", reason="dup"
    )
    report = await _validate(session, assertion)
    stored = await lc.AssertionStore(session).get_assertion(assertion.id)
    assert report.valid
    assert [f.rule for f in report.findings] == ["entity_redirected"]
    assert report.findings[0].severity == "info"
    assert stored.subject_entity_id == ids["bca"]


@pytest.mark.asyncio
async def test_split_entities_make_the_assertion_invalid(world):
    """A split subject has no single successor; the reason is recorded."""
    session, ids = world
    assertion = await _assert(session, ids)
    await lin.EntityLineageService(session).split(
        ids["bca"],
        [lin.SuccessorSpec(canonical_uri=ID + "bca-1",
                           preferred_labels={"en": "BCA 1"}),
         lin.SuccessorSpec(canonical_uri=ID + "bca-2",
                           preferred_labels={"en": "BCA 2"})],
        actor_id="steward:ana", reason="conflated",
    )
    report = await _validate(session, assertion)
    assert _errors(report) == ["entity_split"]
    assert str(ids["bca"]) in report.findings[0].message
    assert await _status(session, assertion) == "invalid"


@pytest.mark.asyncio
async def test_inactive_and_foreign_entities_are_invalid(world):
    """Deprecated entities and other workspaces are refused."""
    session, ids = world
    (await session.get(EntityRecord, ids["ojk"])).status = "deprecated"
    await session.flush()
    deprecated = await _assert(session, ids, subject="ojk",
                               prop="supervises", object="bca")
    foreign = await _assert(session, ids, subject="far")
    assert _errors(await _validate(session, deprecated)) == [
        "entity_inactive"
    ]
    assert _errors(await _validate(session, foreign)) == [
        "entity_workspace"
    ]


# --- Policy ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_confidence_policy(world):
    """Low-confidence assertions fail unless the policy allows them."""
    session, ids = world
    strict = await _assert(session, ids, confidence=0.3)
    lenient = await _assert(session, ids, subject="ojk", confidence=0.3)
    policy = av.AssertionPolicy(policy_id="lenient", version="2",
                                min_confidence=0.2)
    assert _errors(await _validate(session, strict)) == ["low_confidence"]
    report = await _validate(session, lenient, policy=policy)
    assert report.valid
    assert (report.policy_id, report.policy_version) == ("lenient", "2")


def test_policy_is_frozen_and_validated():
    """Assertion policies are immutable values with checked ranges."""
    assert av.DEFAULT_ASSERTION_POLICY.min_confidence == 0.5
    with pytest.raises(ValueError):
        av.AssertionPolicy(min_confidence=1.5)
    with pytest.raises(ValueError):
        av.DEFAULT_ASSERTION_POLICY.min_confidence = 0.1


# --- Lifecycle interaction ------------------------------------------------


@pytest.mark.asyncio
async def test_failed_revalidation_invalidates_a_validated_assertion(world):
    """Re-validation with a stricter policy can demote to invalid."""
    session, ids = world
    assertion = await _assert(session, ids, confidence=0.6)
    assert (await _validate(session, assertion)).valid
    strict = av.AssertionPolicy(policy_id="strict", min_confidence=0.8)
    report = await _validate(session, assertion, policy=strict)
    assert _errors(report) == ["low_confidence"]
    assert await _status(session, assertion) == "invalid"


@pytest.mark.asyncio
async def test_passing_revalidation_keeps_validated(world):
    """Re-validating a sound assertion changes nothing but the history."""
    session, ids = world
    assertion = await _assert(session, ids)
    await _validate(session, assertion)
    await _validate(session, assertion)
    log = await lc.AssertionStore(session).list_transitions(assertion.id)
    reports = await av.AssertionValidator(session).list_reports(
        assertion.id
    )
    latest = await av.AssertionValidator(session).latest_report(
        assertion.id
    )
    assert await _status(session, assertion) == "validated"
    assert len(log) == 2
    assert len(reports) == 2
    assert latest.id == reports[-1].id


@pytest.mark.asyncio
async def test_terminal_assertions_cannot_be_validated(world):
    """Invalid and rejected assertions stay as they are."""
    session, ids = world
    assertion = await _assert(session, ids, source_chunk_ids=[])
    await _validate(session, assertion)
    with pytest.raises(lc.AssertionStateError):
        await _validate(session, assertion)


@pytest.mark.asyncio
async def test_validation_needs_an_approved_release(world):
    """Assertions are validated only against published releases."""
    session, ids = world
    assertion = await _assert(session, ids)
    with pytest.raises(ValueError):
        await av.AssertionValidator(session).validate(
            assertion.id, build_finance_release()
        )
    assert await av.AssertionValidator(session).latest_report(
        assertion.id
    ) is None
