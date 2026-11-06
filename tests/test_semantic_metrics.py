"""Tests for ontology and entity quality metrics (ARCHITECTURE.md §19.3)."""

import uuid

import pytest

from rag_foundry.assertions import curation as cu
from rag_foundry.assertions import lifecycle as lc
from rag_foundry.assertions import validation as av
from rag_foundry.entities import lineage as lin
from rag_foundry.entities import resolution as res
from rag_foundry.entities import store as st
from rag_foundry.stewardship import metrics as mt
from tests.assertion_helpers import (
    ID,
    OTHER_WS,
    PROFILE,
    RELEASE,
    WS,
    create_assertion,
    seed,
)
from tests.ontology_samples import EX

STEWARD = "steward:ana"


async def _mention(session, text):
    """Record a mention in the test workspace."""
    return await st.EntityStore(session).record_mention(
        workspace_id=WS, semantic_profile_id=PROFILE,
        chunk_id=uuid.uuid4(), start_offset=0, end_offset=len(text),
        surface_text=text,
    )


async def _build_dataset(session):
    """Build the fixture dataset described in each test."""
    ids = await seed(session)
    store = st.EntityStore(session)
    # A second "BCA" bank: a duplicate of "bca" after normalization.
    ids["bca-2"] = (await store.create_entity(
        workspace_id=WS, semantic_profile_id=PROFILE,
        canonical_uri=ID + "bca-2", ontology_class_uri=EX + "Bank",
        preferred_labels={"en": "BCA."},
    )).id
    # Same label as ojk but a different class: not a duplicate.
    await store.create_entity(
        workspace_id=WS, semantic_profile_id=PROFILE,
        canonical_uri=ID + "ojk-person", ontology_class_uri=EX + "Person",
        preferred_labels={"en": "OJK"},
    )
    # A duplicate in another workspace never counts here.
    await store.create_entity(
        workspace_id=OTHER_WS, semantic_profile_id=PROFILE,
        canonical_uri=ID + "far-2", ontology_class_uri=EX + "Bank",
        preferred_labels={"en": "far"},
    )

    # Mentions: one resolved, one pending review, two unresolved.
    service = res.ResolutionService(session)
    resolved = await _mention(session, "bca")
    outcome = await service.resolve(resolved.id)
    await service.approve_candidate(
        next(c.id for c in outcome.candidates if c.entity_id == ids["bca"]),
        actor_id=STEWARD,
    )
    await service.resolve((await _mention(session, "ojk")).id)
    await service.resolve((await _mention(session, "zzz")).id)
    await _mention(session, "never resolved")

    validator = av.AssertionValidator(session)
    # a1: validated, evidence resolves, passes.
    a1 = await create_assertion(session, ids)
    await validator.validate(a1.id, RELEASE)
    # a2: curated without evidence (allowed for riskTier), passes.
    a2 = await cu.CurationService(session).create_curated(
        actor_id=STEWARD, workspace_id=WS, semantic_profile_id=PROFILE,
        subject_entity_id=ids["bca"], property_uri=EX + "riskTier",
        literal_value="2",
    )
    await validator.validate(a2.id, RELEASE)
    # a3: live candidate citing a chunk that does not exist.
    await create_assertion(session, ids, prop="foundedOn",
                           literal="1957-02-21",
                           source_chunk_ids=[uuid.uuid4()])
    # a4: fails an ontology constraint (domain) -> invalid.
    a4 = await create_assertion(session, ids, subject="budi",
                                prop="supervises", object="bca")
    await validator.validate(a4.id, RELEASE)
    # a5: fails a non-ontology check (confidence) -> invalid.
    a5 = await create_assertion(session, ids, subject="ojk",
                                confidence=0.3)
    await validator.validate(a5.id, RELEASE)
    # a6: approved, then fails revalidation -> flagged but still approved.
    a6 = await create_assertion(session, ids, subject="bca-dup",
                                confidence=0.6)
    await validator.validate(a6.id, RELEASE)
    await lc.AssertionStore(session).transition(a6.id, "approved",
                                                actor_id=STEWARD)
    await validator.validate(
        a6.id, RELEASE,
        policy=av.AssertionPolicy(policy_id="strict", min_confidence=0.8),
    )
    return ids


@pytest.mark.asyncio
async def test_metrics_on_the_fixture_dataset(session_factory):
    """Each metric matches the hand-computed value for the dataset."""
    async with session_factory() as session:
        await _build_dataset(session)
        metrics = await mt.compute_semantic_metrics(session, WS)

    # Entities: bca, bca-dup, ojk, budi, bca-2, ojk-person are active;
    # bca and bca-2 form one duplicate cluster -> 1 redundant of 6.
    assert (metrics.active_entities, metrics.duplicate_entities) == (6, 1)
    assert metrics.duplicate_entity_rate == pytest.approx(1 / 6)
    # Mentions: 1 resolved, 1 pending, 2 unresolved -> 3 of 4.
    assert (metrics.mentions, metrics.unresolved_mentions) == (4, 3)
    assert metrics.unresolved_mention_rate == pytest.approx(0.75)
    # Live assertions a1, a2, a3, a6; a1 and a6 cite resolvable evidence.
    assert (metrics.live_assertions,
            metrics.assertions_with_provenance) == (4, 2)
    assert metrics.assertion_provenance_coverage == pytest.approx(0.5)
    # Latest reports: a1, a2, a4, a5, a6; only a4 failed an ontology check.
    assert (metrics.validated_assertions,
            metrics.constraint_passes) == (5, 4)
    assert metrics.ontology_constraint_pass_rate == pytest.approx(0.8)
    # Failed latest validation: a4, a5, a6; a6 is still approved.
    assert (metrics.failed_assertions,
            metrics.rejected_failures) == (3, 2)
    assert metrics.invalid_assertion_rejection_rate == pytest.approx(2 / 3)
    assert metrics.workspace_id == WS


@pytest.mark.asyncio
async def test_merged_entities_no_longer_count_as_duplicates(
    session_factory,
):
    """Merging a duplicate brings the rate down: duplicates are controlled."""
    async with session_factory() as session:
        ids = await _build_dataset(session)
        before = await mt.compute_semantic_metrics(session, WS)
        await lin.EntityLineageService(session).merge(
            ids["bca"], ids["bca-2"], actor_id=STEWARD, reason="Duplicate"
        )
        after = await mt.compute_semantic_metrics(session, WS)
    assert before.duplicate_entities == 1
    assert (after.active_entities, after.duplicate_entities) == (5, 0)
    assert after.duplicate_entity_rate == 0.0


@pytest.mark.asyncio
async def test_duplicate_clusters_are_transitive(session_factory):
    """Entities linked through different labels form one cluster."""
    async with session_factory() as session:
        store = st.EntityStore(session)
        for name, labels in [
            ("a", {"en": "Acme"}),
            ("b", {"en": "ACME", "id": "Akme"}),
            ("c", {"id": "akme"}),
        ]:
            await store.create_entity(
                workspace_id=WS, semantic_profile_id=PROFILE,
                canonical_uri=ID + name, ontology_class_uri=EX + "Bank",
                preferred_labels=labels,
            )
        metrics = await mt.compute_semantic_metrics(session, WS)
    assert (metrics.active_entities, metrics.duplicate_entities) == (3, 2)


@pytest.mark.asyncio
async def test_empty_workspace_has_undefined_rates(session_factory):
    """Rates without a denominator are None, not misleading zeros."""
    async with session_factory() as session:
        metrics = await mt.compute_semantic_metrics(session, uuid.uuid4())
    assert metrics.active_entities == metrics.mentions == 0
    for rate in (
        metrics.duplicate_entity_rate,
        metrics.unresolved_mention_rate,
        metrics.assertion_provenance_coverage,
        metrics.ontology_constraint_pass_rate,
        metrics.invalid_assertion_rejection_rate,
    ):
        assert rate is None


@pytest.mark.asyncio
async def test_labels_that_normalize_to_nothing_are_not_duplicates(
    session_factory,
):
    """Punctuation-only labels never make entities look alike."""
    async with session_factory() as session:
        store = st.EntityStore(session)
        for name, label in [("p", "..."), ("q", "***")]:
            await store.create_entity(
                workspace_id=WS, semantic_profile_id=PROFILE,
                canonical_uri=ID + name, ontology_class_uri=EX + "Bank",
                preferred_labels={"en": label},
            )
        metrics = await mt.compute_semantic_metrics(session, WS)
    assert (metrics.active_entities, metrics.duplicate_entities) == (2, 0)
