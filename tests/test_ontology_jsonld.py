"""Tests for JSON-LD ontology import and export (ADR-0011)."""

import copy
import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rag_foundry.db.models import Base
from rag_foundry.ontology import registry as reg
from rag_foundry.ontology import serialization as ser
from rag_foundry.ontology.models import (
    UnsupportedConstraintError,
    UnsupportedFeatureError,
)
from tests.ontology_samples import EX, ONTO, XSD, build_finance_release

OWL = "http://www.w3.org/2002/07/owl#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
SH = "http://www.w3.org/ns/shacl#"


def _nodes(document):
    """Index exported @graph nodes by @id (shapes by sh:path)."""
    nodes = {}
    for node in document["@graph"]:
        if node.get("@type") == "sh:PropertyShape":
            nodes["shape:" + node["sh:path"]["@id"]] = node
        else:
            nodes[node["@id"]] = node
    return nodes


def _terms(release):
    """Dump classes and properties, sorted by IRI, for equality checks."""
    return (
        sorted((c.model_dump() for c in release.classes),
               key=lambda c: c["uri"]),
        sorted((p.model_dump() for p in release.properties),
               key=lambda p: p["uri"]),
    )


def _minimal_document(**extra_nodes):
    """Build a small hand-written document using compact IRIs."""
    graph = [
        {
            "@id": "ex:",
            "@type": "owl:Ontology",
            "owl:versionInfo": "2.0",
            "rdfs:label": "Mini",
        },
        {
            "@id": "ex:Person",
            "@type": "owl:Class",
            "rdfs:label": "Person",
        },
    ]
    graph.extend(extra_nodes.values())
    return {
        "@context": {
            "ex": EX,
            "owl": OWL,
            "rdfs": RDFS,
            "sh": SH,
            "xsd": XSD,
        },
        "@graph": graph,
    }


# --- Export ---------------------------------------------------------------


def test_export_context_and_ontology_header():
    """The document declares its prefixes and describes the release."""
    document = ser.export_jsonld(build_finance_release())
    assert document["@context"] == {
        "owl": OWL,
        "rdfs": RDFS,
        "sh": SH,
        "xsd": XSD,
        "rf": ser.RF_NAMESPACE,
    }
    header = _nodes(document)[ONTO]
    assert header == {
        "@id": ONTO,
        "@type": "owl:Ontology",
        "owl:versionInfo": "1.0.0",
        "rdfs:label": "Finance Ontology",
        "rdfs:comment": "Sample ontology for tests",
    }


def test_export_class_nodes():
    """Classes carry labels, parents, rules and deprecation."""
    nodes = _nodes(ser.export_jsonld(build_finance_release()))
    bank = nodes[EX + "Bank"]
    assert bank["@type"] == "owl:Class"
    assert bank["rdfs:label"] == [
        {"@value": "Bank", "@language": "en"},
        {"@value": "Bank", "@language": "id"},
    ]
    assert bank["rdfs:subClassOf"] == [{"@id": EX + "Organization"}]
    assert bank["rdfs:comment"] == [
        {"@value": "A licensed deposit-taking institution", "@language": "en"}
    ]
    assert bank["rf:identityRule"] == [
        "same national bank code",
        "same legal name and jurisdiction",
    ]
    assert "owl:deprecated" not in bank
    assert nodes[EX + "SavingsAndLoan"]["owl:deprecated"] is True
    assert "rdfs:subClassOf" not in nodes[EX + "Agent"]


def test_export_property_nodes():
    """Properties carry typing, domain, range, inverse and flags."""
    nodes = _nodes(ser.export_jsonld(build_finance_release()))
    employs = nodes[EX + "employs"]
    assert employs["@type"] == "owl:ObjectProperty"
    assert employs["rdfs:domain"] == {"@id": EX + "Organization"}
    assert employs["rdfs:range"] == {"@id": EX + "Person"}
    assert employs["owl:inverseOf"] == {"@id": EX + "employedBy"}
    assert employs["rf:temporal"] is True
    assert employs["rf:provenanceRequired"] is True

    tier = nodes[EX + "riskTier"]
    assert tier["@type"] == "owl:DatatypeProperty"
    assert tier["rdfs:range"] == {"@id": XSD + "integer"}
    assert tier["rf:provenanceRequired"] is False
    assert nodes[EX + "isSystemic"]["owl:deprecated"] is True


def test_export_unions_for_multiple_domain_or_range_classes():
    """Several domain or range classes are exported as owl:unionOf."""
    nodes = _nodes(ser.export_jsonld(build_finance_release()))
    assert nodes[EX + "supervises"]["rdfs:range"] == {
        "@type": "owl:Class",
        "owl:unionOf": {
            "@list": [{"@id": EX + "Bank"}, {"@id": EX + "Person"}]
        },
    }
    assert nodes[EX + "legalName"]["rdfs:domain"] == {
        "@type": "owl:Class",
        "owl:unionOf": {
            "@list": [{"@id": EX + "Organization"}, {"@id": EX + "Person"}]
        },
    }


def test_export_constraints_as_shacl_property_shapes():
    """Constraints become sh:PropertyShape nodes targeting the property."""
    nodes = _nodes(ser.export_jsonld(build_finance_release()))
    status = nodes["shape:" + EX + "licenceStatus"]
    assert status == {
        "@type": "sh:PropertyShape",
        "sh:path": {"@id": EX + "licenceStatus"},
        "sh:targetSubjectsOf": {"@id": EX + "licenceStatus"},
        "sh:maxCount": 1,
        "sh:in": {"@list": ["active", "suspended", "revoked"]},
    }
    founded = nodes["shape:" + EX + "foundedOn"]
    assert founded["sh:minCount"] == 1 and founded["sh:maxCount"] == 1
    tier = nodes["shape:" + EX + "riskTier"]
    assert tier["sh:in"] == {
        "@list": [
            {"@value": "1", "@type": "xsd:integer"},
            {"@value": "2", "@type": "xsd:integer"},
            {"@value": "3", "@type": "xsd:integer"},
        ]
    }
    licensed = nodes["shape:" + EX + "licensedBy"]
    assert licensed["sh:in"] == {
        "@list": [{"@id": EX + "ojk"}, {"@id": EX + "bankIndonesia"}]
    }
    assert "shape:" + EX + "employs" not in nodes


def test_export_is_deterministic_and_sorted():
    """Exports are byte-identical and nodes are ordered by kind and IRI."""
    first = ser.export_jsonld(build_finance_release())
    second = ser.export_jsonld(build_finance_release())
    assert json.dumps(first) == json.dumps(second)
    types = [node["@type"] for node in first["@graph"]]
    assert types[0] == "owl:Ontology"
    class_ids = [
        n["@id"] for n in first["@graph"] if n["@type"] == "owl:Class"
    ]
    assert class_ids == sorted(class_ids)


# --- Round trip -----------------------------------------------------------


def test_round_trip_preserves_terms():
    """Importing an export reproduces every class and property."""
    original = build_finance_release()
    imported = ser.import_jsonld(ser.export_jsonld(original))
    assert imported.ontology_uri == original.ontology_uri
    assert imported.version == original.version
    assert imported.title == original.title
    assert imported.description == original.description
    assert imported.status == "draft"
    assert _terms(imported) == _terms(original)


def test_round_trip_survives_json_text():
    """The export is plain JSON that survives serialization to text."""
    original = build_finance_release()
    text = json.dumps(ser.export_jsonld(original))
    assert _terms(ser.import_jsonld(json.loads(text))) == _terms(original)


def test_imported_approved_terms_become_drafts():
    """Approval is not part of the interchange format."""
    original = build_finance_release()
    for cls in original.classes:
        if cls.status == "draft":
            cls.status = "approved"
    imported = ser.import_jsonld(ser.export_jsonld(original))
    statuses = {c.uri: c.status for c in imported.classes}
    assert statuses[EX + "Bank"] == "draft"
    assert statuses[EX + "SavingsAndLoan"] == "deprecated"


# --- Import of hand-written documents -------------------------------------


def test_import_expands_compact_iris():
    """Prefixes from @context expand in ids, keys and types."""
    doc = _minimal_document(
        cls={
            "@id": "ex:Employee",
            "@type": "owl:Class",
            "rdfs:label": {"@value": "Employee", "@language": "en"},
            "rdfs:subClassOf": {"@id": "ex:Person"},
        },
        prop={
            "@id": "ex:age",
            "@type": "owl:DatatypeProperty",
            "rdfs:label": "age",
            "rdfs:domain": {"@id": "ex:Person"},
            "rdfs:range": {"@id": "xsd:integer"},
        },
    )
    release = ser.import_jsonld(doc)
    assert release.ontology_uri == EX
    assert release.version == "2.0"
    assert release.title == "Mini"
    employee = release.get_class(EX + "Employee")
    assert employee.parent_class_uris == [EX + "Person"]
    age = release.get_property(EX + "age")
    assert age.datatype == XSD + "integer"
    assert age.temporal is False
    assert age.provenance_required is True


def test_import_accepts_full_iris_without_context():
    """Keys and types may be written as full IRIs."""
    doc = {
        "@graph": [
            {
                "@id": ONTO,
                "@type": OWL + "Ontology",
                OWL + "versionInfo": "1",
                RDFS + "label": "Full",
            },
            {
                "@id": EX + "Thing2",
                "@type": [OWL + "Class"],
                RDFS + "label": [{"@value": "Thing", "@language": "en"}],
            },
        ]
    }
    release = ser.import_jsonld(doc)
    assert release.get_class(EX + "Thing2") is not None


def test_untagged_labels_use_undetermined_language():
    """A label without a language tag is stored under 'und'."""
    release = ser.import_jsonld(_minimal_document())
    assert release.get_class(EX + "Person").preferred_labels == {
        "und": "Person"
    }


def test_owl_thing_parent_is_dropped():
    """rdfs:subClassOf owl:Thing is implied and not stored."""
    doc = _minimal_document()
    doc["@graph"][1]["rdfs:subClassOf"] = {"@id": "owl:Thing"}
    release = ser.import_jsonld(doc)
    assert release.get_class(EX + "Person").parent_class_uris == []


def test_import_reads_typed_and_boolean_values():
    """Booleans and counts may be native JSON or typed value objects."""
    doc = _minimal_document(
        prop={
            "@id": "ex:nickname",
            "@type": "owl:DatatypeProperty",
            "rdfs:label": "nickname",
            "rdfs:range": {"@id": "xsd:string"},
            "owl:deprecated": {"@value": "true", "@type": "xsd:boolean"},
            "rf:temporal": True,
        },
        shape={
            "@id": "_:b0",
            "@type": "sh:PropertyShape",
            "sh:path": {"@id": "ex:nickname"},
            "sh:maxCount": {"@value": "2", "@type": "xsd:integer"},
            "sh:in": {"@list": ["Al", {"@value": "Bo"}]},
        },
    )
    doc["@context"]["rf"] = ser.RF_NAMESPACE
    prop = ser.import_jsonld(doc).get_property(EX + "nickname")
    assert prop.status == "deprecated"
    assert prop.temporal is True
    assert prop.constraint("cardinality").max_count == 2
    assert prop.constraint("allowed_values").allowed_values == ["Al", "Bo"]


def test_import_boolean_allowed_values_use_lexical_form():
    """Native JSON booleans in sh:in become 'true' and 'false'."""
    doc = _minimal_document(
        prop={
            "@id": "ex:active",
            "@type": "owl:DatatypeProperty",
            "rdfs:label": "active",
            "rdfs:range": {"@id": "xsd:boolean"},
        },
        shape={
            "@type": "sh:PropertyShape",
            "sh:path": {"@id": "ex:active"},
            "sh:in": {"@list": [True, False]},
        },
    )
    prop = ser.import_jsonld(doc).get_property(EX + "active")
    assert prop.constraint("allowed_values").allowed_values == [
        "true",
        "false",
    ]


def test_import_object_allowed_values_are_iris():
    """sh:in members given as IRI references import as IRIs."""
    doc = _minimal_document(
        prop={
            "@id": "ex:knows",
            "@type": "owl:ObjectProperty",
            "rdfs:label": "knows",
            "rdfs:range": {"@id": "ex:Person"},
        },
        shape={
            "@type": "sh:PropertyShape",
            "sh:path": {"@id": "ex:knows"},
            "sh:targetSubjectsOf": {"@id": "ex:knows"},
            "sh:in": {"@list": [{"@id": "ex:alice"}]},
        },
    )
    prop = ser.import_jsonld(doc).get_property(EX + "knows")
    assert prop.constraint("allowed_values").allowed_values == [EX + "alice"]


# --- Unsupported features fail explicitly ----------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda d: d["@graph"][1].update(
                {"rdfs:subClassOf": {
                    "@type": "owl:Restriction",
                    "owl:onProperty": {"@id": "ex:knows"},
                }}
            ),
            id="owl-restriction",
        ),
        pytest.param(
            lambda d: d["@graph"][1].update(
                {"owl:equivalentClass": {"@id": "ex:Human"}}
            ),
            id="equivalent-class",
        ),
        pytest.param(
            lambda d: d["@graph"][0].update(
                {"owl:imports": {"@id": "http://example.org/other"}}
            ),
            id="owl-imports",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {"@id": "ex:x", "@type": "owl:NamedIndividual"}
            ),
            id="individual",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {
                    "@id": "ex:knows",
                    "@type": ["owl:ObjectProperty", "owl:FunctionalProperty"],
                    "rdfs:label": "knows",
                }
            ),
            id="functional-property",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {
                    "@id": "ex:knows",
                    "@type": "owl:ObjectProperty",
                    "rdfs:label": "knows",
                    "rdfs:domain": [{"@id": "ex:Person"}, {"@id": "ex:A"}],
                }
            ),
            id="domain-intersection",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {
                    "@id": "ex:born",
                    "@type": "owl:DatatypeProperty",
                    "rdfs:label": "born",
                    "rdfs:range": {"@id": "xsd:gYear"},
                }
            ),
            id="unsupported-datatype",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {
                    "@id": "ex:born",
                    "@type": "owl:DatatypeProperty",
                    "rdfs:label": "born",
                }
            ),
            id="datatype-property-without-range",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {
                    "@id": "ex:born",
                    "@type": "owl:DatatypeProperty",
                    "rdfs:label": "born",
                    "rdfs:range": [
                        {"@id": "xsd:date"}, {"@id": "xsd:string"}
                    ],
                }
            ),
            id="datatype-range-intersection",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {"@type": "sh:NodeShape", "sh:targetClass": {"@id": "ex:P"}}
            ),
            id="node-shape",
        ),
        pytest.param(
            lambda d: d["@context"].update({"@vocab": EX}),
            id="context-vocab",
        ),
        pytest.param(
            lambda d: d["@context"].update(
                {"name": {"@id": "rdfs:label", "@container": "@language"}}
            ),
            id="context-term-definition",
        ),
        pytest.param(
            lambda d: d.update({"@context": "https://schema.org/"}),
            id="remote-context",
        ),
        pytest.param(
            lambda d: d.update({"@id": "ex:graph"}),
            id="named-graph",
        ),
        pytest.param(
            lambda d: d["@graph"][1].update(
                {"@reverse": {"rdfs:subClassOf": {"@id": "ex:Child"}}}
            ),
            id="reverse-keyword",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {"@id": "_:c1", "@type": "owl:Class", "rdfs:label": "Anon"}
            ),
            id="anonymous-class",
        ),
        pytest.param(
            lambda d: d["@graph"][1].update(
                {"rdfs:subClassOf": {"@id": "ex:Agent", "rdfs:label": "A"}}
            ),
            id="embedded-node",
        ),
        pytest.param(
            lambda d: d["@graph"][1].update(
                {"rdfs:label": {"@value": "P", "@direction": "ltr"}}
            ),
            id="value-direction",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {
                    "@id": "ex:knows",
                    "@type": "owl:ObjectProperty",
                    "rdfs:label": "knows",
                    "rdfs:domain": {
                        "@type": "owl:Restriction",
                        "owl:onProperty": {"@id": "ex:knows"},
                    },
                }
            ),
            id="domain-restriction",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {
                    "@id": "ex:knows",
                    "@type": "owl:ObjectProperty",
                    "rdfs:label": "knows",
                    "rdfs:range": {
                        "@type": "owl:Class",
                        "owl:intersectionOf": {"@list": [
                            {"@id": "ex:Person"}
                        ]},
                    },
                }
            ),
            id="range-intersection-of",
        ),
    ],
)
def test_unsupported_features_fail_explicitly(mutate):
    """OWL, SHACL and JSON-LD features outside the subset are refused."""
    doc = _minimal_document()
    mutate(doc)
    with pytest.raises(UnsupportedFeatureError):
        ser.import_jsonld(doc)


def test_unsupported_shacl_constraint_raises_constraint_error():
    """SHACL constraint components outside the subset name themselves."""
    doc = _minimal_document(
        prop={
            "@id": "ex:code",
            "@type": "owl:DatatypeProperty",
            "rdfs:label": "code",
            "rdfs:range": {"@id": "xsd:string"},
        },
        shape={
            "@type": "sh:PropertyShape",
            "sh:path": {"@id": "ex:code"},
            "sh:pattern": "^[A-Z]{3}$",
        },
    )
    with pytest.raises(UnsupportedConstraintError) as exc_info:
        ser.import_jsonld(doc)
    assert exc_info.value.kind == SH + "pattern"


def test_shape_targeting_another_property_is_unsupported():
    """Shapes must target the subjects of the property they constrain."""
    doc = _minimal_document(
        prop={
            "@id": "ex:code",
            "@type": "owl:DatatypeProperty",
            "rdfs:label": "code",
            "rdfs:range": {"@id": "xsd:string"},
        },
        shape={
            "@type": "sh:PropertyShape",
            "sh:path": {"@id": "ex:code"},
            "sh:targetSubjectsOf": {"@id": "ex:other"},
            "sh:maxCount": 1,
        },
    )
    with pytest.raises(UnsupportedFeatureError):
        ser.import_jsonld(doc)


def test_unsupported_constraint_error_is_an_unsupported_feature():
    """One except clause catches every unsupported feature."""
    assert issubclass(UnsupportedConstraintError, UnsupportedFeatureError)


# --- Malformed documents ---------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda d: d.pop("@graph"), id="no-graph"),
        pytest.param(lambda d: d["@graph"].pop(0), id="no-ontology-node"),
        pytest.param(
            lambda d: d["@graph"].append(copy.deepcopy(d["@graph"][0])),
            id="two-ontology-nodes",
        ),
        pytest.param(
            lambda d: d["@graph"][0].pop("owl:versionInfo"),
            id="no-version",
        ),
        pytest.param(
            lambda d: d["@graph"][0].pop("rdfs:label"), id="no-title"
        ),
        pytest.param(
            lambda d: d["@graph"][1].update(
                {"rdfs:subClassOf": "ex:Agent"}
            ),
            id="parent-as-literal",
        ),
        pytest.param(
            lambda d: d["@graph"][1].update(
                {"rdfs:subClassOf": {"@id": "ex:Agent"}}
            ),
            id="undefined-parent",
        ),
        pytest.param(
            lambda d: d["@graph"][1].update(
                {"rdfs:label": [
                    {"@value": "A", "@language": "en"},
                    {"@value": "B", "@language": "en"},
                ]}
            ),
            id="two-labels-one-language",
        ),
        pytest.param(
            lambda d: d["@graph"][1].update({"@id": "Person"}),
            id="relative-iri",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {
                    "@type": "sh:PropertyShape",
                    "sh:path": {"@id": "ex:missing"},
                    "sh:maxCount": 1,
                }
            ),
            id="shape-for-unknown-property",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {
                    "@type": "sh:PropertyShape",
                    "sh:path": {"@id": "ex:Person"},
                    "sh:maxCount": True,
                }
            ),
            id="boolean-count",
        ),
        pytest.param(lambda d: d["@graph"].append("ex:x"), id="non-object"),
        pytest.param(lambda d: d.update({"@context": 5}), id="bad-context"),
        pytest.param(
            lambda d: d["@graph"][1].update({"@id": 5}), id="numeric-id"
        ),
        pytest.param(
            lambda d: d["@graph"][1].pop("@type"), id="untyped-node"
        ),
        pytest.param(
            lambda d: d["@graph"][0].pop("@id"), id="anonymous-ontology"
        ),
        pytest.param(
            lambda d: d["@graph"][1].update(
                {"rdfs:label": {"@id": "ex:label"}}
            ),
            id="label-as-iri",
        ),
        pytest.param(
            lambda d: d["@graph"][0].update({"owl:versionInfo": None}),
            id="null-literal",
        ),
        pytest.param(
            lambda d: d["@graph"][1].update({"rdfs:label": {"@value": 5}}),
            id="numeric-label",
        ),
        pytest.param(
            lambda d: d["@graph"][1].update({"owl:deprecated": "yes"}),
            id="non-boolean",
        ),
        pytest.param(
            lambda d: d["@graph"].append(
                {
                    "@id": "ex:knows",
                    "@type": "owl:ObjectProperty",
                    "rdfs:label": "knows",
                    "rdfs:range": {
                        "@type": "owl:Class",
                        "owl:unionOf": {"@id": "ex:Person"},
                    },
                }
            ),
            id="union-without-list",
        ),
        pytest.param(
            lambda d: d["@graph"].extend([
                {
                    "@id": "ex:nick",
                    "@type": "owl:DatatypeProperty",
                    "rdfs:label": "nick",
                    "rdfs:range": {"@id": "xsd:string"},
                },
                {
                    "@type": "sh:PropertyShape",
                    "sh:path": {"@id": "ex:nick"},
                    "sh:in": "Al",
                },
            ]),
            id="sh-in-without-list",
        ),
    ],
)
def test_malformed_documents_are_rejected(mutate):
    """Structural errors raise OntologyImportError."""
    doc = _minimal_document()
    mutate(doc)
    with pytest.raises(ser.OntologyImportError):
        ser.import_jsonld(doc)


def test_import_rejects_non_object_document():
    """The document must be a JSON object."""
    with pytest.raises(ser.OntologyImportError):
        ser.import_jsonld([])


def test_import_rejects_two_shapes_for_one_property():
    """A property may be described by a single shape."""
    shape = {
        "@type": "sh:PropertyShape",
        "sh:path": {"@id": "ex:nick"},
        "sh:maxCount": 1,
    }
    doc = _minimal_document(
        prop={
            "@id": "ex:nick",
            "@type": "owl:DatatypeProperty",
            "rdfs:label": "nick",
            "rdfs:range": {"@id": "xsd:string"},
        },
        a=shape,
        b=dict(shape),
    )
    with pytest.raises(ser.OntologyImportError):
        ser.import_jsonld(doc)


# --- Persisting imports ----------------------------------------------------


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """Yield a session factory bound to a fresh SQLite schema."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'j.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_registry_import_draft_persists_release(session_factory):
    """An imported release is stored as a draft and can be published."""
    imported = ser.import_jsonld(ser.export_jsonld(build_finance_release()))
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        stored = await registry.import_draft(imported)
        await session.commit()

    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        loaded = await registry.get_release(stored.release_id)
        published = await registry.publish(stored.release_id)
    assert loaded.status == "draft"
    assert _terms(loaded) == _terms(imported)
    assert published.get_class(EX + "Bank").status == "approved"
    assert published.get_class(EX + "SavingsAndLoan").status == "deprecated"


@pytest.mark.asyncio
async def test_registry_import_draft_rules(session_factory):
    """Imports must be drafts without approved terms or reused versions."""
    imported = ser.import_jsonld(ser.export_jsonld(build_finance_release()))
    async with session_factory() as session:
        registry = reg.OntologyRegistry(session)
        await registry.import_draft(imported)
        with pytest.raises(reg.DuplicateReleaseError):
            await registry.import_draft(
                imported.model_copy(update={"release_id": uuid.uuid4()})
            )
        with pytest.raises(reg.InvalidReleaseError):
            await registry.import_draft(
                imported.model_copy(update={"status": "approved"})
            )
        approved = imported.model_copy(deep=True)
        approved.version = "9.9.9"
        approved.classes[0].status = "approved"
        with pytest.raises(reg.InvalidReleaseError):
            await registry.import_draft(approved)
