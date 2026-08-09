"""Unit tests for TaxonomyBrowserService concept tree traversals."""
# Also covers label search functionality.

import pytest


@pytest.fixture
def sample_taxonomy_scheme():
    """Create sample SKOS taxonomy scheme for browser testing."""
    from rag_foundry.taxonomy.models import (
        SKOSConceptModel,
        SKOSConceptSchemeModel,
    )

    c1 = SKOSConceptModel(
        scheme_uri="http://id.example.org/schemes/finance",
        uri="http://id.example.org/finance",
        pref_label="Finance",
        alt_labels=["Financial Services"],
        broader_uris=[],
    )
    c2 = SKOSConceptModel(
        scheme_uri="http://id.example.org/schemes/finance",
        uri="http://id.example.org/banking",
        pref_label="Banking",
        alt_labels=["Retail Banking"],
        broader_uris=["http://id.example.org/finance"],
    )
    c3 = SKOSConceptModel(
        scheme_uri="http://id.example.org/schemes/finance",
        uri="http://id.example.org/credit",
        pref_label="Credit & Loans",
        alt_labels=["Lending"],
        broader_uris=["http://id.example.org/banking"],
    )

    return SKOSConceptSchemeModel(
        scheme_id="finance_v1",
        uri="http://id.example.org/schemes/finance",
        title="Finance Taxonomy",
        concepts=[c1, c2, c3],
    )


@pytest.mark.asyncio
async def test_taxonomy_browser_roots_and_narrower(sample_taxonomy_scheme):
    """Test root concept lookups and narrower tree traversals."""
    from rag_foundry.taxonomy.browser import TaxonomyBrowserService

    browser = TaxonomyBrowserService(scheme=sample_taxonomy_scheme)
    roots = browser.get_root_concepts()
    assert len(roots) == 1
    assert roots[0].pref_label == "Finance"

    children = browser.get_narrower_concepts("http://id.example.org/finance")
    assert len(children) == 1
    assert children[0].pref_label == "Banking"

    grand_children = browser.get_narrower_concepts(
        "http://id.example.org/banking"
    )
    assert len(grand_children) == 1
    assert grand_children[0].pref_label == "Credit & Loans"


@pytest.mark.asyncio
async def test_taxonomy_browser_search_concepts(sample_taxonomy_scheme):
    """Test TaxonomyBrowserService searching concepts by label and alt_label."""
    from rag_foundry.taxonomy.browser import TaxonomyBrowserService

    browser = TaxonomyBrowserService(scheme=sample_taxonomy_scheme)
    results = browser.search_concepts("Lending")
    assert len(results) == 1
    assert results[0].pref_label == "Credit & Loans"

    results_fuzzy = browser.search_concepts("Financial")
    assert len(results_fuzzy) == 1
    assert results_fuzzy[0].pref_label == "Finance"
