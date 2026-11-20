"""Unit tests for authorized AssertionContextLoader (ADR-0005 & ADR-0013)."""

import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from rag_foundry.db.models import (
    AssertionRecord,
    Base,
    Chunk,
    Document,
    EntityRecord,
)
from rag_foundry.generation.models import KnowledgeAuthority
from rag_foundry.retrieval.security import (
    SecurityAuthorizationError,
    SecurityContext,
)


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Create an isolated in-memory async SQLite session factory."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_fixtures(
    factory: async_sessionmaker[AsyncSession],
) -> dict[str, uuid.UUID]:
    """Seed documents, chunks, entities, and assertions across domains."""
    ws_id = uuid.uuid4()
    other_ws = uuid.uuid4()
    profile_id = uuid.uuid4()
    other_profile = uuid.uuid4()

    doc_pub_id = uuid.uuid4()
    doc_res_id = uuid.uuid4()
    chunk_pub_id = uuid.uuid4()
    chunk_res_id = uuid.uuid4()

    ent_policy_id = uuid.uuid4()
    ent_regulator_id = uuid.uuid4()

    async with factory() as session:
        session.add_all(
            [
                Document(
                    id=doc_pub_id,
                    document_id=uuid.uuid4(),
                    workspace_id=ws_id,
                    title="Public Retention Policy",
                    mime_type="application/pdf",
                    checksum="a" * 64,
                    page_count=5,
                    parser_name="native_pdf",
                    parser_version="1.0",
                    semantic_profile_id=profile_id,
                ),
                Document(
                    id=doc_res_id,
                    document_id=uuid.uuid4(),
                    workspace_id=ws_id,
                    title="Restricted Risk Annex",
                    mime_type="application/pdf",
                    checksum="b" * 64,
                    page_count=3,
                    parser_name="native_pdf",
                    parser_version="1.0",
                    semantic_profile_id=profile_id,
                ),
                Chunk(
                    id=chunk_pub_id,
                    document_version_id=doc_pub_id,
                    workspace_id=ws_id,
                    chunk_index=0,
                    text="Records must be retained for 7 years.",
                    section_path=["Compliance", "Retention"],
                    page_numbers=[2],
                    bounding_boxes=[
                        {"page": 2, "l": 0.1, "t": 0.2, "r": 0.8, "b": 0.3}
                    ],
                    security_domain="public",
                    checksum="c" * 64,
                    chunker_name="structural",
                    chunker_version="1.0",
                    semantic_profile_id=profile_id,
                ),
                Chunk(
                    id=chunk_res_id,
                    document_version_id=doc_res_id,
                    workspace_id=ws_id,
                    chunk_index=0,
                    text="Board override requires Chief Risk Officer sign-off.",
                    section_path=["Governance", "Overrides"],
                    page_numbers=[1],
                    bounding_boxes=[],
                    security_domain="restricted",
                    checksum="d" * 64,
                    chunker_name="structural",
                    chunker_version="1.0",
                    semantic_profile_id=profile_id,
                ),
                EntityRecord(
                    id=ent_policy_id,
                    workspace_id=ws_id,
                    semantic_profile_id=profile_id,
                    canonical_uri="http://id.example.org/policy/retention",
                    ontology_class_uri="http://example.org/ont#Policy",
                    preferred_labels={"en": "Retention Policy"},
                ),
                EntityRecord(
                    id=ent_regulator_id,
                    workspace_id=ws_id,
                    semantic_profile_id=profile_id,
                    canonical_uri="http://id.example.org/org/regulator",
                    ontology_class_uri="http://example.org/ont#Organization",
                    preferred_labels={"en": "Financial Regulator"},
                ),
            ]
        )
        await session.flush()

        # 1. Curated & approved literal assertion (public chunk)
        curated_pub = AssertionRecord(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            semantic_profile_id=profile_id,
            subject_entity_id=ent_policy_id,
            property_uri="http://example.org/ont#retentionYears",
            literal_value=7,
            source_chunk_ids=[str(chunk_pub_id)],
            origin="curated",
            extraction_method="steward",
            confidence=1.0,
            status="approved",
        )
        # 2. Extracted candidate object assertion (public chunk)
        extracted_pub = AssertionRecord(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            semantic_profile_id=profile_id,
            subject_entity_id=ent_policy_id,
            property_uri="http://example.org/ont#regulatedBy",
            object_entity_id=ent_regulator_id,
            source_chunk_ids=[str(chunk_pub_id)],
            origin="extracted",
            extraction_method="llm",
            confidence=0.78,
            status="candidate",
        )
        # 3. Extracted-then-approved assertion -> classified as CURATED
        promoted_pub = AssertionRecord(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            semantic_profile_id=profile_id,
            subject_entity_id=ent_policy_id,
            property_uri="http://example.org/ont#reviewCadence",
            literal_value="annual",
            source_chunk_ids=[str(chunk_pub_id)],
            origin="extracted",
            extraction_method="llm",
            confidence=0.90,
            status="approved",
        )
        # 4. Restricted assertion (restricted chunk)
        restricted_cur = AssertionRecord(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            semantic_profile_id=profile_id,
            subject_entity_id=ent_policy_id,
            property_uri="http://example.org/ont#overrideApprover",
            literal_value="Chief Risk Officer",
            source_chunk_ids=[str(chunk_res_id)],
            origin="curated",
            extraction_method="steward",
            confidence=1.0,
            status="approved",
        )
        # 5. Mixed-domain assertion (public + restricted chunks -> MUST hide
        #    from public-only caller to prevent restricted leakage)
        mixed_domains = AssertionRecord(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            semantic_profile_id=profile_id,
            subject_entity_id=ent_policy_id,
            property_uri="http://example.org/ont#mixedNote",
            literal_value="Secret synthesis",
            source_chunk_ids=[str(chunk_pub_id), str(chunk_res_id)],
            origin="curated",
            extraction_method="steward",
            confidence=0.95,
            status="approved",
        )
        # 6. Rejected and superseded assertions -> ALWAYS excluded
        rejected = AssertionRecord(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            semantic_profile_id=profile_id,
            subject_entity_id=ent_policy_id,
            property_uri="http://example.org/ont#obsoleteRule",
            literal_value="1 year",
            source_chunk_ids=[str(chunk_pub_id)],
            origin="extracted",
            extraction_method="llm",
            confidence=0.5,
            status="rejected",
        )
        superseded = AssertionRecord(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            semantic_profile_id=profile_id,
            subject_entity_id=ent_policy_id,
            property_uri="http://example.org/ont#oldRetention",
            literal_value=3,
            source_chunk_ids=[str(chunk_pub_id)],
            origin="curated",
            extraction_method="steward",
            confidence=1.0,
            status="superseded",
        )
        # 7. Extracted assertion with NO source chunks -> fails closed
        orphan_ext = AssertionRecord(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            semantic_profile_id=profile_id,
            subject_entity_id=ent_policy_id,
            property_uri="http://example.org/ont#unprovenClaim",
            literal_value="unverified",
            source_chunk_ids=[],
            origin="extracted",
            extraction_method="llm",
            confidence=0.6,
            status="candidate",
        )
        # 8. Different semantic profile -> filtered out when profile specified
        other_prof_row = AssertionRecord(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            semantic_profile_id=other_profile,
            subject_entity_id=ent_policy_id,
            property_uri="http://example.org/ont#otherProfileRule",
            literal_value="ignored",
            source_chunk_ids=[str(chunk_pub_id)],
            origin="curated",
            extraction_method="steward",
            confidence=1.0,
            status="approved",
        )

        session.add_all(
            [
                curated_pub,
                extracted_pub,
                promoted_pub,
                restricted_cur,
                mixed_domains,
                rejected,
                superseded,
                orphan_ext,
                other_prof_row,
            ]
        )
        await session.commit()

    return {
        "ws_id": ws_id,
        "other_ws": other_ws,
        "profile_id": profile_id,
        "doc_pub_id": doc_pub_id,
        "chunk_pub_id": chunk_pub_id,
        "chunk_res_id": chunk_res_id,
        "ent_policy_id": ent_policy_id,
        "ent_regulator_id": ent_regulator_id,
    }


@pytest.mark.asyncio
async def test_assertion_loader_authorization_and_classification(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Loader enforces SecurityContext, excludes rejected, and classifies."""
    from rag_foundry.generation.context import (
        AssertionContextLoader,
        AssertionContextProvider,
        load_chunk_security_domains,
    )

    ids = await _seed_fixtures(session_factory)
    loader = AssertionContextLoader(session_factory)
    assert isinstance(loader, AssertionContextProvider)

    # 1. Unauthorized workspace raises SecurityAuthorizationError
    unauth_ctx = SecurityContext(
        user_id="eve",
        allowed_workspaces=[ids["other_ws"]],
        allowed_security_domains=["public"],
    )
    with pytest.raises(SecurityAuthorizationError):
        await loader.load_assertions(
            workspace_id=ids["ws_id"],
            security_context=unauth_ctx,
            semantic_profile_id=ids["profile_id"],
        )

    # 2. Empty allowed_security_domains fails closed with []
    empty_dom_ctx = SecurityContext(
        user_id="bob",
        allowed_workspaces=[ids["ws_id"]],
        allowed_security_domains=[],
    )
    empty_res = await loader.load_assertions(
        workspace_id=ids["ws_id"],
        security_context=empty_dom_ctx,
        semantic_profile_id=ids["profile_id"],
    )
    assert empty_res == []

    # 3. Public-only user sees only public curated + public extracted
    #    (NO restricted, NO mixed-domain, NO rejected/superseded, NO orphan)
    pub_ctx = SecurityContext(
        user_id="alice",
        allowed_workspaces=[ids["ws_id"]],
        allowed_security_domains=["public"],
    )
    pub_entries = await loader.load_assertions(
        workspace_id=ids["ws_id"],
        security_context=pub_ctx,
        semantic_profile_id=ids["profile_id"],
    )
    assert len(pub_entries) == 3

    curated_entries = [
        e for e in pub_entries if e.authority == KnowledgeAuthority.CURATED
    ]
    extracted_entries = [
        e for e in pub_entries if e.authority == KnowledgeAuthority.EXTRACTED
    ]
    assert len(curated_entries) == 2
    assert len(extracted_entries) == 1

    # Curated entries come first and carry full chunk/document provenance
    assert "Retention Policy" in curated_entries[0].text
    assert "7" in curated_entries[0].text
    assert curated_entries[0].document_version_id == ids["doc_pub_id"]
    assert curated_entries[0].document_title == "Public Retention Policy"
    assert curated_entries[0].page_numbers == (2,)
    assert len(curated_entries[0].bounding_boxes) == 1
    assert curated_entries[0].security_domains == ("public",)

    # Object-relation assertion resolves both subject and object labels
    assert "Retention Policy" in extracted_entries[0].text
    assert "Financial Regulator" in extracted_entries[0].text
    assert ids["ent_policy_id"] in extracted_entries[0].entity_ids
    assert ids["ent_regulator_id"] in extracted_entries[0].entity_ids

    # 4. include_extracted_candidates=False excludes candidate assertions
    curated_only = await loader.load_assertions(
        workspace_id=ids["ws_id"],
        security_context=pub_ctx,
        semantic_profile_id=ids["profile_id"],
        include_extracted_candidates=False,
    )
    assert len(curated_only) == 2
    assert all(e.authority == KnowledgeAuthority.CURATED for e in curated_only)

    # 5. Privileged user with public + restricted sees all 5 valid assertions
    priv_ctx = SecurityContext(
        user_id="cro",
        allowed_workspaces=[ids["ws_id"]],
        allowed_security_domains=["public", "restricted"],
    )
    priv_entries = await loader.load_assertions(
        workspace_id=ids["ws_id"],
        security_context=priv_ctx,
        semantic_profile_id=ids["profile_id"],
    )
    assert len(priv_entries) == 5
    mixed_matches = [
        e for e in priv_entries if "Secret synthesis" in e.text
    ]
    assert len(mixed_matches) == 1
    assert set(mixed_matches[0].security_domains) == {"public", "restricted"}

    # 6. Chunk security domain helper resolves domains scoped to workspace
    dom_map = await load_chunk_security_domains(
        session_factory,
        ids["ws_id"],
        [ids["chunk_pub_id"], ids["chunk_res_id"]],
    )
    assert dom_map == {
        ids["chunk_pub_id"]: "public",
        ids["chunk_res_id"]: "restricted",
    }


@pytest.mark.asyncio
async def test_assertion_loader_chunkless_curated_and_query_ranking(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Chunkless curated rules enforce default domain; query_text ranks hits."""
    from rag_foundry.generation.context import AssertionContextLoader

    ws_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    ent_id = uuid.uuid4()

    async with session_factory() as session:
        session.add(
            EntityRecord(
                id=ent_id,
                workspace_id=ws_id,
                semantic_profile_id=profile_id,
                canonical_uri="http://id.example.org/org/treasury",
                ontology_class_uri="http://example.org/ont#Department",
                preferred_labels={"en": "Treasury Department"},
            )
        )
        await session.flush()
        session.add_all(
            [
                AssertionRecord(
                    id=uuid.uuid4(),
                    workspace_id=ws_id,
                    semantic_profile_id=profile_id,
                    subject_entity_id=ent_id,
                    property_uri="http://example.org/ont#custodian",
                    literal_value="Central Vault",
                    source_chunk_ids=[],
                    origin="curated",
                    extraction_method="steward",
                    confidence=1.0,
                    status="approved",
                ),
                AssertionRecord(
                    id=uuid.uuid4(),
                    workspace_id=ws_id,
                    semantic_profile_id=profile_id,
                    subject_entity_id=ent_id,
                    property_uri="http://example.org/ont#encryptionStandard",
                    literal_value="AES-256-GCM",
                    source_chunk_ids=[],
                    origin="curated",
                    extraction_method="steward",
                    confidence=0.95,
                    status="approved",
                ),
            ]
        )
        await session.commit()

    loader = AssertionContextLoader(
        session_factory, default_curated_security_domain="internal"
    )

    # Caller without 'internal' domain cannot see chunkless curated rules
    pub_only = SecurityContext(
        user_id="guest",
        allowed_workspaces=[ws_id],
        allowed_security_domains=["public"],
    )
    assert (
        await loader.load_assertions(
            workspace_id=ws_id,
            security_context=pub_only,
            semantic_profile_id=profile_id,
        )
        == []
    )

    # Caller with 'internal' sees both, ranked by query_text token overlap
    internal_ctx = SecurityContext(
        user_id="analyst",
        allowed_workspaces=[ws_id],
        allowed_security_domains=["internal"],
    )
    ranked = await loader.load_assertions(
        workspace_id=ws_id,
        security_context=internal_ctx,
        semantic_profile_id=profile_id,
        query_text="What encryption standard does Treasury use?",
    )
    assert len(ranked) == 2
    assert "AES-256-GCM" in ranked[0].text
    assert ranked[0].evidence_id == "A1"
    assert ranked[0].security_domains == ("internal",)
