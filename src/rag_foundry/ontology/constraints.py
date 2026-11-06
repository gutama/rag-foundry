"""Constraint validation against a pinned ontology release (ADR-0011).

The validator checks statements (subject, property, object or literal)
against one release:

- terms: classes and properties must exist and must not be deprecated;
- domain and range: several classes mean "any of", and subclasses count
  (``rdfs:subClassOf`` is applied transitively);
- value kind: object properties take entities, data properties literals;
- datatype: literals must be in the lexical space of the property's XSD
  datatype; Python values are converted to their lexical form first;
- allowed values: compared in canonical form, so ``"02"`` matches ``"2"``
  for integers and ``"1"`` matches ``"true"`` for booleans;
- cardinality: ``min_count`` and ``max_count`` per subject and property.

Nothing outside the supported subset is checked silently: a release that
somehow carries another constraint kind is refused when the validator is
built.
"""

import uuid
from collections import Counter
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Literal,
    Mapping,
    Optional,
    Tuple,
)

from pydantic import BaseModel, Field, computed_field

from rag_foundry.ontology.datatypes import (
    canonical_form,
    is_valid_lexical,
    lexical_form,
)
from rag_foundry.ontology.models import (
    SUPPORTED_CONSTRAINT_KINDS,
    OntologyClass,
    OntologyProperty,
    OntologyRelease,
    UnsupportedConstraintError,
)

ViolationRule = Literal[
    "unknown_class",
    "unknown_property",
    "deprecated_term",
    "domain",
    "range",
    "value_kind",
    "datatype",
    "allowed_values",
    "min_count",
    "max_count",
]


class Statement(BaseModel):
    """A statement to validate: a subject, a property and its value.

    Object properties take ``object_class_uri`` (and ``object_uri`` when the
    property restricts allowed values); data properties take ``literal``.
    """

    subject: str = Field(description="Identifier of the subject entity")
    subject_class_uri: str = Field(description="Ontology class of subject")
    property_uri: str = Field(description="Property IRI")
    object_uri: Optional[str] = Field(
        default=None, description="Canonical IRI of the object entity"
    )
    object_class_uri: Optional[str] = Field(
        default=None, description="Ontology class of the object entity"
    )
    literal: Optional[Any] = Field(
        default=None, description="Literal value for data properties"
    )


class ConstraintViolation(BaseModel):
    """One failed check."""

    rule: ViolationRule = Field(description="The check that failed")
    message: str = Field(description="Human-readable explanation")
    subject: Optional[str] = Field(
        default=None, description="Subject the violation concerns"
    )
    property_uri: Optional[str] = Field(
        default=None, description="Property the violation concerns"
    )


class ConstraintReport(BaseModel):
    """The outcome of validating statements against one release."""

    ontology_release_id: uuid.UUID = Field(
        description="Release the statements were validated against"
    )
    ontology_version: str = Field(description="Version of that release")
    violations: List[ConstraintViolation] = Field(
        default_factory=list, description="Violations, sorted"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def valid(self) -> bool:
        """True if no check failed."""
        return not self.violations


# --- Validator ------------------------------------------------------------


class ConstraintValidator:
    """Validates statements against one ontology release."""

    def __init__(self, release: OntologyRelease) -> None:
        """Index the release and refuse unsupported constraint kinds.

        Args:
            release: The pinned release to validate against.

        Raises:
            UnsupportedConstraintError: If a property carries a constraint
                kind outside the supported subset.
        """
        self.release = release
        self._classes: Dict[str, OntologyClass] = {
            cls.uri: cls for cls in release.classes
        }
        self._properties: Dict[str, OntologyProperty] = {
            prop.uri: prop for prop in release.properties
        }
        for prop in release.properties:
            for constraint in prop.constraints:
                if constraint.kind not in SUPPORTED_CONSTRAINT_KINDS:
                    raise UnsupportedConstraintError(constraint.kind)

    def check_statement(
        self, statement: Statement
    ) -> List[ConstraintViolation]:
        """Check terms, domain, range, value kind, datatype and values.

        Cardinality needs every value of a subject and property, so it is
        checked by ``check_cardinality`` and ``validate`` instead.

        Args:
            statement: The statement to check.

        Returns:
            Violations in the order the checks ran.
        """
        report = _Collector(statement.subject, statement.property_uri)
        subject_known = self._check_class(
            report, statement.subject_class_uri, "subject"
        )
        prop = self._properties.get(statement.property_uri)
        if prop is None:
            report.add(
                "unknown_property",
                f"{statement.property_uri} is not defined in this release",
            )
            return report.violations
        if prop.status == "deprecated":
            report.add("deprecated_term", f"{prop.uri} is deprecated")
        if subject_known and not self._in_classes(
            statement.subject_class_uri, prop.domain_class_uris
        ):
            report.add(
                "domain",
                f"{statement.subject_class_uri} is not in the domain of "
                f"{prop.uri}",
            )
        if prop.property_type == "object":
            self._check_object(report, statement, prop)
        else:
            self._check_literal(report, statement, prop)
        return report.violations

    def check_cardinality(
        self,
        subject: str,
        subject_class_uri: str,
        property_uri: str,
        count: int,
    ) -> List[ConstraintViolation]:
        """Check how many values a subject has for a property.

        Args:
            subject: Subject identifier.
            subject_class_uri: Ontology class of the subject.
            property_uri: Property IRI.
            count: Number of values the subject has.

        Returns:
            Violations of ``min_count`` or ``max_count``.
        """
        report = _Collector(subject, property_uri)
        prop = self._properties.get(property_uri)
        if prop is None:
            report.add(
                "unknown_property",
                f"{property_uri} is not defined in this release",
            )
            return report.violations
        cardinality = prop.constraint("cardinality")
        if cardinality is None:
            return report.violations
        if cardinality.min_count is not None and count < cardinality.min_count:
            report.add(
                "min_count",
                f"{subject} ({subject_class_uri}) has {count} value(s) for "
                f"{property_uri}; at least {cardinality.min_count} required",
            )
        if cardinality.max_count is not None and count > cardinality.max_count:
            report.add(
                "max_count",
                f"{subject} has {count} value(s) for {property_uri}; at "
                f"most {cardinality.max_count} allowed",
            )
        return report.violations

    def validate(
        self,
        statements: Iterable[Statement],
        subjects: Optional[Mapping[str, str]] = None,
    ) -> ConstraintReport:
        """Validate a set of statements, including cardinality.

        Every subject of a statement, plus every entry of ``subjects``, is
        checked for required (``min_count``) properties whose domain covers
        its class. Deprecated properties are never required.

        Args:
            statements: Statements to validate.
            subjects: Extra subjects (identifier to class IRI) that must
                satisfy ``min_count`` even without statements.

        Returns:
            A report pinned to this release, violations sorted.

        Raises:
            ValueError: If one subject is given two different classes.
        """
        statements = list(statements)
        subject_classes = self._subject_classes(statements, subjects or {})
        violations: List[ConstraintViolation] = []
        for statement in statements:
            violations.extend(self.check_statement(statement))

        stated_subjects = {s.subject for s in statements}
        for subject, class_uri in sorted((subjects or {}).items()):
            if subject not in stated_subjects:
                report = _Collector(subject, None)
                self._check_class(report, class_uri, "subject")
                violations.extend(report.violations)

        counts = Counter((s.subject, s.property_uri) for s in statements)
        pairs = {pair for pair in counts if pair[1] in self._properties}
        for subject, class_uri in subject_classes.items():
            for prop in self._required_properties(class_uri):
                pairs.add((subject, prop.uri))
        for subject, property_uri in sorted(pairs):
            violations.extend(
                self.check_cardinality(
                    subject,
                    subject_classes[subject],
                    property_uri,
                    counts[(subject, property_uri)],
                )
            )
        violations.sort(
            key=lambda v: (
                v.subject or "", v.property_uri or "", v.rule, v.message
            )
        )
        return ConstraintReport(
            ontology_release_id=self.release.release_id,
            ontology_version=self.release.version,
            violations=violations,
        )

    # --- Helpers ----------------------------------------------------------

    def _check_class(
        self, report: "_Collector", class_uri: str, role: str
    ) -> bool:
        """Report unknown or deprecated classes; True if the class exists."""
        cls = self._classes.get(class_uri)
        if cls is None:
            report.add(
                "unknown_class",
                f"The {role} class {class_uri} is not defined in this "
                "release",
            )
            return False
        if cls.status == "deprecated":
            report.add(
                "deprecated_term",
                f"The {role} class {class_uri} is deprecated",
            )
        return True

    def _in_classes(self, class_uri: str, allowed: List[str]) -> bool:
        """Check membership in "any of" classes; empty means any class."""
        if not allowed:
            return True
        return any(
            self.release.is_subclass_of(class_uri, uri) for uri in allowed
        )

    def _check_object(
        self,
        report: "_Collector",
        statement: Statement,
        prop: OntologyProperty,
    ) -> None:
        """Check the object side of an object-property statement."""
        if statement.literal is not None or statement.object_class_uri is None:
            report.add(
                "value_kind",
                f"{prop.uri} is an object property and needs an object "
                "entity, not a literal",
            )
            return
        object_known = self._check_class(
            report, statement.object_class_uri, "object"
        )
        if object_known and not self._in_classes(
            statement.object_class_uri, prop.range_class_uris
        ):
            report.add(
                "range",
                f"{statement.object_class_uri} is not in the range of "
                f"{prop.uri}",
            )
        allowed = prop.constraint("allowed_values")
        if allowed is not None and (
            statement.object_uri not in allowed.allowed_values
        ):
            report.add(
                "allowed_values",
                f"{statement.object_uri} is not an allowed value of "
                f"{prop.uri}",
            )

    def _check_literal(
        self,
        report: "_Collector",
        statement: Statement,
        prop: OntologyProperty,
    ) -> None:
        """Check the literal side of a data-property statement."""
        if (
            statement.literal is None
            or statement.object_class_uri is not None
            or statement.object_uri is not None
        ):
            report.add(
                "value_kind",
                f"{prop.uri} is a data property and needs a literal value, "
                "not an entity",
            )
            return
        datatype = prop.datatype or ""
        text = lexical_form(statement.literal)
        if not is_valid_lexical(datatype, text):
            report.add(
                "datatype",
                f"{text!r} is not a valid {datatype} for {prop.uri}",
            )
            return
        allowed = prop.constraint("allowed_values")
        if allowed is not None:
            permitted = {
                canonical_form(datatype, value)
                for value in allowed.allowed_values
            }
            if canonical_form(datatype, text) not in permitted:
                report.add(
                    "allowed_values",
                    f"{text!r} is not an allowed value of {prop.uri}",
                )

    def _required_properties(
        self, class_uri: str
    ) -> List[OntologyProperty]:
        """List active properties with min_count whose domain covers a class."""
        if class_uri not in self._classes:
            return []
        required = []
        for prop in self._properties.values():
            cardinality = prop.constraint("cardinality")
            if (
                prop.status != "deprecated"
                and cardinality is not None
                and cardinality.min_count
                and self._in_classes(class_uri, prop.domain_class_uris)
            ):
                required.append(prop)
        return required

    @staticmethod
    def _subject_classes(
        statements: List[Statement], subjects: Mapping[str, str]
    ) -> Dict[str, str]:
        """Collect one class per subject, refusing conflicts.

        Raises:
            ValueError: If a subject is given two different classes.
        """
        classes: Dict[str, str] = {}
        pairs: List[Tuple[str, str]] = [
            (s.subject, s.subject_class_uri) for s in statements
        ]
        pairs.extend(subjects.items())
        for subject, class_uri in pairs:
            known = classes.setdefault(subject, class_uri)
            if known != class_uri:
                raise ValueError(
                    f"Subject {subject} is given two classes: {known} and "
                    f"{class_uri}"
                )
        return classes


class _Collector:
    """Accumulates violations for one subject and property."""

    def __init__(self, subject: str, property_uri: Optional[str]) -> None:
        self.subject = subject
        self.property_uri = property_uri
        self.violations: List[ConstraintViolation] = []

    def add(self, rule: ViolationRule, message: str) -> None:
        """Record a violation."""
        self.violations.append(
            ConstraintViolation(
                rule=rule,
                message=message,
                subject=self.subject,
                property_uri=self.property_uri,
            )
        )
