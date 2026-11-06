"""Tests for deterministic Turtle export of ontology releases."""

from pathlib import Path

from rag_foundry.ontology import serialization as ser
from rag_foundry.ontology.models import (
    OntologyClass,
    OntologyProperty,
    OntologyRelease,
)
from tests.ontology_samples import EX, XSD, build_finance_release

GOLDEN = Path(__file__).parent / "fixtures" / "ontology" / "finance.ttl"


def _release(ontology_uri, classes, properties=()):
    """Build a minimal release."""
    return OntologyRelease(
        ontology_uri=ontology_uri,
        version="1",
        title="T",
        classes=list(classes),
        properties=list(properties),
    )


def test_export_matches_golden_file():
    """The sample release exports exactly to the reviewed golden file."""
    assert ser.export_turtle(build_finance_release()) == GOLDEN.read_text()


def test_export_is_deterministic():
    """Equal releases export to identical text."""
    first = ser.export_turtle(build_finance_release())
    assert first == ser.export_turtle(build_finance_release())


def test_term_order_does_not_change_output():
    """Terms are sorted, so input order is irrelevant."""
    release = build_finance_release()
    shuffled = release.model_copy(
        update={
            "classes": list(reversed(release.classes)),
            "properties": list(reversed(release.properties)),
        }
    )
    assert ser.export_turtle(shuffled) == ser.export_turtle(release)


def test_prefix_declarations():
    """Vocabulary prefixes come first, then the ontology namespace."""
    lines = ser.export_turtle(build_finance_release()).splitlines()
    assert lines[:6] == [
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix rf: <urn:rag-foundry:vocab#> .",
        "@prefix sh: <http://www.w3.org/ns/shacl#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix : <http://example.org/finance#> .",
    ]


def test_namespace_ending_in_slash_is_used_as_is():
    """An ontology IRI ending in '/' or '#' is itself the namespace."""
    ns = "http://example.org/onto/"
    release = _release(
        ns, [OntologyClass(uri=ns + "Bank", preferred_labels={"en": "B"})]
    )
    text = ser.export_turtle(release)
    assert f"@prefix : <{ns}> ." in text
    assert f"<{ns}> a owl:Ontology" in text
    assert ":Bank a owl:Class" in text


def test_iris_that_cannot_be_prefixed_are_written_in_full():
    """Foreign IRIs and awkward local names use <...> form."""
    onto = "http://example.org/onto"
    classes = [
        OntologyClass(uri=onto + "#1st", preferred_labels={"en": "a"}),
        OntologyClass(uri=onto + "#a.b", preferred_labels={"en": "b"}),
        OntologyClass(
            uri="http://other.example/Thing", preferred_labels={"en": "c"}
        ),
        OntologyClass(uri="urn:x:y", preferred_labels={"en": "d"}),
    ]
    text = ser.export_turtle(_release(onto, classes))
    assert "<http://example.org/onto#1st> a owl:Class" in text
    assert "<http://example.org/onto#a.b> a owl:Class" in text
    assert "<http://other.example/Thing> a owl:Class" in text
    assert "<urn:x:y> a owl:Class" in text


def test_string_literals_are_escaped():
    """Quotes, backslashes, newlines and control characters are escaped."""
    onto = "http://example.org/onto"
    cls = OntologyClass(
        uri=onto + "#Odd",
        preferred_labels={"en": 'say "hi"\\ now'},
        description={"en": "line one\nline two\ttab\r\x07bell"},
    )
    text = ser.export_turtle(_release(onto, [cls]))
    assert r'rdfs:label "say \"hi\"\\ now"@en' in text
    assert r'rdfs:comment "line one\nline two\ttab\r\u0007bell"@en' in text


def test_non_ascii_text_is_written_verbatim():
    """Turtle is UTF-8, so non-ASCII labels need no escaping."""
    onto = "http://example.org/onto"
    cls = OntologyClass(
        uri=onto + "#Kafe", preferred_labels={"id": "Kafé ☕"}
    )
    assert '"Kafé ☕"@id' in ser.export_turtle(_release(onto, [cls]))


def test_typed_allowed_values_and_booleans():
    """Non-string allowed values carry their datatype."""
    onto = "http://example.org/onto"
    cls = OntologyClass(uri=onto + "#Bank", preferred_labels={"en": "Bank"})
    prop = OntologyProperty(
        uri=onto + "#open",
        preferred_labels={"en": "open"},
        property_type="data",
        datatype=XSD + "boolean",
        constraints=[
            {"kind": "allowed_values", "allowed_values": ["true"]}
        ],
    )
    text = ser.export_turtle(_release(onto, [cls], [prop]))
    assert 'sh:in ( "true"^^xsd:boolean ) .' in text
    assert "rf:temporal false" in text


def test_every_class_iri_appears_in_output():
    """Each term of the release is present in the Turtle output."""
    release = build_finance_release()
    text = ser.export_turtle(release)
    for term in [*release.classes, *release.properties]:
        assert ":" + term.uri[len(EX):] + " a owl:" in text
