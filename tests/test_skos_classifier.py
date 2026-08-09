"""Unit tests for SemanticClassifier, text mention resolution, and governance tagging."""

import pytest


@pytest.fixture
def sample_skos_scheme():
    """Create sample SKOS scheme for classification testing."""
    from rag_foundry.taxonomy.models import (
        SKOSConceptModel,
        SKOSConceptSchemeModel,
    )

    c1 = SKOSConceptModel(
        scheme_uri="http://id.example.org/schemes/finance",
        uri="http://id.example.org/finance",
        pref_label="Finance",
        alt_labels=["Financial Analysis", "Capital"],
    )
    c2 = SKOSConceptModel(
        scheme_uri="http://id.example.org/schemes/finance",
        uri="http://id.example.org/legacy_rate",
        pref_label="LIBOR Rate",
        alt_labels=["LIBOR"],
        is_deprecated=True,
        deprecation_note="Replaced by SOFR rate.",
    )
    return SKOSConceptSchemeModel(
        scheme_id="finance_v2",
        uri="http://id.example.org/schemes/finance",
        title="Finance Taxonomy v2",
        version="2.0.0",
        concepts=[c1, c2],
    )


@pytest.mark.asyncio
async def test_semantic_classifier_label_matching(sample_skos_scheme):
    """Test SemanticClassifier matching prefLabels and altLabels in text."""
    from rag_foundry.taxonomy.classifier import SemanticClassifier

    classifier = SemanticClassifier(scheme=sample_skos_scheme)
    text = (
        "The report includes detailed Financial Analysis for Q1 performance."
    )

    result = classifier.classify_text(text=text)
    assert len(result.assignments) >= 1
    assert result.taxonomy_version == "2.0.0"

    assignment = result.assignments[0]
    assert assignment.concept_uri == "http://id.example.org/finance"
    assert assignment.confidence_score >= 0.8


@pytest.mark.asyncio
async def test_semantic_classifier_flags_deprecated_concepts(
    sample_skos_scheme,
):
    """Test SemanticClassifier flagging deprecated concepts in classification output."""
    from rag_foundry.taxonomy.classifier import SemanticClassifier

    classifier = SemanticClassifier(scheme=sample_skos_scheme)
    text = "Contracts referenced the historical LIBOR Rate for interest computation."

    result = classifier.classify_text(text=text)
    assert len(result.deprecated_concepts_flagged) == 1
    assert "http://id.example.org/legacy_rate" in result.deprecated_concepts_flagged
