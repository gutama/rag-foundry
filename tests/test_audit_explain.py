"""Tests for the audit trail and entity-link explanations (FR13)."""

import uuid

import pytest
import pytest_asyncio

from rag_foundry.assertions import lifecycle as lc
from rag_foundry.assertions import validation as av
from rag_foundry.db.models import EntityMentionRecord
from rag_foundry.entities import lineage as lin
from rag_foundry.entities import resolution as res
from rag_foundry.entities import store as st
from rag_foundry.stewardship import audit
from rag_foundry.stewardship import explain as ex
from tests.assertion_helpers import (
    ID,
    PROFILE,
    RELEASE,
    WS,
    create_assertion,
    seed,
)

STEWARD = "steward:ana"
AUTO = res.ResolutionPolicy(policy_id="auto", version="2",
                            auto_approve=True, auto_approve_threshold=0.95)


@pytest_asyncio.fixture
async def world(session_factory):
    """Seed entities and evidence; yield (session, ids)."""
    async with session_factory() as session:
        yield session, await seed(session)


async def _mention(session, text):
    """Record a mention."""
    return await st.EntityStore(session).record_mention(
        workspace_id=WS, semantic_profile_id=PROFILE,
        chunk_id=uuid.uuid4(), start_offset=0, end_offset=len(text),
        surface_text=text,
    )


async def _events(session, **kwargs):
    """List audit events."""
    return await audit.AuditTrail(session).list_events(**kwargs)


def _successors():
    """Two successors for a split."""
    return [
        lin.SuccessorSpec(canonical_uri=ID + "x1",
                          preferred_labels={"en": "X1"}),
        lin.SuccessorSpec(canonical_uri=ID + "x2",
                          preferred_labels={"en": "X2"}),
    ]


# --- Audit events ---------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_is_audited(world):
    """Merges record actor, reason and the survivor."""
    session, ids = world
    await lin.EntityLineageService(session).merge(
        ids["bca"], ids["bca-dup"], actor_id=STEWARD, reason="Duplicate"
    )
    (event,) = await _events(session, event_type="entity.merged")
    assert event.actor_id == STEWARD
    assert (event.resource_type, event.resource_id) == (
        "entity", str(ids["bca-dup"])
    )
    assert event.details["survivor_id"] == str(ids["bca"])
    assert event.details["reason"] == "Duplicate"
    assert event.timestamp.tzinfo is not None


@pytest.mark.asyncio
async def test_split_is_audited(world):
    """Splits record successors and their downstream effects."""
    session, ids = world
    assertion = await create_assertion(session, ids)
    await av.AssertionValidator(session).validate(assertion.id, RELEASE)
    result = await lin.EntityLineageService(session).split(
        ids["bca"], _successors(), actor_id=STEWARD, reason="Conflated"
    )
    (event,) = await _events(session, event_type="entity.split")
    assert event.resource_id == str(ids["bca"])
    assert event.details["successor_ids"] == [
        str(s.id) for s in result.successors
    ]
    assert event.details["flagged_assertion_ids"] == [str(assertion.id)]
    assert event.details["reason"] == "Conflated"


@pytest.mark.asyncio
async def test_resolution_decisions_are_audited(world):
    """Approvals, rejections and policy auto-approvals are recorded."""
    session, ids = world
    service = res.ResolutionService(session)
    approved_mention = await _mention(session, "bca")
    (approved,) = (await service.resolve(approved_mention.id)).candidates
    await service.approve_candidate(approved.id, actor_id=STEWARD,
                                    reason="Register")
    rejected_mention = await _mention(session, "ojk")
    (rejected,) = (await service.resolve(rejected_mention.id)).candidates
    await service.reject_candidate(rejected.id, actor_id=STEWARD,
                                   reason="Wrong")
    auto_mention = await _mention(session, "budi")
    outcome = await service.resolve(auto_mention.id, policy=AUTO)

    events = {
        e.resource_id: e
        for e in await _events(session, event_type="resolution.decision")
    }
    assert events[str(approved.id)].details["decision"] == "approved"
    assert events[str(approved.id)].details["reason"] == "Register"
    assert events[str(approved.id)].details["mention_id"] == \
        str(approved_mention.id)
    assert events[str(rejected.id)].details["decision"] == "rejected"
    auto = events[str(outcome.candidates[0].id)]
    assert auto.actor_id == "policy:auto@2"
    assert auto.details["decision"] == "auto_approved"
    assert auto.details["policy"] == "auto@2"


@pytest.mark.asyncio
async def test_every_assertion_transition_is_audited(world):
    """Creation and each status change leave an audit event."""
    session, ids = world
    assertion = await create_assertion(session, ids)
    await av.AssertionValidator(session).validate(assertion.id, RELEASE)
    await lc.AssertionStore(session).transition(
        assertion.id, "approved", actor_id=STEWARD, reason="OK"
    )
    events = await _events(session, resource_type="assertion",
                           resource_id=assertion.id)
    steps = sorted(
        (e.details["sequence"], e.details["from_status"],
         e.details["to_status"], e.actor_id)
        for e in events
    )
    assert steps == [
        (1, None, "candidate", "extractor:1"),
        (2, "candidate", "validated", "system:validator"),
        (3, "validated", "approved", STEWARD),
    ]
    assert all(e.event_type == "assertion.transition" for e in events)


@pytest.mark.asyncio
async def test_audit_trail_filters(world):
    """Events filter by type and resource."""
    session, ids = world
    await create_assertion(session, ids)
    await lin.EntityLineageService(session).merge(
        ids["bca"], ids["bca-dup"], actor_id=STEWARD, reason="Duplicate"
    )
    everything = await _events(session)
    merges = await _events(session, event_type="entity.merged")
    entity_events = await _events(session, resource_type="entity")
    assert len(everything) == 2
    assert len(merges) == len(entity_events) == 1
    assert await _events(session, resource_id=uuid.uuid4()) == []


# --- Explanations ---------------------------------------------------------


@pytest.mark.asyncio
async def test_explain_a_steward_approved_link(world):
    """The explanation names the candidate, scores, policy and approver."""
    session, ids = world
    mention = await _mention(session, "bca")
    service = res.ResolutionService(session)
    (candidate,) = (await service.resolve(mention.id)).candidates
    await service.approve_candidate(candidate.id, actor_id=STEWARD,
                                    reason="Licence register")

    explanation = await ex.explain_entity_link(session, mention.id)

    assert explanation.mention.id == mention.id
    assert explanation.status == "resolved"
    assert explanation.linked_entity_id == ids["bca"]
    assert explanation.current_entity.id == ids["bca"]
    link = explanation.link_candidate
    assert link.id == candidate.id
    assert link.method == "exact_label"
    assert link.score_breakdown["exact_label"] == 1.0
    assert (link.policy_id, link.policy_version) == ("default", "1")
    assert link.normalizer_version == res.NORMALIZER_VERSION
    assert (link.decided_by, link.decision_reason) == (
        STEWARD, "Licence register"
    )
    assert [c.id for c in explanation.candidates] == [candidate.id]
    assert explanation.redirects == []
    assert [e.details["decision"] for e in explanation.audit_events] == [
        "approved"
    ]
    assert explanation.note is None


@pytest.mark.asyncio
async def test_explain_an_auto_approved_link(world):
    """Auto-approval is attributed to the policy that made it."""
    session, ids = world
    mention = await _mention(session, "bca")
    await res.ResolutionService(session).resolve(mention.id, policy=AUTO)
    explanation = await ex.explain_entity_link(session, mention.id)
    assert explanation.link_candidate.decision == "auto_approved"
    assert explanation.link_candidate.decided_by == "policy:auto@2"


@pytest.mark.asyncio
async def test_explain_follows_merges(world):
    """A link to a merged entity shows the redirect to its survivor."""
    session, ids = world
    mention = await _mention(session, "bca-dup")
    await res.ResolutionService(session).resolve(mention.id, policy=AUTO)
    merge = await lin.EntityLineageService(session).merge(
        ids["bca"], ids["bca-dup"], actor_id=STEWARD, reason="Duplicate"
    )
    explanation = await ex.explain_entity_link(session, mention.id)
    assert explanation.linked_entity_id == ids["bca-dup"]
    assert explanation.current_entity.id == ids["bca"]
    (redirect,) = explanation.redirects
    assert redirect.event_id == merge.event_id
    assert (redirect.predecessor_id, redirect.successor_id) == (
        ids["bca-dup"], ids["bca"]
    )


@pytest.mark.asyncio
async def test_explain_after_a_split(world):
    """A link reset by a split keeps its history and says why."""
    session, ids = world
    mention = await _mention(session, "bca")
    await res.ResolutionService(session).resolve(mention.id, policy=AUTO)
    await lin.EntityLineageService(session).split(
        ids["bca"], _successors(), actor_id=STEWARD, reason="Conflated"
    )
    explanation = await ex.explain_entity_link(session, mention.id)
    assert explanation.status == "unresolved"
    assert explanation.linked_entity_id is None
    assert explanation.current_entity is None
    assert explanation.link_candidate.entity_id == ids["bca"]
    assert "split" in explanation.note


@pytest.mark.asyncio
async def test_explain_an_unresolved_mention(world):
    """Pending mentions list their candidates and nothing else."""
    session, ids = world
    mention = await _mention(session, "bca")
    outcome = await res.ResolutionService(session).resolve(mention.id)
    explanation = await ex.explain_entity_link(session, mention.id)
    assert explanation.status == "candidate"
    assert explanation.link_candidate is None
    assert explanation.current_entity is None
    assert [c.id for c in explanation.candidates] == [
        c.id for c in outcome.candidates
    ]
    assert explanation.audit_events == []
    with pytest.raises(st.MentionNotFoundError):
        await ex.explain_entity_link(session, uuid.uuid4())


@pytest.mark.asyncio
async def test_split_resets_mentions_linked_through_merges(world):
    """A mention linked to A is reset when A's survivor is split."""
    session, ids = world
    mention = await _mention(session, "bca-dup")
    await res.ResolutionService(session).resolve(mention.id, policy=AUTO)
    lineage = lin.EntityLineageService(session)
    await lineage.merge(ids["bca"], ids["bca-dup"], actor_id=STEWARD,
                        reason="Duplicate")
    result = await lineage.split(ids["bca"], _successors(),
                                 actor_id=STEWARD, reason="Conflated")
    stored = await st.EntityStore(session).get_mention(mention.id)
    explanation = await ex.explain_entity_link(session, mention.id)
    assert mention.id in result.reset_mention_ids
    assert stored.resolution_status == "unresolved"
    assert explanation.current_entity is None
    assert "merged" in explanation.note


@pytest.mark.asyncio
async def test_explain_survives_links_that_end_at_a_split(world):
    """Even a link a split did not reset is explained, not raised."""
    session, ids = world
    mention = await _mention(session, "bca-dup")
    await res.ResolutionService(session).resolve(mention.id, policy=AUTO)
    lineage = lin.EntityLineageService(session)
    await lineage.merge(ids["bca"], ids["bca-dup"], actor_id=STEWARD,
                        reason="Duplicate")
    await lineage.split(ids["bca"], _successors(), actor_id=STEWARD,
                        reason="Conflated")
    # Simulate a link written before splits reset merged predecessors.
    record = await session.get(EntityMentionRecord, mention.id)
    record.resolution_status = "resolved"
    record.resolved_entity_id = ids["bca-dup"]
    await session.flush()
    explanation = await ex.explain_entity_link(session, mention.id)
    assert explanation.status == "resolved"
    assert explanation.current_entity is None
    assert [r.successor_id for r in explanation.redirects] == [ids["bca"]]
    assert "split" in explanation.note
