"""Tests for auditable entity merges, splits and redirects (ADR-0012)."""

import uuid

import pytest

from rag_foundry.db.models import EntityRecord
from rag_foundry.entities import lineage as lin
from rag_foundry.entities import resolution as res
from rag_foundry.entities import store as st

EX = "http://example.org/finance#"
ID = "http://id.example.org/entity/"
WS = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
OTHER_WS = uuid.UUID("00000000-0000-4000-8000-0000000000cc")
PROFILE = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
STEWARD = "steward:ana"


async def _entity(session, name, cls="Bank", workspace=WS, **kwargs):
    """Create an entity."""
    return await st.EntityStore(session).create_entity(
        workspace_id=workspace,
        semantic_profile_id=PROFILE,
        canonical_uri=ID + name,
        ontology_class_uri=EX + cls,
        preferred_labels=kwargs.pop("labels", {"en": name}),
        **kwargs,
    )


async def _resolved_mention(session, entity_id, text="BCA"):
    """Record a mention and link it to an entity by approval."""
    mention = await st.EntityStore(session).record_mention(
        workspace_id=WS, semantic_profile_id=PROFILE, chunk_id=uuid.uuid4(),
        start_offset=0, end_offset=len(text), surface_text=text,
    )
    service = res.ResolutionService(session)
    outcome = await service.resolve(mention.id)
    candidate = next(
        c for c in outcome.candidates if c.entity_id == entity_id
    )
    await service.approve_candidate(candidate.id, actor_id=STEWARD)
    return mention


# --- Merge ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_redirects_and_moves_identity(session_factory):
    """The merged entity redirects; identifiers and names move over."""
    async with session_factory() as session:
        survivor = await _entity(
            session, "bca", labels={"en": "Bank Central Asia"},
            identifiers={"swift_bic": "CENAIDJA"},
        )
        duplicate = await _entity(
            session, "bca-dup", labels={"en": "BCA", "id": "Bank BCA"},
            aliases={"en": ["PT BCA"]}, identifiers={"lei": "LEI-BCA"},
        )
        result = await lin.EntityLineageService(session).merge(
            survivor.id, duplicate.id, actor_id=STEWARD,
            reason="Same SWIFT code in licence register",
        )
        await session.commit()

    assert result.survivor.identifiers == {
        "swift_bic": "CENAIDJA", "lei": "LEI-BCA"
    }
    assert result.survivor.aliases == {
        "en": ["BCA", "PT BCA"], "id": ["Bank BCA"]
    }
    assert result.merged.status == "merged"
    assert result.merged.merged_into_id == survivor.id
    async with session_factory() as session:
        store = st.EntityStore(session)
        found = await store.find_by_identifier(WS, "lei", "LEI-BCA")
        kept = await store.get_entity(duplicate.id)
    assert found.id == survivor.id
    assert kept.preferred_labels == {"en": "BCA", "id": "Bank BCA"}
    assert kept.status == "merged"


@pytest.mark.asyncio
async def test_merge_is_recorded_in_lineage(session_factory):
    """Both entities' histories show who merged them, when and why."""
    async with session_factory() as session:
        survivor = await _entity(session, "bca")
        duplicate = await _entity(
            session, "bca-dup", identifiers={"lei": "LEI-BCA"}
        )
        service = lin.EntityLineageService(session)
        result = await service.merge(
            survivor.id, duplicate.id, actor_id=STEWARD, reason="Duplicate"
        )
        survivor_history = await service.history(survivor.id)
        merged_history = await service.history(duplicate.id)

    (event,) = survivor_history
    assert merged_history == survivor_history
    assert event.event_id == result.event_id
    assert event.event_type == "merge"
    assert event.predecessor_id == duplicate.id
    assert event.successor_id == survivor.id
    assert event.actor_id == STEWARD
    assert event.reason == "Duplicate"
    assert event.details["moved_identifiers"] == {"lei": "LEI-BCA"}
    assert event.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_redirect_chains_resolve_to_the_live_entity(session_factory):
    """A -> B -> C redirects every old id to C."""
    async with session_factory() as session:
        a = await _entity(session, "a")
        b = await _entity(session, "b")
        c = await _entity(session, "c")
        service = lin.EntityLineageService(session)
        await service.merge(b.id, a.id, actor_id=STEWARD, reason="dup")
        await service.merge(c.id, b.id, actor_id=STEWARD, reason="dup")
        assert (await service.current_entity(a.id)).id == c.id
        assert (await service.current_entity(b.id)).id == c.id
        assert (await service.current_entity(c.id)).id == c.id
        with pytest.raises(st.EntityNotFoundError):
            await service.current_entity(uuid.uuid4())


@pytest.mark.asyncio
async def test_merge_skips_names_the_survivor_already_has(session_factory):
    """Labels and aliases are not duplicated on the survivor."""
    async with session_factory() as session:
        survivor = await _entity(
            session, "bca", labels={"en": "BCA"}, aliases={"en": ["Bank BCA"]}
        )
        duplicate = await _entity(
            session, "bca-dup", labels={"en": "BCA"},
            aliases={"en": ["Bank BCA", "PT BCA"]},
        )
        service = lin.EntityLineageService(session)
        result = await service.merge(
            survivor.id, duplicate.id, actor_id=STEWARD, reason="dup"
        )
        (event,) = await service.history(survivor.id)
    assert result.survivor.aliases == {"en": ["Bank BCA", "PT BCA"]}
    assert event.details["added_aliases"] == {"en": ["PT BCA"]}


@pytest.mark.asyncio
async def test_redirect_cycles_are_detected(session_factory):
    """Corrupted redirects fail loudly instead of looping forever."""
    async with session_factory() as session:
        a = await _entity(session, "a")
        b = await _entity(session, "b")
        for entity_id, target in ((a.id, b.id), (b.id, a.id)):
            record = await session.get(EntityRecord, entity_id)
            record.status, record.merged_into_id = "merged", target
        await session.flush()
        with pytest.raises(lin.LineageError):
            await lin.EntityLineageService(session).current_entity(a.id)


@pytest.mark.asyncio
async def test_merge_into_itself_is_rejected(session_factory):
    """An entity cannot absorb itself."""
    async with session_factory() as session:
        a = await _entity(session, "a")
        with pytest.raises(lin.EntityMergeError):
            await lin.EntityLineageService(session).merge(
                a.id, a.id, actor_id=STEWARD, reason="x"
            )


@pytest.mark.asyncio
async def test_merges_involving_merged_entities_are_rejected(
    session_factory,
):
    """Neither side of a merge may already be merged."""
    async with session_factory() as session:
        a = await _entity(session, "a")
        b = await _entity(session, "b")
        c = await _entity(session, "c")
        service = lin.EntityLineageService(session)
        await service.merge(b.id, a.id, actor_id=STEWARD, reason="dup")
        with pytest.raises(st.EntityStateError):
            await service.merge(a.id, c.id, actor_id=STEWARD, reason="x")
        with pytest.raises(st.EntityStateError):
            await service.merge(c.id, a.id, actor_id=STEWARD, reason="x")


@pytest.mark.asyncio
async def test_incompatible_merges_are_rejected(session_factory):
    """Merges stay within a workspace and an ontology class."""
    async with session_factory() as session:
        bank = await _entity(session, "bank", identifiers={"lei": "L1"})
        person = await _entity(session, "person", cls="Person")
        elsewhere = await _entity(session, "far", workspace=OTHER_WS)
        rival = await _entity(session, "rival", identifiers={"lei": "L2"})
        service = lin.EntityLineageService(session)
        for other in (person, elsewhere, rival):
            with pytest.raises(lin.EntityMergeError):
                await service.merge(
                    bank.id, other.id, actor_id=STEWARD, reason="x"
                )
        assert (await st.EntityStore(session).get_entity(rival.id)).status \
            == "active"


@pytest.mark.asyncio
async def test_merges_need_an_actor_and_a_reason(session_factory):
    """Governed operations always say who and why."""
    async with session_factory() as session:
        a = await _entity(session, "a")
        b = await _entity(session, "b")
        service = lin.EntityLineageService(session)
        with pytest.raises(ValueError):
            await service.merge(a.id, b.id, actor_id=" ", reason="dup")
        with pytest.raises(ValueError):
            await service.merge(a.id, b.id, actor_id=STEWARD, reason="")


# --- Split ----------------------------------------------------------------


def _spec(name, **kwargs):
    """Describe a split successor."""
    return lin.SuccessorSpec(
        canonical_uri=ID + name,
        preferred_labels=kwargs.pop("labels", {"en": name}),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_split_creates_successors(session_factory):
    """A split creates new identities and hands identifiers over."""
    async with session_factory() as session:
        original = await _entity(
            session, "bank-x",
            identifiers={"lei": "LEI-1", "swift_bic": "SWIFT-2",
                         "id.npwp": "NPWP-9"},
        )
        result = await lin.EntityLineageService(session).split(
            original.id,
            [
                _spec("bank-x-holding", identifiers={"lei": "LEI-1"}),
                _spec("bank-x-ops", aliases={"en": ["X Ops"]},
                      identifiers={"swift_bic": "SWIFT-2",
                                   "lei.new": "LEI-NEW"}),
            ],
            actor_id=STEWARD,
            reason="Two legal entities were conflated",
        )
        await session.commit()

    holding, ops = result.successors
    assert result.original.status == "split"
    assert holding.status == ops.status == "active"
    assert holding.identifiers == {"lei": "LEI-1"}
    assert ops.identifiers == {"swift_bic": "SWIFT-2", "lei.new": "LEI-NEW"}
    assert ops.aliases == {"en": ["X Ops"]}
    assert holding.ontology_class_uri == original.ontology_class_uri
    assert holding.workspace_id == WS
    assert result.original.identifiers == {"id.npwp": "NPWP-9"}
    async with session_factory() as session:
        history = await lin.EntityLineageService(session).history(
            original.id
        )
    assert {h.successor_id for h in history} == {holding.id, ops.id}
    assert {h.event_id for h in history} == {result.event_id}
    assert all(h.event_type == "split" for h in history)


@pytest.mark.asyncio
async def test_split_successors_may_name_their_class(session_factory):
    """A successor may be typed more precisely than the original."""
    async with session_factory() as session:
        original = await _entity(session, "x", cls="Organization")
        result = await lin.EntityLineageService(session).split(
            original.id,
            [_spec("x-bank", ontology_class_uri=EX + "Bank"), _spec("x-org")],
            actor_id=STEWARD, reason="One was a bank",
        )
    assert [s.ontology_class_uri for s in result.successors] == [
        EX + "Bank", EX + "Organization"
    ]


@pytest.mark.asyncio
async def test_split_resets_mentions_of_the_original(session_factory):
    """Mentions linked to the split entity must be resolved again."""
    async with session_factory() as session:
        original = await _entity(session, "bca", labels={"en": "BCA"})
        other = await _entity(session, "bri", labels={"en": "BRI"})
        linked = await _resolved_mention(session, original.id, "BCA")
        untouched = await _resolved_mention(session, other.id, "BRI")
        result = await lin.EntityLineageService(session).split(
            original.id, [_spec("bca-a"), _spec("bca-b")],
            actor_id=STEWARD, reason="Conflated",
        )
        store = st.EntityStore(session)
        reset = await store.get_mention(linked.id)
        kept = await store.get_mention(untouched.id)
    assert result.reset_mention_ids == [linked.id]
    assert reset.resolution_status == "unresolved"
    assert reset.resolved_entity_id is None
    assert kept.resolved_entity_id == other.id


@pytest.mark.asyncio
async def test_redirects_to_split_entities_need_re_resolution(
    session_factory,
):
    """A split has no single successor, so redirects stop there."""
    async with session_factory() as session:
        original = await _entity(session, "x")
        absorbed = await _entity(session, "x-dup")
        service = lin.EntityLineageService(session)
        await service.merge(
            original.id, absorbed.id, actor_id=STEWARD, reason="dup"
        )
        await service.split(
            original.id, [_spec("x1"), _spec("x2")],
            actor_id=STEWARD, reason="conflated",
        )
        for entity_id in (original.id, absorbed.id):
            with pytest.raises(lin.EntitySplitError):
                await service.current_entity(entity_id)


@pytest.mark.parametrize(
    "successors, error",
    [
        ([("only", {})], lin.EntitySplitError),
        ([("same", {}), ("same", {})], lin.EntitySplitError),
        ([("taken", {}), ("b", {})], st.DuplicateEntityError),
        ([("a", {"lei": "L-OTHER"}), ("b", {})], st.DuplicateIdentifierError),
        ([("a", {"lei": "L-1"}), ("b", {"lei": "L-1"})], lin.EntitySplitError),
    ],
)
@pytest.mark.asyncio
async def test_invalid_splits_are_rejected(
    session_factory, successors, error
):
    """Splits need two distinct, free identities and unshared identifiers."""
    async with session_factory() as session:
        original = await _entity(session, "x", identifiers={"lei": "L-1"})
        await _entity(session, "taken", identifiers={"lei": "L-OTHER"})
        with pytest.raises(error):
            await lin.EntityLineageService(session).split(
                original.id,
                [_spec(name, identifiers=ids) for name, ids in successors],
                actor_id=STEWARD, reason="x",
            )
        assert (await st.EntityStore(session).get_entity(original.id)) \
            .status == "active"


@pytest.mark.asyncio
async def test_only_active_entities_can_be_split(session_factory):
    """Merged or split entities cannot be split again."""
    async with session_factory() as session:
        a = await _entity(session, "a")
        b = await _entity(session, "b")
        service = lin.EntityLineageService(session)
        await service.merge(b.id, a.id, actor_id=STEWARD, reason="dup")
        with pytest.raises(st.EntityStateError):
            await service.split(
                a.id, [_spec("a1"), _spec("a2")],
                actor_id=STEWARD, reason="x",
            )
        with pytest.raises(ValueError):
            await service.split(
                b.id, [_spec("b1"), _spec("b2")], actor_id=STEWARD,
                reason=" ",
            )


def test_successor_specs_are_validated():
    """Successor names and identifiers follow the entity rules."""
    with pytest.raises(ValueError):
        lin.SuccessorSpec(canonical_uri="x", preferred_labels={"en": "X"})
    with pytest.raises(ValueError):
        _spec("x", identifiers={"LEI": "1"})
