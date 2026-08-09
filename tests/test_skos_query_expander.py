"""Unit tests for TaxonomyQueryExpander search query expansion (ADR-0016)."""

import pytest


@pytest.fixture
def sample_expansion_scheme():
    """Create sample SKOS scheme for query expansion testing."""
    from rag_foundry.taxonomy.models import (
        SKOSConceptModel,
        SKOSConceptSchemeModel,
    )

    c1 = SKOSConceptModel(
        scheme_uri="http://id.example.org/schemes/banking",
        uri="http://id.example.org/finance",
        pref_label="Financial Services",
        alt_labels=["Finance"],
        broader_uris=[],
    )
    c2 = SKOSConceptModel(
        scheme_uri="http://id.example.org/schemes/banking",
        uri="http://id.example.org/banking",
        pref_label="Banking",
        alt_labels=["Retail Banking"],
        broader_uris=["http://id.example.org/finance"],
    )
    c3 = SKOSConceptModel(
        scheme_uri="http://id.example.org/schemes/banking",
        uri="http://id.example.org/lending",
        pref_label="Lending",
        alt_labels=["Loans", "Credit"],
        broader_uris=["http://id.example.org/banking"],
    )
    return SKOSConceptSchemeModel(
        scheme_id="banking_v1",
        uri="http://id.example.org/schemes/banking",
        title="Banking Taxonomy",
        concepts=[c1, c2, c3],
    )


@pytest.mark.asyncio
async def test_taxonomy_query_expander_synonym_and_hierarchy(
    sample_expansion_scheme,
):
    """Test query expansion with synonyms, broader, and narrower concepts."""
    from rag_foundry.taxonomy.query_expander import TaxonomyQueryExpander

    expander = TaxonomyQueryExpander(scheme=sample_expansion_scheme)
    result = expander.expand_query(query="Lending regulations")

    assert result.original_query == "Lending regulations"
    assert result.execution_time_ms < 15.0  # Performance requirement

    terms = [t.term for t in result.expanded_terms]
    assert "Lending" in terms
    assert "Loans" in terms or "Credit" in terms  # AltLabel synonym
    assert "Banking" in terms  # Broader concept

    # Check weight decay
    banking_term = next(t for t in result.expanded_terms if t.term == "Banking")
    assert banking_term.weight == 0.7  # Broader decay weight


@pytest.mark.asyncio
async def test_taxonomy_query_expander_lexical_output(sample_expansion_scheme):
    """Test TaxonomyQueryExpander generates expanded lexical query."""
    from rag_foundry.taxonomy.query_expander import TaxonomyQueryExpander

    expander = TaxonomyQueryExpander(scheme=sample_expansion_scheme)
    result = expander.expand_query(query="Lending")

    assert len(result.expanded_terms) >= 2
    assert "Lending" in result.expanded_lexical_query
