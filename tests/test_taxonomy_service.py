"""Unit tests for SKOS TaxonomyService and candidate entity resolution baseline."""

import uuid

import pytest


@pytest.mark.asyncio
async def test_taxonomy_service_create_and_get_concept():
    """Test creating a concept in TaxonomyService and retrieving by URI."""
    from rag_foundry.db.models import Base
    from rag_foundry.db.session import get_sessionmaker
    from rag_foundry.taxonomy.service import TaxonomyService

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        service = TaxonomyService(session=session)
        scheme_id = uuid.uuid4()

        concept = await service.create_concept(
            scheme_id=scheme_id,
            uri="http://example.org/taxonomies/finance/banking",
            pref_labels={"en": "Banking", "id": "Perbankan"},
            alt_labels={"en": ["Financial Services", "Retail Banking"]},
            broader_uris=["http://example.org/taxonomies/finance"],
        )

        assert concept.uri == "http://example.org/taxonomies/finance/banking"
        assert concept.pref_labels["en"] == "Banking"

        fetched = await service.get_concept_by_uri(
            "http://example.org/taxonomies/finance/banking"
        )
        assert fetched is not None
        assert fetched.pref_labels["id"] == "Perbankan"


@pytest.mark.asyncio
async def test_taxonomy_service_broader_narrower_queries():
    """Test broader and narrower concept relationship queries."""
    from rag_foundry.db.models import Base
    from rag_foundry.db.session import get_sessionmaker
    from rag_foundry.taxonomy.service import TaxonomyService

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        service = TaxonomyService(session=session)
        scheme_id = uuid.uuid4()

        # Parent concept
        await service.create_concept(
            scheme_id=scheme_id,
            uri="http://example.org/taxonomies/finance",
            pref_labels={"en": "Finance"},
        )

        # Child concept
        await service.create_concept(
            scheme_id=scheme_id,
            uri="http://example.org/taxonomies/finance/banking",
            pref_labels={"en": "Banking"},
            broader_uris=["http://example.org/taxonomies/finance"],
        )

        # Broader query for child
        broader_list = await service.get_broader_concepts(
            "http://example.org/taxonomies/finance/banking"
        )
        assert len(broader_list) == 1
        assert broader_list[0].uri == "http://example.org/taxonomies/finance"

        # Narrower query for parent
        narrower_list = await service.get_narrower_concepts(
            "http://example.org/taxonomies/finance"
        )
        assert len(narrower_list) == 1
        assert (
            narrower_list[0].uri
            == "http://example.org/taxonomies/finance/banking"
        )


@pytest.mark.asyncio
async def test_taxonomy_service_candidate_entity_resolution():
    """Test resolving surface text mentions against prefLabel and altLabel."""
    from rag_foundry.db.models import Base
    from rag_foundry.db.session import get_sessionmaker
    from rag_foundry.taxonomy.service import TaxonomyService

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        conn = await session.connection()
        await conn.run_sync(Base.metadata.create_all)

        service = TaxonomyService(session=session)
        scheme_id = uuid.uuid4()

        await service.create_concept(
            scheme_id=scheme_id,
            uri="http://example.org/taxonomies/ai",
            pref_labels={"en": "Artificial Intelligence"},
            alt_labels={"en": ["AI", "Machine Intelligence"]},
        )

        # Exact prefLabel match
        matches = await service.resolve_candidate_entities(
            mention="Artificial Intelligence"
        )
        assert len(matches) == 1
        assert matches[0].uri == "http://example.org/taxonomies/ai"

        # AltLabel match (case-insensitive)
        alt_matches = await service.resolve_candidate_entities(mention="ai")
        assert len(alt_matches) == 1
        assert alt_matches[0].uri == "http://example.org/taxonomies/ai"

        # Unmatched mention returns empty list
        no_matches = await service.resolve_candidate_entities(
            mention="Quantum Computing"
        )
        assert len(no_matches) == 0
