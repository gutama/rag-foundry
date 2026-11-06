"""Unit tests for ontology domain models (ADR-0011, ARCHITECTURE.md §8.5)."""

import pytest
from pydantic import ValidationError

from rag_foundry.ontology import models

EX = "http://example.org/onto#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def _cls(name, parents=None, **kwargs):
    """Build an OntologyClass in the example namespace."""
    return models.OntologyClass(
        uri=EX + name,
        preferred_labels={"en": name},
        parent_class_uris=[EX + p for p in (parents or [])],
        **kwargs,
    )


def _object_prop(name, domain, range_, **kwargs):
    """Build an object OntologyProperty in the example namespace."""
    return models.OntologyProperty(
        uri=EX + name,
        preferred_labels={"en": name},
        property_type="object",
        domain_class_uris=[EX + d for d in domain],
        range_class_uris=[EX + r for r in range_],
        **kwargs,
    )


def _data_prop(name, domain, datatype, **kwargs):
    """Build a data OntologyProperty in the example namespace."""
    return models.OntologyProperty(
        uri=EX + name,
        preferred_labels={"en": name},
        property_type="data",
        domain_class_uris=[EX + d for d in domain],
        datatype=datatype,
        **kwargs,
    )


def _release(classes=None, properties=None, **kwargs):
    """Build an OntologyRelease with sensible defaults."""
    fields = {
        "ontology_uri": "http://example.org/onto",
        "version": "1.0.0",
        "title": "Example Ontology",
    }
    fields.update(kwargs)
    return models.OntologyRelease(
        classes=classes or [], properties=properties or [], **fields
    )


# --- IRIs -----------------------------------------------------------------


@pytest.mark.parametrize(
    "iri",
    [
        "http://example.org/onto#Organization",
        "https://id.example.org/class/Bank",
        "urn:example:onto:Person",
    ],
)
def test_class_accepts_absolute_iris(iri):
    """Absolute IRIs with a scheme are accepted for class URIs."""
    cls = models.OntologyClass(uri=iri, preferred_labels={"en": "X"})
    assert cls.uri == iri


@pytest.mark.parametrize(
    "iri",
    ["", "Organization", "onto#Organization", "http://ex.org/has space",
     "http://ex.org/<bad>"],
)
def test_class_rejects_invalid_iris(iri):
    """Relative, empty or whitespace-containing IRIs are rejected."""
    with pytest.raises(ValidationError):
        models.OntologyClass(uri=iri, preferred_labels={"en": "X"})


def test_parent_class_uris_must_be_valid_iris():
    """Parent class references are validated as IRIs too."""
    with pytest.raises(ValidationError):
        models.OntologyClass(
            uri=EX + "Bank",
            preferred_labels={"en": "Bank"},
            parent_class_uris=["not an iri"],
        )


# --- OntologyClass --------------------------------------------------------


def test_class_defaults():
    """A new class is a draft with no parents, rules or description."""
    cls = _cls("Organization")
    assert cls.status == "draft"
    assert cls.parent_class_uris == []
    assert cls.identity_rules == []
    assert cls.description == {}


def test_class_requires_a_preferred_label():
    """At least one preferred label is required."""
    with pytest.raises(ValidationError):
        models.OntologyClass(uri=EX + "Bank", preferred_labels={})


def test_class_rejects_blank_labels():
    """Labels cannot be blank strings."""
    with pytest.raises(ValidationError):
        models.OntologyClass(uri=EX + "Bank", preferred_labels={"en": "  "})


def test_class_rejects_unknown_status():
    """Only draft, approved and deprecated statuses are allowed."""
    with pytest.raises(ValidationError):
        _cls("Bank", status="published")


def test_class_cannot_be_its_own_parent():
    """A class listing itself as a parent is rejected."""
    with pytest.raises(ValidationError):
        _cls("Bank", parents=["Bank"])


def test_class_rejects_duplicate_parents():
    """Duplicate parent references are rejected."""
    with pytest.raises(ValidationError):
        _cls("Bank", parents=["Organization", "Organization"])


# --- PropertyConstraint ---------------------------------------------------


def test_cardinality_constraint():
    """A cardinality constraint stores min and max counts."""
    constraint = models.PropertyConstraint(
        kind="cardinality", min_count=1, max_count=1
    )
    assert constraint.min_count == 1
    assert constraint.max_count == 1


def test_cardinality_requires_a_bound():
    """A cardinality constraint needs at least one bound."""
    with pytest.raises(ValidationError):
        models.PropertyConstraint(kind="cardinality")


def test_cardinality_rejects_negative_or_inverted_bounds():
    """Bounds must be non-negative and min must not exceed max."""
    with pytest.raises(ValidationError):
        models.PropertyConstraint(kind="cardinality", min_count=-1)
    with pytest.raises(ValidationError):
        models.PropertyConstraint(
            kind="cardinality", min_count=2, max_count=1
        )


def test_cardinality_rejects_allowed_values():
    """A cardinality constraint cannot carry allowed values."""
    with pytest.raises(ValidationError):
        models.PropertyConstraint(
            kind="cardinality", max_count=1, allowed_values=["a"]
        )


def test_allowed_values_constraint():
    """An allowed-values constraint stores a non-empty unique list."""
    constraint = models.PropertyConstraint(
        kind="allowed_values", allowed_values=["active", "dissolved"]
    )
    assert constraint.allowed_values == ["active", "dissolved"]


def test_allowed_values_must_be_non_empty_and_unique():
    """Empty or duplicate allowed values are rejected."""
    with pytest.raises(ValidationError):
        models.PropertyConstraint(kind="allowed_values", allowed_values=[])
    with pytest.raises(ValidationError):
        models.PropertyConstraint(
            kind="allowed_values", allowed_values=["a", "a"]
        )


def test_allowed_values_rejects_counts():
    """An allowed-values constraint cannot carry cardinality bounds."""
    with pytest.raises(ValidationError):
        models.PropertyConstraint(
            kind="allowed_values", allowed_values=["a"], min_count=1
        )


@pytest.mark.parametrize(
    "kind", ["pattern", "sh:pattern", "owl:FunctionalProperty", ""]
)
def test_unsupported_constraint_kind_fails_explicitly(kind):
    """Constraint kinds outside the subset raise UnsupportedConstraintError."""
    with pytest.raises(models.UnsupportedConstraintError) as exc_info:
        models.PropertyConstraint(kind=kind, min_count=1)
    assert exc_info.value.kind == kind


def test_unsupported_constraint_nested_in_property_fails_explicitly():
    """The explicit error survives nesting inside a property."""
    with pytest.raises(models.UnsupportedConstraintError):
        _data_prop(
            "code", ["Organization"], XSD + "string",
            constraints=[{"kind": "pattern", "allowed_values": ["^[A-Z]"]}],
        )


def test_supported_constraint_kinds_are_published():
    """The supported subset is exposed as a module constant."""
    assert models.SUPPORTED_CONSTRAINT_KINDS == (
        "cardinality",
        "allowed_values",
    )


# --- OntologyProperty -----------------------------------------------------


def test_object_property():
    """An object property links domain classes to range classes."""
    prop = _object_prop(
        "employs",
        ["Organization"],
        ["Person"],
        inverse_property_uri=EX + "employedBy",
    )
    assert prop.property_type == "object"
    assert prop.range_class_uris == [EX + "Person"]
    assert prop.datatype is None
    assert prop.inverse_property_uri == EX + "employedBy"
    assert prop.provenance_required is True
    assert prop.temporal is False
    assert prop.status == "draft"


def test_object_property_cannot_have_datatype():
    """Object properties take range classes, not a datatype."""
    with pytest.raises(ValidationError):
        _object_prop(
            "employs", ["Organization"], ["Person"], datatype=XSD + "string"
        )


def test_object_property_range_cannot_be_a_datatype():
    """An XSD datatype is not a valid range class."""
    with pytest.raises(ValidationError):
        models.OntologyProperty(
            uri=EX + "employs",
            preferred_labels={"en": "employs"},
            property_type="object",
            range_class_uris=[XSD + "string"],
        )


def test_object_property_cannot_be_its_own_inverse():
    """A property naming itself as its inverse is rejected."""
    with pytest.raises(ValidationError):
        _object_prop(
            "knows", ["Person"], ["Person"],
            inverse_property_uri=EX + "knows",
        )


@pytest.mark.parametrize(
    "datatype", sorted(models.SUPPORTED_DATATYPES)
)
def test_data_property_accepts_supported_datatypes(datatype):
    """Each supported XSD datatype is accepted for data properties."""
    prop = _data_prop("value", ["Organization"], datatype)
    assert prop.datatype == datatype


def test_supported_datatypes():
    """The supported datatype subset matches the specification."""
    assert models.SUPPORTED_DATATYPES == frozenset(
        XSD + name
        for name in (
            "string", "integer", "decimal", "boolean", "date", "dateTime"
        )
    )


def test_data_property_requires_a_datatype():
    """A data property must declare its datatype range."""
    with pytest.raises(ValidationError):
        models.OntologyProperty(
            uri=EX + "foundedOn",
            preferred_labels={"en": "founded on"},
            property_type="data",
        )


def test_data_property_rejects_unsupported_datatype():
    """Datatypes outside the supported subset are rejected."""
    with pytest.raises(ValidationError):
        _data_prop("foundedOn", ["Organization"], XSD + "gYear")


def test_data_property_cannot_have_range_classes_or_inverse():
    """Data properties have no range classes and no inverse."""
    with pytest.raises(ValidationError):
        models.OntologyProperty(
            uri=EX + "name",
            preferred_labels={"en": "name"},
            property_type="data",
            datatype=XSD + "string",
            range_class_uris=[EX + "Person"],
        )
    with pytest.raises(ValidationError):
        _data_prop(
            "name", ["Person"], XSD + "string",
            inverse_property_uri=EX + "nameOf",
        )


def test_property_rejects_unknown_type():
    """Property type must be object or data."""
    with pytest.raises(ValidationError):
        models.OntologyProperty(
            uri=EX + "x",
            preferred_labels={"en": "x"},
            property_type="annotation",
        )


def test_property_rejects_duplicate_constraint_kinds():
    """A property carries at most one constraint of each kind."""
    with pytest.raises(ValidationError):
        _data_prop(
            "status", ["Organization"], XSD + "string",
            constraints=[
                models.PropertyConstraint(kind="cardinality", max_count=1),
                models.PropertyConstraint(kind="cardinality", min_count=1),
            ],
        )


def test_property_constraints_from_dicts():
    """Constraints can be supplied as plain mappings."""
    prop = _data_prop(
        "status", ["Organization"], XSD + "string",
        constraints=[
            {"kind": "cardinality", "max_count": 1},
            {"kind": "allowed_values", "allowed_values": ["active"]},
        ],
    )
    assert [c.kind for c in prop.constraints] == [
        "cardinality",
        "allowed_values",
    ]


def test_property_constraint_lookup():
    """constraint() returns the constraint of a kind, or None."""
    prop = _data_prop(
        "status", ["Organization"], XSD + "string",
        constraints=[{"kind": "cardinality", "max_count": 1}],
    )
    assert prop.constraint("cardinality").max_count == 1
    assert prop.constraint("allowed_values") is None


# --- OntologyRelease ------------------------------------------------------


def _sample_release(**kwargs):
    """Build a small, internally consistent release."""
    return _release(
        classes=[
            _cls("Agent"),
            _cls("Organization", ["Agent"]),
            _cls("Bank", ["Organization"]),
            _cls("Person", ["Agent"]),
        ],
        properties=[
            _object_prop(
                "employs", ["Organization"], ["Person"],
                inverse_property_uri=EX + "employedBy",
            ),
            _object_prop("employedBy", ["Person"], ["Organization"]),
            _data_prop("foundedOn", ["Organization"], XSD + "date"),
        ],
        **kwargs,
    )


def test_release_defaults():
    """A new release is a draft with an id and creation timestamp."""
    release = _sample_release()
    assert release.status == "draft"
    assert release.release_id is not None
    assert release.created_at.tzinfo is not None


def test_release_requires_a_version():
    """The release version cannot be blank."""
    with pytest.raises(ValidationError):
        _release(version=" ")


def test_release_rejects_duplicate_class_iris():
    """Two classes cannot share an IRI."""
    with pytest.raises(ValidationError):
        _release(classes=[_cls("Bank"), _cls("Bank")])


def test_release_rejects_duplicate_property_iris():
    """Two properties cannot share an IRI."""
    with pytest.raises(ValidationError):
        _release(
            classes=[_cls("Person")],
            properties=[
                _data_prop("name", ["Person"], XSD + "string"),
                _data_prop("name", ["Person"], XSD + "string"),
            ],
        )


def test_release_rejects_iri_shared_by_class_and_property():
    """An IRI cannot denote both a class and a property."""
    with pytest.raises(ValidationError):
        _release(
            classes=[_cls("Person"), _cls("name")],
            properties=[_data_prop("name", ["Person"], XSD + "string")],
        )


def test_release_rejects_unknown_parent_class():
    """Parent classes must be defined in the same release."""
    with pytest.raises(ValidationError):
        _release(classes=[_cls("Bank", ["Organization"])])


def test_release_rejects_unknown_domain_or_range_class():
    """Domain and range classes must be defined in the same release."""
    with pytest.raises(ValidationError):
        _release(
            classes=[_cls("Organization")],
            properties=[
                _object_prop("employs", ["Organization"], ["Person"])
            ],
        )
    with pytest.raises(ValidationError):
        _release(
            classes=[_cls("Person")],
            properties=[
                _object_prop("employs", ["Organization"], ["Person"])
            ],
        )


def test_release_rejects_unknown_or_data_inverse():
    """An inverse must be an object property in the same release."""
    with pytest.raises(ValidationError):
        _release(
            classes=[_cls("Person")],
            properties=[
                _object_prop(
                    "knows", ["Person"], ["Person"],
                    inverse_property_uri=EX + "knownBy",
                )
            ],
        )
    with pytest.raises(ValidationError):
        _release(
            classes=[_cls("Person")],
            properties=[
                _object_prop(
                    "knows", ["Person"], ["Person"],
                    inverse_property_uri=EX + "name",
                ),
                _data_prop("name", ["Person"], XSD + "string"),
            ],
        )


def test_release_rejects_subclass_cycles():
    """Cycles in rdfs:subClassOf are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        _release(
            classes=[
                _cls("A", ["C"]),
                _cls("B", ["A"]),
                _cls("C", ["B"]),
            ]
        )
    assert "cycle" in str(exc_info.value).lower()


def test_release_term_lookup():
    """get_class and get_property find terms by IRI."""
    release = _sample_release()
    assert release.get_class(EX + "Bank").uri == EX + "Bank"
    assert release.get_class(EX + "Missing") is None
    assert release.get_property(EX + "employs").property_type == "object"
    assert release.get_property(EX + "Bank") is None


def test_release_ancestors_are_transitive():
    """ancestors() returns every superclass, nearest first."""
    release = _sample_release()
    assert release.ancestors(EX + "Bank") == [
        EX + "Organization",
        EX + "Agent",
    ]
    assert release.ancestors(EX + "Agent") == []


def test_release_ancestors_with_multiple_parents():
    """Diamond inheritance lists each ancestor once."""
    release = _release(
        classes=[
            _cls("Thing"),
            _cls("Agent", ["Thing"]),
            _cls("LegalEntity", ["Thing"]),
            _cls("Company", ["Agent", "LegalEntity"]),
        ]
    )
    assert release.ancestors(EX + "Company") == [
        EX + "Agent",
        EX + "LegalEntity",
        EX + "Thing",
    ]


def test_release_is_subclass_of():
    """is_subclass_of is reflexive and transitive."""
    release = _sample_release()
    assert release.is_subclass_of(EX + "Bank", EX + "Bank")
    assert release.is_subclass_of(EX + "Bank", EX + "Agent")
    assert not release.is_subclass_of(EX + "Agent", EX + "Bank")
    assert not release.is_subclass_of(EX + "Person", EX + "Organization")


def test_release_ancestors_of_unknown_class_raises():
    """Asking for ancestors of an undefined class raises KeyError."""
    with pytest.raises(KeyError):
        _sample_release().ancestors(EX + "Missing")
