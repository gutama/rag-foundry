"""Tests for resolution policies, stored candidates and decisions."""

import uuid

import pytest
from pydantic import ValidationError

from rag_foundry.db.models import EntityRecord
from rag_foundry.entities import resolution as res
from rag_foundry.entities import store as st
from tests.ontology_samples import EX, build_finance_release

WS = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
PROFILE = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
ID = "http://id.example.org/entity/"
AUTO = res.ResolutionPolicy(
    policy_id="trusted-names", version="3", auto_approve=True,
    auto_approve_threshold=0.95,
)


async def _seed(session):
    """Create banks and return their ids by name."""
    store = st.EntityStore(session)
    ids = {}
    for name, labels, aliases, identifiers in [
        ("bca", {"en": "Bank Central Asia"}, {"en": ["BCA"]},
         {"swift_bic": "CENAIDJA"}),
        ("bri", {"en": "Bank Rakyat Indonesia"}, {"en": ["BRI"]}, {}),
        ("bri-dup", {"en": "Bank Rakyat Indonesia"}, {}, {}),
    ]:
        entity = await store.create_entity(
            workspace_id=WS, semantic_profile_id=PROFILE,
            canonical_uri=ID + name, ontology_class_uri=EX + "Bank",
            preferred_labels=labels, aliases=aliases,
            identifiers=identifiers,
        )
        ids[name] = entity.id
    return ids


async def _mention(session, text, **kwargs):
    """Record a mention in the test workspace."""
    return await st.EntityStore(session).record_mention(
        workspace_id=WS, semantic_profile_id=PROFILE,
        chunk_id=uuid.uuid4(), start_offset=0, end_offset=len(text),
        surface_text=text, **kwargs,
    )


# --- Policy ---------------------------------------------------------------


def test_default_policy_never_auto_approves():
    """The default policy sends every candidate to review."""
    assert res.DEFAULT_POLICY.auto_approve is False
    assert res.DEFAULT_POLICY.key == "default@1"


def test_policy_is_immutable_and_validated():
    """Policies are frozen values with checked ranges."""
    with pytest.raises(ValidationError):
        res.DEFAULT_POLICY.auto_approve = True
    for bad in (
        {"auto_approve_threshold": 1.2},
        {"min_similarity": -0.1},
        {"max_candidates": 0},
        {"policy_id": " "},
        {"version": ""},
    ):
        with pytest.raises(ValidationError):
            res.ResolutionPolicy(**bad)


# --- Resolving mentions ---------------------------------------------------


@pytest.mark.asyncio
async def test_default_policy_keeps_even_identifier_matches_pending(
    session_factory,
):
    """Without an explicit policy, a perfect match still needs review."""
    async with session_factory() as session:
        ids = await _seed(session)
        mention = await _mention(
            session, "BCA", identifiers={"swift_bic": "CENAIDJA"}
        )
        outcome = await res.ResolutionService(session).resolve(mention.id)
    assert outcome.auto_approved is False
    assert outcome.mention.resolution_status == "candidate"
    assert outcome.mention.resolved_entity_id is None
    (candidate,) = outcome.candidates
    assert candidate.entity_id == ids["bca"]
    assert candidate.score == 1.0
    assert candidate.decision == "pending"


@pytest.mark.asyncio
async def test_explicit_policy_auto_approves_above_threshold(
    session_factory,
):
    """An enabled policy links a single candidate at the threshold."""
    async with session_factory() as session:
        ids = await _seed(session)
        mention = await _mention(session, "bank central asia")
        outcome = await res.ResolutionService(session).resolve(
            mention.id, policy=AUTO
        )
        await session.commit()

    assert outcome.auto_approved is True
    assert outcome.mention.resolution_status == "resolved"
    assert outcome.mention.resolved_entity_id == ids["bca"]
    top = outcome.candidates[0]
    assert top.decision == "auto_approved"
    assert top.decided_by == "policy:trusted-names@3"
    assert top.decided_at is not None
    async with session_factory() as session:
        stored = await st.EntityStore(session).get_mention(mention.id)
    assert stored.resolved_entity_id == ids["bca"]


@pytest.mark.asyncio
async def test_explicit_policy_below_threshold_needs_review(
    session_factory,
):
    """Candidates under the threshold stay pending."""
    async with session_factory() as session:
        await _seed(session)
        mention = await _mention(session, "BCA")
        outcome = await res.ResolutionService(session).resolve(
            mention.id, policy=AUTO
        )
    assert outcome.candidates[0].score == pytest.approx(0.9)
    assert outcome.auto_approved is False
    assert outcome.mention.resolution_status == "candidate"


@pytest.mark.asyncio
async def test_ties_at_the_threshold_are_never_auto_approved(
    session_factory,
):
    """Two candidates reaching the threshold mean the match is ambiguous."""
    async with session_factory() as session:
        await _seed(session)
        mention = await _mention(session, "Bank Rakyat Indonesia")
        outcome = await res.ResolutionService(session).resolve(
            mention.id, policy=AUTO
        )
    assert [c.score for c in outcome.candidates[:2]] == [0.95, 0.95]
    assert outcome.auto_approved is False
    assert all(c.decision == "pending" for c in outcome.candidates)


@pytest.mark.asyncio
async def test_ties_hidden_by_truncation_still_block_auto_approval(
    session_factory,
):
    """Ambiguity is judged before the candidate list is truncated."""
    policy = AUTO.model_copy(update={"max_candidates": 1})
    async with session_factory() as session:
        await _seed(session)
        mention = await _mention(session, "Bank Rakyat Indonesia")
        outcome = await res.ResolutionService(session).resolve(
            mention.id, policy=policy
        )
    assert len(outcome.candidates) == 1
    assert outcome.auto_approved is False
    assert outcome.candidates[0].decision == "pending"


@pytest.mark.asyncio
async def test_no_candidates_leaves_the_mention_unresolved(session_factory):
    """Nothing to review means the mention stays unresolved."""
    async with session_factory() as session:
        await _seed(session)
        mention = await _mention(session, "Bank Mandiri")
        outcome = await res.ResolutionService(session).resolve(mention.id)
    assert outcome.candidates == []
    assert outcome.mention.resolution_status == "unresolved"


@pytest.mark.asyncio
async def test_candidates_store_scores_and_versions(session_factory):
    """Each stored candidate explains how it was produced."""
    release = build_finance_release()
    async with session_factory() as session:
        ids = await _seed(session)
        mention = await _mention(
            session, "Bank Central Asi", ontology_class_uri=EX + "Organization"
        )
        await res.ResolutionService(session, release=release).resolve(
            mention.id, policy=AUTO
        )
        await session.commit()

    async with session_factory() as session:
        (candidate,) = await res.ResolutionService(session).list_candidates(
            mention.id
        )
    assert candidate.entity_id == ids["bca"]
    assert candidate.mention_id == mention.id
    assert candidate.rank == 1
    assert candidate.method == "similarity"
    assert set(candidate.score_breakdown) == {
        "identifier", "exact_label", "exact_alias", "similarity"
    }
    assert candidate.matched_text == "Bank Central Asia"
    assert candidate.policy_id == "trusted-names"
    assert candidate.policy_version == "3"
    assert candidate.normalizer_version == res.NORMALIZER_VERSION
    assert candidate.ontology_release_id == release.release_id
    assert candidate.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_resolution_is_deterministic(session_factory):
    """Re-running supersedes pending candidates with identical ones."""
    async with session_factory() as session:
        await _seed(session)
        mention = await _mention(session, "Bank Rakyat Indonesia")
        service = res.ResolutionService(session)
        first = await service.resolve(mention.id)
        second = await service.resolve(mention.id)
        history = await service.list_candidates(
            mention.id, include_history=True
        )
        current = [c.id for c in await service.list_candidates(mention.id)]

    def key(candidates):
        return [(c.entity_id, c.rank, c.method, c.score) for c in candidates]

    assert key(first.candidates) == key(second.candidates)
    assert len(history) == 2 * len(first.candidates)
    assert sorted({c.decision for c in history}) == ["pending", "superseded"]
    assert current == [c.id for c in second.candidates]


@pytest.mark.asyncio
async def test_resolved_mentions_cannot_be_resolved_again(session_factory):
    """Once linked, a mention keeps its link until a split resets it."""
    async with session_factory() as session:
        await _seed(session)
        mention = await _mention(session, "Bank Central Asia")
        service = res.ResolutionService(session)
        await service.resolve(mention.id, policy=AUTO)
        with pytest.raises(res.ResolutionStateError):
            await service.resolve(mention.id)


@pytest.mark.asyncio
async def test_resolve_missing_mention_raises(session_factory):
    """Unknown mentions raise MentionNotFoundError."""
    async with session_factory() as session:
        with pytest.raises(st.MentionNotFoundError):
            await res.ResolutionService(session).resolve(uuid.uuid4())


# --- Steward decisions ----------------------------------------------------


@pytest.mark.asyncio
async def test_approve_candidate_links_the_mention(session_factory):
    """Approval records who decided and why, and links the mention."""
    async with session_factory() as session:
        ids = await _seed(session)
        mention = await _mention(session, "Bank Rakyat Indonesia")
        service = res.ResolutionService(session)
        outcome = await service.resolve(mention.id)
        chosen = next(
            c for c in outcome.candidates if c.entity_id == ids["bri"]
        )
        approved = await service.approve_candidate(
            chosen.id, actor_id="steward:ana", reason="Matches licence"
        )
        await session.commit()

    assert approved.decision == "approved"
    assert approved.decided_by == "steward:ana"
    assert approved.decision_reason == "Matches licence"
    assert approved.decided_at is not None
    async with session_factory() as session:
        service = res.ResolutionService(session)
        stored = await st.EntityStore(session).get_mention(mention.id)
        decisions = {
            c.entity_id: c.decision
            for c in await service.list_candidates(mention.id)
        }
    assert stored.resolution_status == "resolved"
    assert stored.resolved_entity_id == ids["bri"]
    assert decisions == {ids["bri"]: "approved", ids["bri-dup"]: "superseded"}


@pytest.mark.asyncio
async def test_only_pending_candidates_can_be_decided(session_factory):
    """Decided candidates are final."""
    async with session_factory() as session:
        await _seed(session)
        mention = await _mention(session, "BCA")
        service = res.ResolutionService(session)
        (candidate,) = (await service.resolve(mention.id)).candidates
        await service.reject_candidate(candidate.id, actor_id="steward:ana")
        with pytest.raises(res.ResolutionStateError):
            await service.approve_candidate(candidate.id, actor_id="x")
        with pytest.raises(res.ResolutionStateError):
            await service.reject_candidate(candidate.id, actor_id="x")


@pytest.mark.asyncio
async def test_stale_candidates_cannot_be_approved(session_factory):
    """A candidate whose entity is no longer active must be re-resolved."""
    async with session_factory() as session:
        ids = await _seed(session)
        mention = await _mention(session, "BCA")
        service = res.ResolutionService(session)
        (candidate,) = (await service.resolve(mention.id)).candidates
        (await session.get(EntityRecord, ids["bca"])).status = "deprecated"
        await session.flush()
        with pytest.raises(res.ResolutionStateError):
            await service.approve_candidate(candidate.id, actor_id="x")


@pytest.mark.asyncio
async def test_reject_candidates(session_factory):
    """Rejecting the last pending candidate unresolves the mention."""
    async with session_factory() as session:
        await _seed(session)
        mention = await _mention(session, "Bank Rakyat Indonesia")
        service = res.ResolutionService(session)
        first, second = (await service.resolve(mention.id)).candidates
        rejected = await service.reject_candidate(
            first.id, actor_id="steward:ana", reason="Wrong bank"
        )
        after_one = await st.EntityStore(session).get_mention(mention.id)
        await service.reject_candidate(second.id, actor_id="steward:ana")
        after_both = await st.EntityStore(session).get_mention(mention.id)
    assert rejected.decision == "rejected"
    assert rejected.decision_reason == "Wrong bank"
    assert after_one.resolution_status == "candidate"
    assert after_both.resolution_status == "unresolved"


@pytest.mark.asyncio
async def test_decisions_need_an_actor(session_factory):
    """Every decision names who made it."""
    async with session_factory() as session:
        await _seed(session)
        mention = await _mention(session, "BCA")
        service = res.ResolutionService(session)
        (candidate,) = (await service.resolve(mention.id)).candidates
        with pytest.raises(ValueError):
            await service.approve_candidate(candidate.id, actor_id=" ")


@pytest.mark.asyncio
async def test_missing_candidate_raises(session_factory):
    """Unknown candidate ids raise CandidateNotFoundError."""
    async with session_factory() as session:
        with pytest.raises(res.CandidateNotFoundError):
            await res.ResolutionService(session).get_candidate(uuid.uuid4())
