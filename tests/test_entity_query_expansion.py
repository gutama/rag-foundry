"""Tests for workspace-scoped authorized entity query expansion (ADR-0016)."""

import uuid

import pytest

from rag_foundry.db.models import AssertionRecord, Base, EntityRecord
from rag_foundry.db.session import get_sessionmaker
from rag_foundry.retrieval.security import (
    SecurityAuthorizationError,
    SecurityContext,
)


async def _seed_entities(session):
    """Seed active, merged, deprecated, cross-workspace entities and assertions."""
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()
    prof_1 = uuid.uuid4()
    prof_2 = uuid.uuid4()

    survivor = EntityRecord(
        id=uuid.uuid4(),
        workspace_id=ws_a,
        semantic_profile_id=prof_1,
        canonical_uri="urn:entity:acme_holdings",
        ontology_class_uri="https://example.org/onto/Organization",
        preferred_labels={"en": "Acme Holdings"},
        aliases={"en": ["ACME Corp", "Acme Group"]},
        status="active",
    )
    merged_mid = EntityRecord(
        id=uuid.uuid4(),
        workspace_id=ws_a,
        semantic_profile_id=prof_1,
        canonical_uri="urn:entity:acme_inc",
        ontology_class_uri="https://example.org/onto/Organization",
        preferred_labels={"en": "Acme Incorporated"},
        aliases={"en": ["Acme Old"]},
        status="merged",
        merged_into_id=survivor.id,
    )
    merged_leaf = EntityRecord(
        id=uuid.uuid4(),
        workspace_id=ws_a,
        semantic_profile_id=prof_1,
        canonical_uri="urn:entity:acme_legacy",
        ontology_class_uri="https://example.org/onto/Organization",
        preferred_labels={"en": "Acme Legacy Co"},
        aliases={"en": ["ALC"]},
        status="merged",
        merged_into_id=merged_mid.id,
    )
    deprecated_entity = EntityRecord(
        id=uuid.uuid4(),
        workspace_id=ws_a,
        semantic_profile_id=prof_1,
        canonical_uri="urn:entity:acme_deprecated",
        ontology_class_uri="https://example.org/onto/Organization",
        preferred_labels={"en": "Acme Holdings"},
        aliases={"en": ["Deprecated Shadow Alias"]},
        status="deprecated",
    )
    other_profile = EntityRecord(
        id=uuid.uuid4(),
        workspace_id=ws_a,
        semantic_profile_id=prof_2,
        canonical_uri="urn:entity:acme_other_profile",
        ontology_class_uri="https://example.org/onto/Organization",
        preferred_labels={"en": "Acme Holdings"},
        aliases={"en": ["Other Profile Alias"]},
        status="active",
    )
    other_workspace = EntityRecord(
        id=uuid.uuid4(),
        workspace_id=ws_b,
        semantic_profile_id=prof_1,
        canonical_uri="urn:entity:acme_secret_tenant",
        ontology_class_uri="https://example.org/onto/Organization",
        preferred_labels={"en": "Acme Holdings"},
        aliases={"en": ["Cross Workspace Secret Alias"]},
        status="active",
    )

    # Unapproved extracted SemanticAssertion that MUST NOT produce expansions
    unapproved_assertion = AssertionRecord(
        id=uuid.uuid4(),
        workspace_id=ws_a,
        semantic_profile_id=prof_1,
        subject_entity_id=survivor.id,
        property_uri="https://example.org/onto/altName",
        literal_value="Unapproved Extracted Alias",
        source_chunk_ids=[],
        origin="extracted",
        extraction_method="llm",
        confidence=0.65,
        status="candidate",
        requires_review=True,
    )

    session.add_all(
        [
            survivor,
            merged_mid,
            merged_leaf,
            deprecated_entity,
            other_profile,
            other_workspace,
            unapproved_assertion,
        ]
    )
    await session.commit()
    return ws_a, ws_b, prof_1, prof_2, survivor


@pytest.mark.asyncio
async def test_entity_expander_active_aliases_isolation_and_no_assertions() -> None:
    """Expands active entity aliases strictly within workspace & profile."""
    from rag_foundry.retrieval.ontology_expansion import EntityQueryExpander

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        ws_a, _, prof_1, _, survivor = await _seed_entities(session)

        sec_ctx = SecurityContext(
            user_id="analyst_1",
            allowed_workspaces=[ws_a],
            allowed_security_domains=["public"],
        )
        expander = EntityQueryExpander(session_or_factory=session)

        trace = await expander.expand_query(
            "ACME Corp compliance report",
            workspace_id=ws_a,
            semantic_profile_id=prof_1,
            security_context=sec_ctx,
        )
        assert trace.expansion_applied is True
        assert "entity" in trace.sources_consulted

        term_map = {t.term: t for t in trace.terms}
        assert "Acme Holdings" in term_map
        assert term_map["Acme Holdings"].relationship == "preferred_label"
        assert term_map["Acme Holdings"].source_type == "entity"
        assert term_map["Acme Holdings"].source_uri == survivor.canonical_uri
        assert term_map["Acme Holdings"].entity_id == survivor.id

        assert "Acme Group" in term_map
        assert term_map["Acme Group"].relationship == "entity_alias"
        assert term_map["Acme Group"].entity_id == survivor.id

        # Strict isolation & governance checks
        assert "Deprecated Shadow Alias" not in term_map
        assert "Other Profile Alias" not in term_map
        assert "Cross Workspace Secret Alias" not in term_map
        assert "Unapproved Extracted Alias" not in term_map


@pytest.mark.asyncio
async def test_entity_expander_resolves_chained_merged_redirects() -> None:
    """Merged entity aliases redirect to active canonical survivor."""
    from rag_foundry.retrieval.ontology_expansion import EntityQueryExpander

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)
        ws_a, _, prof_1, _, survivor = await _seed_entities(session)

        sec_ctx = SecurityContext(
            user_id="analyst_1",
            allowed_workspaces=[ws_a],
            allowed_security_domains=["public"],
        )
        expander = EntityQueryExpander(session_or_factory=session)

        # Query mentions alias 'ALC' of merged_leaf -> merged_mid -> survivor
        trace = await expander.expand_query(
            "ALC annual audit",
            workspace_id=ws_a,
            semantic_profile_id=prof_1,
            security_context=sec_ctx,
        )
        assert trace.expansion_applied is True
        term_map = {t.term: t for t in trace.terms}
        assert "Acme Holdings" in term_map
        assert term_map["Acme Holdings"].relationship == "entity_redirect"
        assert term_map["Acme Holdings"].source_uri == survivor.canonical_uri
        assert term_map["Acme Holdings"].entity_id == survivor.id
        assert "ACME Corp" in term_map
        assert "Acme Group" in term_map


@pytest.mark.asyncio
async def test_entity_expander_authorizes_before_loading_vocabulary() -> None:
    """Unauthorized workspace fails before DB query; empty domains fails closed."""
    from rag_foundry.retrieval.ontology_expansion import EntityQueryExpander

    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()

    class _ExplodingSessionFactory:
        def __call__(self):
            raise AssertionError(
                "DB must not be queried before caller authorization!"
            )

    expander = EntityQueryExpander(
        session_or_factory=_ExplodingSessionFactory()  # type: ignore[arg-type]
    )

    # 1. Unauthorized workspace raises SecurityAuthorizationError without DB access
    unauth_ctx = SecurityContext(
        user_id="intruder",
        allowed_workspaces=[ws_b],
        allowed_security_domains=["public"],
    )
    with pytest.raises(SecurityAuthorizationError):
        await expander.expand_query(
            "Acme Holdings",
            workspace_id=ws_a,
            security_context=unauth_ctx,
        )

    # 2. Authorized workspace with zero allowed domains fails closed without DB access
    no_domain_ctx = SecurityContext(
        user_id="restricted_user",
        allowed_workspaces=[ws_a],
        allowed_security_domains=[],
    )
    trace = await expander.expand_query(
        "Acme Holdings",
        workspace_id=ws_a,
        security_context=no_domain_ctx,
    )
    assert trace.expansion_applied is False
    assert trace.expanded_query == "Acme Holdings"
    assert trace.reason == "no_allowed_security_domains"
