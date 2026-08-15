"""Unit tests for SKOS taxonomy query expansion retrieval integration (ADR-0016)."""

import uuid
import pytest

from rag_foundry.retrieval.models import RetrievalFilter, RetrievalQuery
from rag_foundry.taxonomy.models import SKOSConceptModel, SKOSConceptSchemeModel


@pytest.fixture
def banking_concept_scheme() -> SKOSConceptSchemeModel:
    """Fixture providing a sample SKOS taxonomy scheme for banking & capital rules."""
    scheme_uri = "urn:scheme:banking"
    c_broad = SKOSConceptModel(
        scheme_uri=scheme_uri,
        uri="urn:concept:capital_requirements",
        pref_label="Capital Requirements",
        alt_labels=["Capital Standards", "Prudential Capital"],
        broader_uris=[],
    )
    c_tier1 = SKOSConceptModel(
        scheme_uri=scheme_uri,
        uri="urn:concept:tier1_capital",
        pref_label="Tier 1 Capital",
        alt_labels=["Core Capital", "T1 Capital"],
        broader_uris=["urn:concept:capital_requirements"],
    )
    return SKOSConceptSchemeModel(
        scheme_id=str(uuid.uuid4()),
        uri=scheme_uri,
        title="Banking Regulation Taxonomy",
        version="1.0",
        concepts=[c_broad, c_tier1],
    )


def test_taxonomy_expansion_bridge_expands_query(banking_concept_scheme):
    """Test TaxonomyExpansionBridge enriches query text with prefLabel and altLabels."""
    from rag_foundry.retrieval.expansion import TaxonomyExpansionBridge

    bridge = TaxonomyExpansionBridge(scheme=banking_concept_scheme)
    ws_id = uuid.uuid4()

    query = RetrievalQuery(
        query_text="What are the T1 Capital ratios?",
        filter=RetrievalFilter(workspace_id=ws_id),
        enable_expansion=True,
    )

    expanded_query, trace = bridge.expand_retrieval_query(query)

    assert "Tier 1 Capital" in expanded_query.query_text
    assert "Core Capital" in expanded_query.query_text
    assert trace["expanded_term_count"] >= 2
    assert trace["expansion_applied"] is True


def test_taxonomy_expansion_bridge_disabled(banking_concept_scheme):
    """Test TaxonomyExpansionBridge leaves query untouched when enable_expansion is False."""
    from rag_foundry.retrieval.expansion import TaxonomyExpansionBridge

    bridge = TaxonomyExpansionBridge(scheme=banking_concept_scheme)
    ws_id = uuid.uuid4()

    query = RetrievalQuery(
        query_text="What are the T1 Capital ratios?",
        filter=RetrievalFilter(workspace_id=ws_id),
        enable_expansion=False,
    )

    expanded_query, trace = bridge.expand_retrieval_query(query)

    assert expanded_query.query_text == "What are the T1 Capital ratios?"
    assert trace["expansion_applied"] is False
