"""Tests for the curator review queue (FR12, ADR-0014, ADR-0022)."""

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from rag_foundry.assertions import lifecycle as lc
from rag_foundry.assertions import validation as av
from rag_foundry.db.models import (
    AssertionRecord,
    AssertionValidationRecord,
    Chunk,
)
from rag_foundry.entities import lineage as lin
from rag_foundry.entities import resolution as res
from rag_foundry.entities import store as st
from rag_foundry.stewardship import review_queue as rq
from tests.assertion_helpers import (
    ID,
    OTHER_WS,
    PROFILE,
    RELEASE,
    WS,
    create_assertion,
    seed,
)

STEWARD = "steward:ana"
AUTO = res.ResolutionPolicy(policy_id="auto", auto_approve=True,
                            auto_approve_threshold=0.95)


@pytest_asyncio.fixture
async def world(session_factory):
    """Seed entities and evidence; yield (session, ids)."""
    async with session_factory() as session:
        yield session, await seed(session)


async def _mention(session, text, workspace=WS):
    """Record a mention."""
    return await st.EntityStore(session).record_mention(
        workspace_id=workspace, semantic_profile_id=PROFILE,
        chunk_id=uuid.uuid4(), start_offset=0, end_offset=len(text),
        surface_text=text,
    )


async def _validated(session, ids, **kwargs):
    """Create and validate an assertion."""
    assertion = await create_assertion(session, ids, **kwargs)
    report = await av.AssertionValidator(session).validate(
        assertion.id, RELEASE
    )
    assert report.valid, report.findings
    return assertion


async def _items(session, **kwargs):
    """List review items."""
    return await rq.ReviewQueue(session).list_items(**kwargs)


# --- Enqueuing ------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_candidates_are_enqueued(world):
    """Each candidate awaiting review gets an open item."""
    session, ids = world
    mention = await _mention(session, "bca")
    outcome = await res.ResolutionService(session).resolve(mention.id)
    items = await _items(session)
    assert [(i.kind, i.target_id) for i in items] == [
        ("resolution_candidate", c.id) for c in outcome.candidates
    ]
    item = items[0]
    assert item.status == "open"
    assert item.workspace_id == WS
    assert item.semantic_profile_id == PROFILE
    assert str(mention.id) in item.reason
    assert item.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_auto_approved_resolutions_need_no_review(world):
    """A link made by an explicit policy is not queued."""
    session, ids = world
    mention = await _mention(session, "bca")
    outcome = await res.ResolutionService(session).resolve(
        mention.id, policy=AUTO
    )
    assert outcome.auto_approved
    assert await _items(session) == []


@pytest.mark.asyncio
async def test_re_resolution_replaces_items(world):
    """Superseded candidates' items close; new ones open."""
    session, ids = world
    mention = await _mention(session, "bca")
    service = res.ResolutionService(session)
    first = await service.resolve(mention.id)
    second = await service.resolve(mention.id)
    open_items = await _items(session)
    closed = await _items(session, statuses=["closed"])
    assert [i.target_id for i in open_items] == [
        c.id for c in second.candidates
    ]
    assert [i.target_id for i in closed] == [c.id for c in first.candidates]
    assert all(i.decided_by == "system:re-resolution" for i in closed)


@pytest.mark.asyncio
async def test_validated_assertions_are_enqueued(world):
    """Only assertions that pass validation wait for approval."""
    session, ids = world
    good = await _validated(session, ids)
    bad = await create_assertion(session, ids, prop="foundedOn",
                                 literal="1957-02-30")
    await av.AssertionValidator(session).validate(bad.id, RELEASE)
    items = await _items(session, kind="assertion")
    assert [i.target_id for i in items] == [good.id]
    assert items[0].reason == "Validated; awaiting approval"


@pytest.mark.asyncio
async def test_split_flags_are_enqueued(world):
    """Flagged approved assertions come back to the queue."""
    session, ids = world
    assertion = await _validated(session, ids)
    await rq.ReviewQueue(session).approve(
        (await _items(session))[0].id, actor_id=STEWARD
    )
    await lin.EntityLineageService(session).split(
        ids["bca"],
        [lin.SuccessorSpec(canonical_uri=ID + "a",
                           preferred_labels={"en": "A"}),
         lin.SuccessorSpec(canonical_uri=ID + "b",
                           preferred_labels={"en": "B"})],
        actor_id=STEWARD, reason="Conflated",
    )
    (item,) = await _items(session)
    assert item.target_id == assertion.id
    assert "was split" in item.reason


@pytest.mark.asyncio
async def test_list_filters(world):
    """Items filter by kind, workspace and status."""
    session, ids = world
    mention = await _mention(session, "bca")
    await res.ResolutionService(session).resolve(mention.id)
    await _validated(session, ids)
    assert len(await _items(session)) == 2
    assert len(await _items(session, kind="assertion")) == 1
    assert len(await _items(session, kind="resolution_candidate")) == 1
    assert await _items(session, workspace_id=OTHER_WS) == []
    assert len(await _items(session, statuses=None)) == 2
    assert await _items(session, statuses=["approved"]) == []


# --- Deciding resolution candidates ---------------------------------------


@pytest.mark.asyncio
async def test_approve_candidate_item(world):
    """Approval links the mention and records who, when, why and profile."""
    session, ids = world
    mention = await _mention(session, "bca")
    await res.ResolutionService(session).resolve(mention.id)
    (item,) = await _items(session)
    decided = await rq.ReviewQueue(session).approve(
        item.id, actor_id=STEWARD, reason="Licence register"
    )
    stored = await st.EntityStore(session).get_mention(mention.id)
    assert decided.status == "approved"
    assert decided.decided_by == STEWARD
    assert decided.decision_reason == "Licence register"
    assert decided.decided_at is not None
    assert decided.semantic_profile_id == PROFILE
    assert stored.resolved_entity_id == ids["bca"]


@pytest.mark.asyncio
async def test_approving_one_candidate_closes_its_siblings(world):
    """Alternatives that were not chosen leave the queue."""
    session, ids = world
    store = st.EntityStore(session)
    for name in ("acme-1", "acme-2"):
        await store.create_entity(
            workspace_id=WS, semantic_profile_id=PROFILE,
            canonical_uri=ID + name, ontology_class_uri=RELEASE.classes[0].uri,
            preferred_labels={"en": "Acme"},
        )
    mention = await _mention(session, "Acme")
    await res.ResolutionService(session).resolve(mention.id)
    first, second = await _items(session)
    await rq.ReviewQueue(session).approve(first.id, actor_id=STEWARD)
    closed = await _items(session, statuses=["closed"])
    assert [i.id for i in closed] == [second.id]
    assert await _items(session) == []


@pytest.mark.asyncio
async def test_reject_candidate_item(world):
    """Rejection is recorded on the item and the candidate."""
    session, ids = world
    mention = await _mention(session, "bca")
    await res.ResolutionService(session).resolve(mention.id)
    (item,) = await _items(session)
    decided = await rq.ReviewQueue(session).reject(
        item.id, actor_id=STEWARD, reason="Different bank"
    )
    candidate = await res.ResolutionService(session).get_candidate(
        item.target_id
    )
    assert decided.status == "rejected"
    assert decided.decision_reason == "Different bank"
    assert candidate.decision == "rejected"


@pytest.mark.asyncio
async def test_decisions_made_outside_the_queue_settle_items(world):
    """A direct service decision still closes the matching item."""
    session, ids = world
    mention = await _mention(session, "bca")
    outcome = await res.ResolutionService(session).resolve(mention.id)
    await res.ResolutionService(session).approve_candidate(
        outcome.candidates[0].id, actor_id=STEWARD, reason="Direct"
    )
    (item,) = await _items(session, statuses=["approved"])
    assert item.decided_by == STEWARD
    assert item.decision_reason == "Direct"


# --- Deciding assertions --------------------------------------------------


@pytest.mark.asyncio
async def test_approve_assertion_item(world):
    """Approving a validated assertion approves it."""
    session, ids = world
    assertion = await _validated(session, ids)
    (item,) = await _items(session)
    decided = await rq.ReviewQueue(session).approve(
        item.id, actor_id=STEWARD, reason="Deed checked"
    )
    stored = await lc.AssertionStore(session).get_assertion(assertion.id)
    log = await lc.AssertionStore(session).list_transitions(assertion.id)
    assert decided.status == "approved"
    assert stored.status == "approved"
    assert (log[-1].actor_id, log[-1].reason) == (STEWARD, "Deed checked")


@pytest.mark.asyncio
async def test_reject_assertion_item(world):
    """Rejecting a validated assertion rejects it."""
    session, ids = world
    assertion = await _validated(session, ids)
    (item,) = await _items(session)
    await rq.ReviewQueue(session).reject(item.id, actor_id=STEWARD,
                                         reason="Outdated")
    stored = await lc.AssertionStore(session).get_assertion(assertion.id)
    assert stored.status == "rejected"


@pytest.mark.asyncio
async def test_approval_refused_when_evidence_is_missing(world):
    """Evidence that no longer resolves blocks approval."""
    session, ids = world
    await _validated(session, ids)
    chunk = await session.get(Chunk, ids["chunk"])
    await session.delete(chunk)
    await session.flush()
    (item,) = await _items(session)
    with pytest.raises(rq.ReviewRefusedError):
        await rq.ReviewQueue(session).approve(item.id, actor_id=STEWARD)
    assert (await rq.ReviewQueue(session).get_item(item.id)).status == "open"


@pytest.mark.asyncio
async def test_approval_refused_when_validation_failed(world):
    """A flagged assertion whose revalidation failed cannot be confirmed."""
    session, ids = world
    assertion = await _validated(session, ids, confidence=0.6)
    queue = rq.ReviewQueue(session)
    await queue.approve((await _items(session))[0].id, actor_id=STEWARD)
    strict = av.AssertionPolicy(policy_id="strict", min_confidence=0.8)
    await av.AssertionValidator(session).validate(
        assertion.id, RELEASE, policy=strict
    )
    (item,) = await _items(session)
    assert item.reason == "Failed checks: low_confidence"
    with pytest.raises(rq.ReviewRefusedError):
        await queue.approve(item.id, actor_id=STEWARD)


@pytest.mark.asyncio
async def test_passing_revalidation_closes_a_flag_item(world):
    """Fixing the cause clears the flag and the item."""
    session, ids = world
    assertion = await _validated(session, ids, confidence=0.6)
    queue = rq.ReviewQueue(session)
    await queue.approve((await _items(session))[0].id, actor_id=STEWARD)
    strict = av.AssertionPolicy(policy_id="strict", min_confidence=0.8)
    validator = av.AssertionValidator(session)
    await validator.validate(assertion.id, RELEASE, policy=strict)
    await validator.validate(assertion.id, RELEASE)
    assert await _items(session) == []
    (closed,) = await _items(session, statuses=["closed"])
    assert closed.decision_reason == "Revalidation passed"


@pytest.mark.asyncio
async def test_rejecting_a_flagged_assertion_retires_it(world):
    """A flagged approved assertion is retired, never silently kept."""
    session, ids = world
    assertion = await _validated(session, ids, confidence=0.6)
    queue = rq.ReviewQueue(session)
    await queue.approve((await _items(session))[0].id, actor_id=STEWARD)
    strict = av.AssertionPolicy(policy_id="strict", min_confidence=0.8)
    await av.AssertionValidator(session).validate(
        assertion.id, RELEASE, policy=strict
    )
    (item,) = await _items(session)
    decided = await queue.reject(item.id, actor_id=STEWARD,
                                 reason="Below the new bar")
    stored = await lc.AssertionStore(session).get_assertion(assertion.id)
    assert decided.status == "rejected"
    assert stored.status == "superseded"


# --- Idempotency and state ------------------------------------------------


@pytest.mark.asyncio
async def test_approving_twice_has_no_extra_effect(world):
    """A repeated approval returns the decided item unchanged."""
    session, ids = world
    assertion = await _validated(session, ids)
    (item,) = await _items(session)
    queue = rq.ReviewQueue(session)
    first = await queue.approve(item.id, actor_id=STEWARD, reason="Once")
    second = await queue.approve(item.id, actor_id="steward:bo",
                                 reason="Twice")
    log = await lc.AssertionStore(session).list_transitions(assertion.id)
    assert second == first
    assert [t.to_status for t in log].count("approved") == 1


@pytest.mark.asyncio
async def test_decided_items_cannot_change_their_outcome(world):
    """Approved items cannot be rejected, closed ones cannot be decided."""
    session, ids = world
    mention = await _mention(session, "bca")
    service = res.ResolutionService(session)
    await service.resolve(mention.id)
    (old,) = await _items(session)
    await service.resolve(mention.id)
    (new,) = await _items(session)
    queue = rq.ReviewQueue(session)
    await queue.approve(new.id, actor_id=STEWARD)
    with pytest.raises(rq.ReviewStateError):
        await queue.reject(new.id, actor_id=STEWARD)
    with pytest.raises(rq.ReviewStateError):
        await queue.approve(old.id, actor_id=STEWARD)
    with pytest.raises(ValueError):
        await queue.approve(new.id, actor_id=" ")
    with pytest.raises(rq.ReviewItemNotFoundError):
        await queue.get_item(uuid.uuid4())


@pytest.mark.asyncio
async def test_split_of_a_validated_assertion_updates_its_open_item(world):
    """One open item per target: the split reason replaces the old one."""
    session, ids = world
    await _validated(session, ids)
    (before,) = await _items(session)
    await lin.EntityLineageService(session).split(
        ids["bca"],
        [lin.SuccessorSpec(canonical_uri=ID + "a",
                           preferred_labels={"en": "A"}),
         lin.SuccessorSpec(canonical_uri=ID + "b",
                           preferred_labels={"en": "B"})],
        actor_id=STEWARD, reason="Conflated",
    )
    (after,) = await _items(session)
    assert after.id == before.id
    assert "was split" in after.reason
    with pytest.raises(rq.ReviewRefusedError):
        await rq.ReviewQueue(session).approve(after.id, actor_id=STEWARD)


@pytest.mark.asyncio
async def test_approval_refused_after_a_concurrent_failed_validation(world):
    """The latest report decides, even if it arrived out of band."""
    session, ids = world
    assertion = await _validated(session, ids)
    session.add(AssertionValidationRecord(
        assertion_id=assertion.id, ontology_release_id=RELEASE.release_id,
        ontology_version=RELEASE.version, policy_id="other",
        policy_version="1", valid=False,
        findings=[{"rule": "low_confidence", "severity": "error",
                   "message": "x"}],
        actor_id="validator:other",
    ))
    await session.flush()
    (item,) = await _items(session)
    with pytest.raises(rq.ReviewRefusedError):
        await rq.ReviewQueue(session).approve(item.id, actor_id=STEWARD)


@pytest.mark.asyncio
async def test_approval_refused_when_evidence_list_was_emptied(world):
    """Extracted assertions must still cite evidence at approval time."""
    session, ids = world
    assertion = await _validated(session, ids)
    record = await session.get(AssertionRecord, assertion.id)
    record.source_chunk_ids = []
    await session.flush()
    (item,) = await _items(session)
    with pytest.raises(rq.ReviewRefusedError):
        await rq.ReviewQueue(session).approve(item.id, actor_id=STEWARD)


def test_review_item_migration_upgrades_and_downgrades(tmp_path):
    """The review_items table comes and goes with its migration."""
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

    command.upgrade(config, "head")
    assert "review_items" in tables()
    command.downgrade(config, "a7c19e4b2d10")
    assert "review_items" not in tables()
    assert "assertion_validations" in tables()
