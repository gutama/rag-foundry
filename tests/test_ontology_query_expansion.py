"""Tests for governed ontology query expansion and provenance traces (ADR-0016)."""

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from rag_foundry.db.models import (
    Base,
    OntologyClassRecord,
    OntologyPropertyRecord,
    OntologyReleaseRecord,
)
from rag_foundry.db.session import get_sessionmaker


async def _seed_ontology_releases(session):
    """Create approved, draft, and deprecated ontology releases for testing."""
    now = datetime.now(timezone.utc)

    approved = OntologyReleaseRecord(
        id=uuid.uuid4(),
        ontology_uri="https://example.org/onto/institutional",
        version="1.0.0",
        title="Institutional Governance Ontology",
        status="approved",
        published_at=now,
    )
    draft = OntologyReleaseRecord(
        id=uuid.uuid4(),
        ontology_uri="https://example.org/onto/institutional",
        version="2.0.0-draft",
        title="Unapproved Draft Ontology",
        status="draft",
    )
    deprecated = OntologyReleaseRecord(
        id=uuid.uuid4(),
        ontology_uri="https://example.org/onto/legacy",
        version="0.9.0",
        title="Deprecated Legacy Ontology",
        status="deprecated",
    )
    session.add_all([approved, draft, deprecated])
    await session.flush()

    # Approved hierarchy: Entity -> Organization -> Central Bank -> Regional Reserve
    cls_entity = OntologyClassRecord(
        release_id=approved.id,
        uri="https://example.org/onto/Entity",
        preferred_labels={"en": "Institutional Entity"},
        parent_class_uris=[],
        status="active",
    )
    cls_org = OntologyClassRecord(
        release_id=approved.id,
        uri="https://example.org/onto/Organization",
        preferred_labels={"en": "Organization", "fr": "Organisation"},
        parent_class_uris=["https://example.org/onto/Entity"],
        status="active",
    )
    cls_bank = OntologyClassRecord(
        release_id=approved.id,
        uri="https://example.org/onto/CentralBank",
        preferred_labels={"en": "Central Bank", "id": "Bank Sentral"},
        parent_class_uris=["https://example.org/onto/Organization"],
        status="active",
    )
    cls_reserve = OntologyClassRecord(
        release_id=approved.id,
        uri="https://example.org/onto/RegionalReserve",
        preferred_labels={"en": "Regional Reserve"},
        parent_class_uris=["https://example.org/onto/CentralBank"],
        status="active",
    )
    cls_dep_child = OntologyClassRecord(
        release_id=approved.id,
        uri="https://example.org/onto/OldBank",
        preferred_labels={"en": "Legacy Shadow Bank"},
        parent_class_uris=["https://example.org/onto/CentralBank"],
        status="deprecated",
    )

    # Approved properties with inverse relationship
    prop_regulates = OntologyPropertyRecord(
        release_id=approved.id,
        uri="https://example.org/onto/regulates",
        preferred_labels={"en": "regulates", "id": "mengatur"},
        property_type="object",
        domain_class_uris=["https://example.org/onto/CentralBank"],
        range_class_uris=["https://example.org/onto/Organization"],
        inverse_property_uri="https://example.org/onto/regulatedBy",
        status="active",
    )
    prop_regulated_by = OntologyPropertyRecord(
        release_id=approved.id,
        uri="https://example.org/onto/regulatedBy",
        preferred_labels={"en": "regulated by"},
        property_type="object",
        domain_class_uris=["https://example.org/onto/Organization"],
        range_class_uris=["https://example.org/onto/CentralBank"],
        inverse_property_uri="https://example.org/onto/regulates",
        status="active",
    )
    prop_deprecated = OntologyPropertyRecord(
        release_id=approved.id,
        uri="https://example.org/onto/legacyControls",
        preferred_labels={"en": "legacy controls"},
        property_type="object",
        inverse_property_uri="https://example.org/onto/regulates",
        status="deprecated",
    )

    # Draft & deprecated releases contain terms that MUST NEVER be expanded
    cls_draft = OntologyClassRecord(
        release_id=draft.id,
        uri="https://example.org/onto/DraftBank",
        preferred_labels={"en": "Central Bank"},
        parent_class_uris=["https://example.org/onto/DraftParent"],
        status="active",
    )
    cls_draft_parent = OntologyClassRecord(
        release_id=draft.id,
        uri="https://example.org/onto/DraftParent",
        preferred_labels={"en": "Secret Draft Authority"},
        parent_class_uris=[],
        status="active",
    )
    cls_dep_release = OntologyClassRecord(
        release_id=deprecated.id,
        uri="https://example.org/onto/DepBank",
        preferred_labels={"en": "Central Bank"},
        parent_class_uris=["https://example.org/onto/DepParent"],
        status="active",
    )
    cls_dep_parent = OntologyClassRecord(
        release_id=deprecated.id,
        uri="https://example.org/onto/DepParent",
        preferred_labels={"en": "Deprecated Authority"},
        parent_class_uris=[],
        status="active",
    )

    session.add_all(
        [
            cls_entity,
            cls_org,
            cls_bank,
            cls_reserve,
            cls_dep_child,
            prop_regulates,
            prop_regulated_by,
            prop_deprecated,
            cls_draft,
            cls_draft_parent,
            cls_dep_release,
            cls_dep_parent,
        ]
    )
    await session.commit()
    return approved, draft, deprecated


def test_expansion_policy_validation_and_bounds() -> None:
    """ExpansionPolicy validates depth, budget, and relation weight bounds."""
    from rag_foundry.retrieval.ontology_expansion import ExpansionPolicy

    policy = ExpansionPolicy()
    assert policy.max_depth == 1
    assert policy.max_expanded_terms == 12
    assert 0.0 < policy.depth_decay <= 1.0

    with pytest.raises(ValidationError):
        ExpansionPolicy(max_depth=-1)

    with pytest.raises(ValidationError):
        ExpansionPolicy(max_expanded_terms=-1)

    with pytest.raises(ValidationError):
        ExpansionPolicy(relation_weights={"ontology_parent": 1.5})

    with pytest.raises(ValidationError):
        ExpansionPolicy(relation_weights={"ontology_parent": 0.0})


@pytest.mark.asyncio
async def test_ontology_expander_matches_approved_classes_and_ignores_drafts() -> None:
    """Expands active classes in approved releases and ignores draft/deprecated."""
    from rag_foundry.retrieval.ontology_expansion import (
        ExpansionPolicy,
        OntologyQueryExpander,
    )

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        approved, _, _ = await _seed_ontology_releases(session)

        expander = OntologyQueryExpander(
            session_or_factory=session,
            policy=ExpansionPolicy(max_depth=1, languages=["en"]),
        )
        trace = await expander.expand_query("Central Bank policy")

        assert trace.expansion_applied is True
        assert trace.original_query == "Central Bank policy"
        assert str(approved.id) in trace.release_ids

        term_map = {t.term: t for t in trace.terms}
        assert "Central Bank policy" in term_map
        assert term_map["Central Bank policy"].weight == 1.0
        assert term_map["Central Bank policy"].relationship == "original"

        # Depth 1 includes direct parent (Organization) and active child (Regional Reserve)
        assert "Organization" in term_map
        assert term_map["Organization"].relationship == "ontology_parent"
        assert (
            term_map["Organization"].source_uri
            == "https://example.org/onto/Organization"
        )
        assert term_map["Organization"].release_id == approved.id
        assert term_map["Organization"].hop_depth == 1

        assert "Regional Reserve" in term_map
        assert term_map["Regional Reserve"].relationship == "ontology_child"
        assert (
            term_map["Regional Reserve"].source_uri
            == "https://example.org/onto/RegionalReserve"
        )

        # Depth 2 grandparent excluded at max_depth=1
        assert "Institutional Entity" not in term_map
        # Deprecated class, draft release, and deprecated release strictly excluded
        assert "Legacy Shadow Bank" not in term_map
        assert "Secret Draft Authority" not in term_map
        assert "Deprecated Authority" not in term_map

        # Depth 2 reaches grandparent with decayed weight
        trace_d2 = await expander.expand_query(
            "Central Bank policy",
            policy=ExpansionPolicy(max_depth=2, languages=["en"]),
        )
        d2_map = {t.term: t for t in trace_d2.terms}
        assert "Institutional Entity" in d2_map
        assert d2_map["Institutional Entity"].hop_depth == 2
        assert (
            d2_map["Institutional Entity"].weight
            < d2_map["Organization"].weight
        )


@pytest.mark.asyncio
async def test_ontology_expander_properties_inverses_multilingual_and_budget() -> None:
    """Expands active properties, inverses, multilingual labels, and enforces budget."""
    from rag_foundry.retrieval.ontology_expansion import (
        ExpansionPolicy,
        OntologyQueryExpander,
    )

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        approved, _, _ = await _seed_ontology_releases(session)

        expander = OntologyQueryExpander(session_or_factory=session)
        trace = await expander.expand_query("Who regulates Central Bank?")

        term_map = {t.term: t for t in trace.terms}
        # Multilingual preferred label on class and property
        assert "Bank Sentral" in term_map
        assert term_map["Bank Sentral"].relationship == "preferred_label"
        assert "mengatur" in term_map
        assert term_map["mengatur"].relationship == "ontology_property"
        # Active inverse property expanded; deprecated inverse ignored
        assert "regulated by" in term_map
        assert term_map["regulated by"].relationship == "ontology_inverse"
        assert (
            term_map["regulated by"].source_uri
            == "https://example.org/onto/regulatedBy"
        )
        assert term_map["regulated by"].release_id == approved.id
        assert "legacy controls" not in term_map

        # Deterministic ordering across repeated calls
        trace_repeat = await expander.expand_query("Who regulates Central Bank?")
        assert [t.term for t in trace.terms] == [
            t.term for t in trace_repeat.terms
        ]
        assert trace.expanded_query == trace_repeat.expanded_query

        # Strict max_expanded_terms budget (original + at most 2 added terms)
        budgeted = await expander.expand_query(
            "Who regulates Central Bank?",
            policy=ExpansionPolicy(max_expanded_terms=2),
        )
        assert len(budgeted.terms) == 3
        assert budgeted.terms[0].relationship == "original"

        # Metrics dictionary preserves provenance fields
        metrics = budgeted.to_metrics_dict()
        assert metrics["expansion_applied"] is True
        assert metrics["expanded_term_count"] == 3
        assert metrics["expanded_terms"][1]["source_uri"] is not None
        assert metrics["expanded_terms"][1]["release_id"] == str(approved.id)


@pytest.mark.asyncio
async def test_ontology_expander_release_pinning_and_no_match() -> None:
    """Pinned release_ids restricts scope; unmatched query stays unchanged."""
    from rag_foundry.retrieval.ontology_expansion import OntologyQueryExpander

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        approved, draft, _ = await _seed_ontology_releases(session)

        expander = OntologyQueryExpander(session_or_factory=session)

        # Pinning to a draft release yields zero expansion
        draft_trace = await expander.expand_query(
            "Central Bank", release_ids=[draft.id]
        )
        assert draft_trace.expansion_applied is False
        assert draft_trace.expanded_query == "Central Bank"
        assert draft_trace.release_ids == []

        # Pinning to approved release succeeds, unmatched query stays untouched
        no_match = await expander.expand_query(
            "Quantum entanglement", release_ids=[approved.id]
        )
        assert no_match.expansion_applied is False
        assert no_match.expanded_query == "Quantum entanglement"
        assert len(no_match.terms) == 1

