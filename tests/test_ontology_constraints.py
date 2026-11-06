"""Tests for the ontology constraint validator (ADR-0011, ADR-0014)."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from rag_foundry.ontology import constraints as con
from rag_foundry.ontology.models import (
    OntologyClass,
    OntologyProperty,
    OntologyRelease,
    PropertyConstraint,
    UnsupportedConstraintError,
)
from tests.ontology_samples import EX, XSD, build_finance_release


@pytest.fixture
def validator():
    """A validator over the finance sample release."""
    return con.ConstraintValidator(build_finance_release())


def _stmt(subject_class, prop, *, subject="s1", **kwargs):
    """Build a statement in the finance namespace."""
    return con.Statement(
        subject=subject,
        subject_class_uri=EX + subject_class,
        property_uri=EX + prop,
        **kwargs,
    )


def _rules(violations):
    """List the rule names of violations."""
    return [v.rule for v in violations]


# --- Domain and range -----------------------------------------------------


def test_valid_object_statement(validator):
    """A subclass of the domain and of the range is accepted."""
    stmt = _stmt("Bank", "employs", object_class_uri=EX + "Person")
    assert validator.check_statement(stmt) == []


def test_domain_violation(validator):
    """A subject outside the domain is rejected."""
    violations = validator.check_statement(
        _stmt("Person", "employs", object_class_uri=EX + "Person")
    )
    assert _rules(violations) == ["domain"]
    assert violations[0].subject == "s1"
    assert violations[0].property_uri == EX + "employs"


def test_range_violation(validator):
    """An object outside the range is rejected."""
    violations = validator.check_statement(
        _stmt("Bank", "employs", object_class_uri=EX + "Bank")
    )
    assert _rules(violations) == ["range"]


def test_range_accepts_subclasses(validator):
    """Range checks use subclass inference."""
    stmt = _stmt("Person", "employedBy", object_class_uri=EX + "Bank")
    assert validator.check_statement(stmt) == []


@pytest.mark.parametrize(
    "subject_class, ok",
    [("Person", True), ("Bank", True), ("Organization", True),
     ("Agent", False)],
)
def test_union_domain(validator, subject_class, ok):
    """Several domain classes mean 'any of', with subclass inference."""
    violations = validator.check_statement(
        _stmt(subject_class, "legalName", literal="Bank Nusantara")
    )
    assert _rules(violations) == ([] if ok else ["domain"])


@pytest.mark.parametrize(
    "object_class, ok",
    [("Bank", True), ("Person", True), ("Regulator", False)],
)
def test_union_range(validator, object_class, ok):
    """Several range classes mean 'any of'."""
    violations = validator.check_statement(
        _stmt("Regulator", "supervises", object_class_uri=EX + object_class)
    )
    assert _rules(violations) == ([] if ok else ["range"])


def test_property_without_domain_accepts_any_subject():
    """An empty domain places no restriction on the subject."""
    release = OntologyRelease(
        ontology_uri="http://example.org/o",
        version="1",
        title="T",
        classes=[OntologyClass(uri=EX + "A", preferred_labels={"en": "A"})],
        properties=[
            OntologyProperty(
                uri=EX + "note",
                preferred_labels={"en": "note"},
                property_type="data",
                datatype=XSD + "string",
            )
        ],
    )
    stmt = _stmt("A", "note", literal="x")
    assert con.ConstraintValidator(release).check_statement(stmt) == []


# --- Unknown and deprecated terms -----------------------------------------


def test_unknown_property(validator):
    """A property outside the release is reported and nothing else."""
    violations = validator.check_statement(
        _stmt("Bank", "owns", object_class_uri=EX + "Bank")
    )
    assert _rules(violations) == ["unknown_property"]


def test_unknown_subject_and_object_classes(validator):
    """Classes outside the release are reported."""
    violations = validator.check_statement(
        _stmt("Fintech", "employs", object_class_uri=EX + "Robot")
    )
    assert _rules(violations) == ["unknown_class", "unknown_class"]


def test_deprecated_property(validator):
    """Statements may not use deprecated properties."""
    violations = validator.check_statement(
        _stmt("Bank", "isSystemic", literal=True)
    )
    assert _rules(violations) == ["deprecated_term"]


def test_deprecated_classes(validator):
    """Subjects and objects of deprecated classes are reported."""
    subject_side = validator.check_statement(
        _stmt("SavingsAndLoan", "riskTier", literal=2)
    )
    object_side = validator.check_statement(
        _stmt("Regulator", "supervises",
              object_class_uri=EX + "SavingsAndLoan")
    )
    assert _rules(subject_side) == ["deprecated_term"]
    assert _rules(object_side) == ["deprecated_term"]


# --- Value kinds ----------------------------------------------------------


def test_object_property_needs_an_object(validator):
    """Object properties take entities, not literals."""
    with_literal = validator.check_statement(
        _stmt("Bank", "employs", literal="Alice")
    )
    missing = validator.check_statement(_stmt("Bank", "employs"))
    assert _rules(with_literal) == ["value_kind"]
    assert _rules(missing) == ["value_kind"]


def test_data_property_needs_a_literal(validator):
    """Data properties take literals, not entities."""
    with_object = validator.check_statement(
        _stmt("Bank", "legalName", object_class_uri=EX + "Person")
    )
    missing = validator.check_statement(_stmt("Bank", "legalName"))
    assert _rules(with_object) == ["value_kind"]
    assert _rules(missing) == ["value_kind"]


# --- Datatypes ------------------------------------------------------------


def _typed_validator():
    """A validator with one data property per supported datatype."""
    names = ["string", "integer", "decimal", "boolean", "date", "dateTime"]
    return con.ConstraintValidator(
        OntologyRelease(
            ontology_uri="http://example.org/o",
            version="1",
            title="T",
            classes=[
                OntologyClass(uri=EX + "A", preferred_labels={"en": "A"})
            ],
            properties=[
                OntologyProperty(
                    uri=EX + name,
                    preferred_labels={"en": name},
                    property_type="data",
                    datatype=XSD + name,
                )
                for name in names
            ],
        )
    )


@pytest.mark.parametrize(
    "datatype, value",
    [
        ("string", "anything at all"),
        ("string", ""),
        ("integer", "12"),
        ("integer", "+3"),
        ("integer", "-0"),
        ("integer", 7),
        ("decimal", "1.5"),
        ("decimal", "-.5"),
        ("decimal", "10"),
        ("decimal", "1."),
        ("decimal", Decimal("1.50")),
        ("decimal", 3),
        ("boolean", "true"),
        ("boolean", "0"),
        ("boolean", False),
        ("date", "2026-11-06"),
        ("date", "2026-11-06Z"),
        ("date", "2026-11-06+07:00"),
        ("date", date(2026, 2, 28)),
        ("dateTime", "2026-11-06T10:15:30"),
        ("dateTime", "2026-11-06T10:15:30.5Z"),
        ("dateTime", "2026-11-06T10:15:30-03:30"),
        ("dateTime", datetime(2026, 11, 6, 10, 15, tzinfo=timezone.utc)),
    ],
)
def test_valid_literals(datatype, value):
    """Lexical forms and Python values of each datatype are accepted."""
    stmt = _stmt("A", datatype, literal=value)
    assert _typed_validator().check_statement(stmt) == []


@pytest.mark.parametrize(
    "datatype, value",
    [
        ("integer", "1.5"),
        ("integer", "abc"),
        ("integer", ""),
        ("integer", True),
        ("decimal", "1e5"),
        ("decimal", "abc"),
        ("decimal", float("nan")),
        ("boolean", "True"),
        ("boolean", "yes"),
        ("date", "2026-02-30"),
        ("date", "06-11-2026"),
        ("date", "2026-11-06T00:00:00"),
        ("date", "2026-11-06+15:00"),
        ("date", datetime(2026, 11, 6)),
        ("dateTime", "2026-11-06"),
        ("dateTime", "2026-11-06T25:00:00"),
        ("dateTime", "2026-11-06 10:15:30"),
        ("dateTime", "2026-13-06T10:15:30"),
    ],
)
def test_invalid_literals(datatype, value):
    """Values outside the datatype's lexical space are rejected."""
    violations = _typed_validator().check_statement(
        _stmt("A", datatype, literal=value)
    )
    assert _rules(violations) == ["datatype"]


# --- Allowed values -------------------------------------------------------


@pytest.mark.parametrize(
    "prop, value, ok",
    [
        ("licenceStatus", "active", True),
        ("licenceStatus", "closed", False),
        ("riskTier", "2", True),
        ("riskTier", 2, True),
        ("riskTier", "+02", True),
        ("riskTier", "4", False),
    ],
)
def test_data_allowed_values(validator, prop, value, ok):
    """Literals are compared in canonical form."""
    violations = validator.check_statement(_stmt("Bank", prop, literal=value))
    assert _rules(violations) == ([] if ok else ["allowed_values"])


def test_allowed_values_canonicalize_booleans_and_decimals():
    """'1' matches 'true', and '1.50' matches '1.5'."""
    release = OntologyRelease(
        ontology_uri="http://example.org/o",
        version="1",
        title="T",
        classes=[OntologyClass(uri=EX + "A", preferred_labels={"en": "A"})],
        properties=[
            OntologyProperty(
                uri=EX + "flag",
                preferred_labels={"en": "flag"},
                property_type="data",
                datatype=XSD + "boolean",
                constraints=[{"kind": "allowed_values",
                              "allowed_values": ["true"]}],
            ),
            OntologyProperty(
                uri=EX + "rate",
                preferred_labels={"en": "rate"},
                property_type="data",
                datatype=XSD + "decimal",
                constraints=[{"kind": "allowed_values",
                              "allowed_values": ["1.5", "100"]}],
            ),
        ],
    )
    validator = con.ConstraintValidator(release)
    assert validator.check_statement(_stmt("A", "flag", literal="1")) == []
    assert validator.check_statement(
        _stmt("A", "rate", literal="1.50")
    ) == []
    assert validator.check_statement(
        _stmt("A", "rate", literal=Decimal("1E+2"))
    ) == []
    assert _rules(validator.check_statement(
        _stmt("A", "flag", literal=False)
    )) == ["allowed_values"]


@pytest.mark.parametrize(
    "object_uri, ok",
    [(EX + "ojk", True), (EX + "fsa", False), (None, False)],
)
def test_object_allowed_values(validator, object_uri, ok):
    """Object values are compared by entity IRI, which is required."""
    violations = validator.check_statement(
        _stmt(
            "Bank", "licensedBy",
            object_class_uri=EX + "Regulator", object_uri=object_uri,
        )
    )
    assert _rules(violations) == ([] if ok else ["allowed_values"])


# --- Cardinality ----------------------------------------------------------


@pytest.mark.parametrize(
    "prop, count, expected",
    [
        ("legalName", 1, []),
        ("legalName", 2, ["max_count"]),
        ("foundedOn", 0, ["min_count"]),
        ("foundedOn", 1, []),
        ("foundedOn", 3, ["max_count"]),
        ("employs", 50, []),
        ("unknown", 1, ["unknown_property"]),
    ],
)
def test_check_cardinality(validator, prop, count, expected):
    """Counts are compared against sh:minCount and sh:maxCount."""
    violations = validator.check_cardinality(
        "s1", EX + "Bank", EX + prop, count
    )
    assert _rules(violations) == expected


# --- Whole-graph validation -----------------------------------------------


def test_validate_reports_against_pinned_release(validator):
    """A clean graph yields a valid report naming the release."""
    report = validator.validate(
        [
            _stmt("Bank", "foundedOn", literal="1998-01-01", subject="b1"),
            _stmt("Bank", "legalName", literal="Bank A", subject="b1"),
            _stmt("Person", "employedBy", subject="p1",
                  object_class_uri=EX + "Bank"),
        ]
    )
    release = build_finance_release()
    assert report.valid
    assert report.violations == []
    assert report.ontology_release_id == release.release_id
    assert report.ontology_version == "1.0.0"
    assert report.model_dump()["valid"] is True


def test_validate_counts_values_per_subject(validator):
    """Two values of a max-1 property on one subject violate maxCount."""
    report = validator.validate(
        [
            _stmt("Bank", "foundedOn", literal="1998-01-01", subject="b1"),
            _stmt("Bank", "legalName", literal="A", subject="b1"),
            _stmt("Bank", "legalName", literal="B", subject="b1"),
            _stmt("Bank", "foundedOn", literal="2001-01-01", subject="b2"),
            _stmt("Bank", "legalName", literal="C", subject="b2"),
        ]
    )
    assert not report.valid
    assert [(v.rule, v.subject) for v in report.violations] == [
        ("max_count", "b1")
    ]


def test_validate_checks_min_count_for_listed_subjects(validator):
    """Subjects without a required value violate minCount."""
    report = validator.validate(
        [_stmt("Bank", "legalName", literal="A", subject="b1")],
        subjects={"b2": EX + "Organization", "p1": EX + "Person"},
    )
    assert [(v.rule, v.subject, v.property_uri) for v in report.violations] \
        == [
            ("min_count", "b1", EX + "foundedOn"),
            ("min_count", "b2", EX + "foundedOn"),
        ]


def test_validate_reports_listed_subjects_of_unknown_classes(validator):
    """Extra subjects must have a class defined in the release."""
    report = validator.validate([], subjects={"r1": EX + "Robot"})
    assert [(v.rule, v.subject) for v in report.violations] == [
        ("unknown_class", "r1")
    ]


def test_validate_ignores_min_count_of_deprecated_properties():
    """Deprecated properties are not required any more."""
    release = build_finance_release()
    founded = release.get_property(EX + "foundedOn")
    founded.status = "deprecated"
    report = con.ConstraintValidator(release).validate(
        [], subjects={"b1": EX + "Bank"}
    )
    assert report.valid


def test_validate_sorts_violations_deterministically(validator):
    """Violations are ordered by subject, property, then rule."""
    report = validator.validate(
        [
            _stmt("Person", "riskTier", literal="9", subject="z"),
            _stmt("Person", "employs", subject="a",
                  object_class_uri=EX + "Bank"),
        ]
    )
    keys = [(v.subject, v.property_uri, v.rule) for v in report.violations]
    assert keys == sorted(keys)
    assert {v.rule for v in report.violations} == {
        "domain", "range", "allowed_values"
    }


def test_validate_rejects_conflicting_subject_classes(validator):
    """A subject cannot be given two different classes."""
    with pytest.raises(ValueError):
        validator.validate(
            [
                _stmt("Bank", "legalName", literal="A", subject="b1"),
                _stmt("Person", "legalName", literal="A", subject="b1"),
            ]
        )
    with pytest.raises(ValueError):
        validator.validate(
            [_stmt("Bank", "legalName", literal="A", subject="b1")],
            subjects={"b1": EX + "Person"},
        )


# --- Unsupported constraints ----------------------------------------------


def test_unsupported_constraint_kind_fails_at_validation():
    """A constraint that bypassed model validation still fails loudly."""
    release = build_finance_release()
    release.get_property(EX + "legalName").constraints.append(
        PropertyConstraint.model_construct(
            kind="pattern", min_count=None, max_count=None,
            allowed_values=["^[A-Z]"],
        )
    )
    with pytest.raises(UnsupportedConstraintError):
        con.ConstraintValidator(release)


def test_long_decimals_are_not_rounded_into_allowed_values():
    """1.000...01 is not the allowed value 1."""
    release = OntologyRelease(
        ontology_uri="http://example.org/o",
        version="1",
        title="T",
        classes=[OntologyClass(uri=EX + "A", preferred_labels={"en": "A"})],
        properties=[
            OntologyProperty(
                uri=EX + "rate",
                preferred_labels={"en": "rate"},
                property_type="data",
                datatype=XSD + "decimal",
                constraints=[{"kind": "allowed_values",
                              "allowed_values": ["1"]}],
            )
        ],
    )
    validator = con.ConstraintValidator(release)
    near_one = _stmt("A", "rate", literal="1.0000000000000000000000000001")
    assert _rules(validator.check_statement(near_one)) == ["allowed_values"]
    assert validator.check_statement(_stmt("A", "rate", literal="1.00")) == []
