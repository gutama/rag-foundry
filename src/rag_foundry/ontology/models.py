"""Ontology domain models: classes, properties, constraints and releases.

Implements the provider-neutral ontology representation of ADR-0011 and
ARCHITECTURE.md §8.5. Terms are identified by RDF-compatible IRIs so they
keep the same identity in every serialization format.

Only the constraint kinds in ``SUPPORTED_CONSTRAINT_KINDS`` and the datatypes
in ``SUPPORTED_DATATYPES`` are implemented. ADR-0011 requires anything outside
that subset to fail explicitly instead of being ignored, so an unsupported
constraint kind raises ``UnsupportedConstraintError`` as soon as it is built.
"""

import re
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from rag_foundry.ontology.datatypes import (
    SUPPORTED_DATATYPES,
    XSD_NAMESPACE,
    is_valid_lexical,
)

__all__ = [
    "SUPPORTED_CONSTRAINT_KINDS",
    "SUPPORTED_DATATYPES",
    "XSD_NAMESPACE",
    "OntologyClass",
    "OntologyProperty",
    "OntologyRelease",
    "PropertyConstraint",
    "TermStatus",
    "UnsupportedConstraintError",
    "UnsupportedFeatureError",
    "validate_iri",
]

SUPPORTED_CONSTRAINT_KINDS = ("cardinality", "allowed_values")

TermStatus = Literal["draft", "approved", "deprecated"]

# An absolute IRI: a scheme, a colon, then characters that are neither
# control characters, spaces nor among those RFC 3987 excludes from IRIs.
# This is also exactly what Turtle accepts inside <...>.
_IRI_PATTERN = re.compile(
    r'^[A-Za-z][A-Za-z0-9+.\-]*:[^\x00-\x20\x7f<>"{}|\\^`]+$'
)

# A well-formed BCP 47 language tag, as required by RDF and Turtle.
_LANGUAGE_TAG_PATTERN = re.compile(r"^[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*$")


class UnsupportedFeatureError(Exception):
    """Raised for an ontology feature outside the supported subset.

    ADR-0011 requires unsupported semantics to fail explicitly instead of
    being ignored. Deliberately not a ``ValueError``: Pydantic lets it
    propagate unwrapped, so callers can tell "unsupported feature" apart
    from "invalid data".
    """


class UnsupportedConstraintError(UnsupportedFeatureError):
    """Raised for a constraint kind outside the supported subset.

    Attributes:
        kind: The constraint kind that was requested.
    """

    def __init__(self, kind: str) -> None:
        """Initialize the error for the given constraint kind.

        Args:
            kind: The unsupported constraint kind.
        """
        self.kind = kind
        supported = ", ".join(SUPPORTED_CONSTRAINT_KINDS)
        super().__init__(
            f"Unsupported ontology constraint kind {kind!r}; "
            f"supported kinds are: {supported}"
        )


def validate_iri(value: str) -> str:
    """Check that a value is an absolute IRI.

    Args:
        value: Candidate IRI.

    Returns:
        The unchanged IRI.

    Raises:
        ValueError: If the value is not an absolute IRI.
    """
    if not _IRI_PATTERN.match(value):
        raise ValueError(f"{value!r} is not an absolute IRI")
    return value


def _validate_iri_list(values: List[str]) -> List[str]:
    """Check that a list holds distinct absolute IRIs.

    Args:
        values: Candidate IRIs.

    Returns:
        The unchanged list.

    Raises:
        ValueError: If an entry is not an IRI or appears twice.
    """
    for value in values:
        validate_iri(value)
    if len(set(values)) != len(values):
        raise ValueError(f"Duplicate IRIs in {values!r}")
    return values


def _validate_language_map(texts: Dict[str, str]) -> Dict[str, str]:
    """Check language tags and texts of a language-to-text map.

    Args:
        texts: Language tag to text mapping; may be empty.

    Returns:
        The unchanged mapping.

    Raises:
        ValueError: If a tag is not BCP 47 or a text is blank.
    """
    for language, text in texts.items():
        if not _LANGUAGE_TAG_PATTERN.match(language):
            raise ValueError(f"{language!r} is not a BCP 47 language tag")
        if not text.strip():
            raise ValueError(f"The {language!r} text cannot be blank")
    return texts


def _validate_labels(labels: Dict[str, str]) -> Dict[str, str]:
    """Check that a label map is non-empty and well-formed.

    Args:
        labels: Language tag to label mapping.

    Returns:
        The unchanged mapping.

    Raises:
        ValueError: If the map is empty, a tag is not BCP 47 or a label is
            blank.
    """
    if not labels:
        raise ValueError("At least one preferred label is required")
    return _validate_language_map(labels)


def _breadth_first(edges: Dict[str, List[str]], start: str) -> List[str]:
    """Walk a graph breadth-first from a node, excluding the node itself.

    Args:
        edges: Node to neighbour list; every neighbour must be a key.
        start: Node to start from.

    Returns:
        Reachable nodes in breadth-first order, each listed once.

    Raises:
        KeyError: If ``start`` is not a node of the graph.
    """
    if start not in edges:
        raise KeyError(start)
    result: List[str] = []
    queue = deque(edges[start])
    while queue:
        current = queue.popleft()
        if current in result:
            continue
        result.append(current)
        queue.extend(edges[current])
    return result


class OntologyClass(BaseModel):
    """An ontology class (``owl:Class``) identified by a stable IRI."""

    uri: str = Field(description="Stable class IRI")
    preferred_labels: Dict[str, str] = Field(
        description="Language tag to preferred label"
    )
    parent_class_uris: List[str] = Field(
        default_factory=list,
        description="Direct superclass IRIs (rdfs:subClassOf)",
    )
    description: Dict[str, str] = Field(
        default_factory=dict, description="Language tag to description"
    )
    identity_rules: List[str] = Field(
        default_factory=list,
        description="Rules deciding when two entities of the class are one",
    )
    status: TermStatus = Field(default="draft", description="Term status")

    _check_uri = field_validator("uri")(validate_iri)
    _check_parents = field_validator("parent_class_uris")(_validate_iri_list)
    _check_labels = field_validator("preferred_labels")(_validate_labels)
    _check_description = field_validator("description")(
        _validate_language_map
    )

    @model_validator(mode="after")
    def _check_not_own_parent(self) -> "OntologyClass":
        """Reject a class that lists itself as a parent."""
        if self.uri in self.parent_class_uris:
            raise ValueError(f"Class {self.uri} cannot be its own parent")
        return self


class PropertyConstraint(BaseModel):
    """A constraint on property values, limited to the supported subset.

    ``cardinality`` maps to SHACL ``sh:minCount``/``sh:maxCount`` and
    ``allowed_values`` maps to ``sh:in``.
    """

    kind: str = Field(description="One of SUPPORTED_CONSTRAINT_KINDS")
    min_count: Optional[int] = Field(
        default=None, ge=0, description="Minimum values per subject"
    )
    max_count: Optional[int] = Field(
        default=None, ge=0, description="Maximum values per subject"
    )
    allowed_values: List[str] = Field(
        default_factory=list, description="Permitted values"
    )

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, kind: str) -> str:
        """Fail explicitly for constraint kinds outside the subset."""
        if kind not in SUPPORTED_CONSTRAINT_KINDS:
            raise UnsupportedConstraintError(kind)
        return kind

    @model_validator(mode="after")
    def _check_shape(self) -> "PropertyConstraint":
        """Check that only the fields relevant to the kind are set."""
        has_counts = self.min_count is not None or self.max_count is not None
        if self.kind == "cardinality":
            if self.allowed_values:
                raise ValueError("Cardinality cannot carry allowed values")
            if not has_counts:
                raise ValueError("Cardinality needs min_count or max_count")
            if (
                self.min_count is not None
                and self.max_count is not None
                and self.min_count > self.max_count
            ):
                raise ValueError("min_count cannot exceed max_count")
        else:
            if has_counts:
                raise ValueError("Allowed values cannot carry counts")
            if not self.allowed_values:
                raise ValueError("Allowed values cannot be empty")
            if len(set(self.allowed_values)) != len(self.allowed_values):
                raise ValueError("Allowed values must be unique")
        return self


class OntologyProperty(BaseModel):
    """An object or data property with domain, range and constraints."""

    uri: str = Field(description="Stable property IRI")
    preferred_labels: Dict[str, str] = Field(
        description="Language tag to preferred label"
    )
    description: Dict[str, str] = Field(
        default_factory=dict, description="Language tag to description"
    )
    property_type: Literal["object", "data"] = Field(
        description="owl:ObjectProperty or owl:DatatypeProperty"
    )
    domain_class_uris: List[str] = Field(
        default_factory=list,
        description="Classes a subject may belong to (empty: any class)",
    )
    range_class_uris: List[str] = Field(
        default_factory=list,
        description="Object property only: classes an object may belong to",
    )
    datatype: Optional[str] = Field(
        default=None, description="Data property only: XSD datatype IRI"
    )
    inverse_property_uri: Optional[str] = Field(
        default=None, description="Object property only: owl:inverseOf"
    )
    temporal: bool = Field(
        default=False, description="True if values hold for a time interval"
    )
    provenance_required: bool = Field(
        default=True, description="True if assertions must cite evidence"
    )
    constraints: List[PropertyConstraint] = Field(
        default_factory=list, description="At most one constraint per kind"
    )
    status: TermStatus = Field(default="draft", description="Term status")

    _check_uri = field_validator("uri")(validate_iri)
    _check_labels = field_validator("preferred_labels")(_validate_labels)
    _check_description = field_validator("description")(
        _validate_language_map
    )
    _check_domain = field_validator("domain_class_uris")(_validate_iri_list)
    _check_range = field_validator("range_class_uris")(_validate_iri_list)

    @field_validator("inverse_property_uri")
    @classmethod
    def _check_inverse_iri(cls, value: Optional[str]) -> Optional[str]:
        """Validate the inverse property IRI when present."""
        return None if value is None else validate_iri(value)

    @model_validator(mode="after")
    def _check_typing(self) -> "OntologyProperty":
        """Check fields that depend on the property type."""
        if self.property_type == "object":
            if self.datatype is not None:
                raise ValueError("Object properties cannot have a datatype")
            for uri in self.range_class_uris:
                if uri.startswith(XSD_NAMESPACE):
                    raise ValueError(f"{uri} is a datatype, not a class")
            if self.inverse_property_uri == self.uri:
                raise ValueError("A property cannot be its own inverse")
        else:
            if self.datatype not in SUPPORTED_DATATYPES:
                raise ValueError(
                    "Data properties need a supported datatype, "
                    f"got {self.datatype!r}"
                )
            if self.range_class_uris:
                raise ValueError("Data properties cannot have range classes")
            if self.inverse_property_uri is not None:
                raise ValueError("Data properties cannot have an inverse")
        kinds = [constraint.kind for constraint in self.constraints]
        if len(set(kinds)) != len(kinds):
            raise ValueError("At most one constraint of each kind is allowed")
        # RDF does not order constraints, so keep one canonical order to
        # make exports and round trips deterministic.
        self.constraints.sort(
            key=lambda c: SUPPORTED_CONSTRAINT_KINDS.index(c.kind)
        )
        allowed = self.constraint("allowed_values")
        for value in allowed.allowed_values if allowed else []:
            if self.property_type == "object":
                validate_iri(value)
            elif not is_valid_lexical(self.datatype or "", value):
                raise ValueError(
                    f"Allowed value {value!r} is not a valid {self.datatype}"
                )
        return self

    def constraint(self, kind: str) -> Optional[PropertyConstraint]:
        """Return the property's constraint of the given kind.

        Args:
            kind: Constraint kind.

        Returns:
            The matching constraint, or None if the property has none.
        """
        for constraint in self.constraints:
            if constraint.kind == kind:
                return constraint
        return None


class OntologyRelease(BaseModel):
    """A versioned, internally consistent set of classes and properties.

    Every class referenced as a parent, domain or range, and every inverse
    property, must be defined in the same release, and the subclass
    hierarchy must be acyclic. Approved releases are immutable; the registry
    enforces that rule.
    """

    release_id: uuid.UUID = Field(
        default_factory=uuid.uuid4, description="Unique release id"
    )
    ontology_uri: str = Field(description="IRI of the ontology")
    version: str = Field(description="Release version, e.g. 1.2.0")
    title: str = Field(description="Human-readable ontology title")
    description: Optional[str] = Field(
        default=None, description="Release description"
    )
    status: TermStatus = Field(default="draft", description="Release status")
    previous_release_id: Optional[uuid.UUID] = Field(
        default=None, description="Release this draft was derived from"
    )
    classes: List[OntologyClass] = Field(
        default_factory=list, description="Classes in the release"
    )
    properties: List[OntologyProperty] = Field(
        default_factory=list, description="Properties in the release"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Release creation timestamp",
    )
    published_at: Optional[datetime] = Field(
        default=None, description="When the release was approved"
    )

    _check_uri = field_validator("ontology_uri")(validate_iri)

    @field_validator("version", "title")
    @classmethod
    def _check_not_blank(cls, value: str) -> str:
        """Reject blank versions and titles."""
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> "OntologyRelease":
        """Check identifier uniqueness, references and acyclicity."""
        class_uris = [cls.uri for cls in self.classes]
        property_uris = [prop.uri for prop in self.properties]
        if len(set(class_uris)) != len(class_uris):
            raise ValueError("Class IRIs must be unique within a release")
        if len(set(property_uris)) != len(property_uris):
            raise ValueError("Property IRIs must be unique within a release")
        shared = set(class_uris) & set(property_uris)
        if shared:
            raise ValueError(f"IRIs used as class and property: {shared}")

        known_classes = set(class_uris)
        for cls in self.classes:
            for parent in cls.parent_class_uris:
                if parent not in known_classes:
                    raise ValueError(
                        f"Class {cls.uri} has undefined parent {parent}"
                    )
        properties = {prop.uri: prop for prop in self.properties}
        for prop in self.properties:
            for uri in prop.domain_class_uris + prop.range_class_uris:
                if uri not in known_classes:
                    raise ValueError(
                        f"Property {prop.uri} references undefined "
                        f"class {uri}"
                    )
            inverse_uri = prop.inverse_property_uri
            if inverse_uri is not None:
                inverse = properties.get(inverse_uri)
                if inverse is None or inverse.property_type != "object":
                    raise ValueError(
                        f"Inverse of {prop.uri} must be an object property "
                        "in the release"
                    )
        self._check_acyclic()
        return self

    def _check_acyclic(self) -> None:
        """Reject cycles in the subclass hierarchy.

        Raises:
            ValueError: If a class is its own ancestor.
        """
        parents = self._parent_map()
        visiting: set = set()
        done: set = set()

        def visit(uri: str) -> None:
            if uri in done:
                return
            if uri in visiting:
                raise ValueError(f"Subclass cycle detected at {uri}")
            visiting.add(uri)
            for parent in parents[uri]:
                visit(parent)
            visiting.discard(uri)
            done.add(uri)

        for uri in parents:
            visit(uri)

    def _parent_map(self) -> Dict[str, List[str]]:
        """Map each class IRI to its direct parent IRIs."""
        return {cls.uri: cls.parent_class_uris for cls in self.classes}

    def get_class(self, uri: str) -> Optional[OntologyClass]:
        """Find a class by IRI.

        Args:
            uri: Class IRI.

        Returns:
            The class, or None if the release does not define it.
        """
        return next((c for c in self.classes if c.uri == uri), None)

    def get_property(self, uri: str) -> Optional[OntologyProperty]:
        """Find a property by IRI.

        Args:
            uri: Property IRI.

        Returns:
            The property, or None if the release does not define it.
        """
        return next((p for p in self.properties if p.uri == uri), None)

    def ancestors(self, uri: str) -> List[str]:
        """List every superclass of a class, nearest first.

        Args:
            uri: Class IRI.

        Returns:
            Ancestor IRIs in breadth-first order, each listed once.

        Raises:
            KeyError: If the release does not define the class.
        """
        return _breadth_first(self._parent_map(), uri)

    def descendants(self, uri: str) -> List[str]:
        """List every subclass of a class, nearest first.

        Args:
            uri: Class IRI.

        Returns:
            Descendant IRIs in breadth-first order, each listed once.

        Raises:
            KeyError: If the release does not define the class.
        """
        parents = self._parent_map()
        children: Dict[str, List[str]] = {key: [] for key in parents}
        for child, child_parents in parents.items():
            for parent in child_parents:
                children[parent].append(child)
        return _breadth_first(children, uri)

    def is_subclass_of(self, uri: str, ancestor_uri: str) -> bool:
        """Check rdfs:subClassOf, reflexively and transitively.

        Args:
            uri: Candidate subclass IRI.
            ancestor_uri: Candidate superclass IRI.

        Returns:
            True if ``uri`` equals or descends from ``ancestor_uri``.

        Raises:
            KeyError: If the release does not define ``uri``.
        """
        return uri == ancestor_uri or ancestor_uri in self.ancestors(uri)
