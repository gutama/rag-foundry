"""Unit tests for SKOS concept schemes and multi-format importers."""
# Also covers deprecation governance and CSV/JSON-LD exporters.

import pytest


@pytest.fixture
def sample_csv_skos():
    """Generate sample SKOS concept scheme in CSV format."""
    return (
        "uri,prefLabel,altLabels,broaderURIs,isDeprecated\n"
        "http://id.example.org/finance,Finance,"
        "Banking;Economics,,false\n"
        "http://id.example.org/banking,Banking,"
        "Retail Banking,"
        "http://id.example.org/finance,false\n"
        "http://id.example.org/legacy_tax,Legacy Tax,"
        "Old Tax,"
        "http://id.example.org/finance,true\n"
    )


@pytest.fixture
def sample_jsonld_skos():
    """Generate sample SKOS concept scheme in JSON-LD format."""
    return {
        "@context": {
            "skos": "http://www.w3.org/2004/02/skos/core#",
            "prefLabel": "skos:prefLabel",
            "altLabel": "skos:altLabel",
            "broader": "skos:broader",
        },
        "@graph": [
            {
                "@id": "http://id.example.org/risk",
                "@type": "skos:Concept",
                "prefLabel": "Risk Management",
                "altLabel": ["Risk", "Risk Mitigation"],
            }
        ],
    }


@pytest.mark.asyncio
async def test_skos_csv_importer_and_exporter(sample_csv_skos):
    """Test importing SKOS scheme from CSV and exporting back to CSV."""
    from rag_foundry.taxonomy.serialization import SKOSExporter, SKOSImporter

    importer = SKOSImporter()
    scheme = importer.import_csv(
        csv_content=sample_csv_skos,
        scheme_id="finance_v1",
        scheme_uri="http://id.example.org/schemes/finance",
    )

    assert scheme.title == "finance_v1"
    assert len(scheme.concepts) == 3

    banking = next(c for c in scheme.concepts if c.pref_label == "Banking")
    assert banking.broader_uris == ["http://id.example.org/finance"]
    assert "Retail Banking" in banking.alt_labels

    legacy = next(c for c in scheme.concepts if c.pref_label == "Legacy Tax")
    assert legacy.is_deprecated is True

    # Test CSV Export
    exporter = SKOSExporter()
    exported_csv = exporter.export_csv(scheme)
    assert "Finance" in exported_csv
    assert "Banking" in exported_csv


@pytest.mark.asyncio
async def test_skos_jsonld_importer_and_exporter(sample_jsonld_skos):
    """Test importing SKOS scheme from JSON-LD dict and exporting back."""
    from rag_foundry.taxonomy.serialization import SKOSExporter, SKOSImporter

    importer = SKOSImporter()
    scheme = importer.import_jsonld(
        data=sample_jsonld_skos,
        scheme_id="risk_v1",
        scheme_uri="http://id.example.org/schemes/risk",
    )

    assert len(scheme.concepts) == 1
    risk_concept = scheme.concepts[0]
    assert risk_concept.pref_label == "Risk Management"
    assert "Risk Mitigation" in risk_concept.alt_labels

    exporter = SKOSExporter()
    exported_jsonld = exporter.export_jsonld(scheme)
    assert "@graph" in exported_jsonld
