"""JSON-LD and Turtle interchange for ontology releases (ADR-0011).

The provider-neutral model maps onto standard vocabulary:

- a release is an ``owl:Ontology`` with ``owl:versionInfo``, ``rdfs:label``
  (title) and ``rdfs:comment`` (description);
- a class is an ``owl:Class`` with ``rdfs:label``, ``rdfs:comment``,
  ``rdfs:subClassOf`` and ``owl:deprecated``;
- a property is an ``owl:ObjectProperty`` or ``owl:DatatypeProperty`` with
  ``rdfs:domain``, ``rdfs:range`` and ``owl:inverseOf``. Several domain or
  range classes mean "any of", which OWL writes as ``owl:unionOf``;
- constraints are ``sh:PropertyShape`` nodes with ``sh:path``,
  ``sh:targetSubjectsOf``, ``sh:minCount``, ``sh:maxCount`` and ``sh:in``.
  A minimum count also applies to every instance of the property's domain,
  so its shape adds ``sh:targetClass`` for each domain class.

Identity rules and the ``temporal``/``provenance_required`` flags have no
standard term and use the ``rf:`` namespace (``RF_NAMESPACE``).

Import is closed-world: any node type, predicate or JSON-LD keyword outside
this mapping raises ``UnsupportedFeatureError`` (``UnsupportedConstraintError``
for SHACL constraint components) instead of being skipped, and structural
problems raise ``OntologyImportError``. Imported terms are drafts unless
marked ``owl:deprecated``; approval only happens through the registry.

Turtle is export-only. It is rendered from the JSON-LD export, so both
formats always state the same triples.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import ValidationError

from rag_foundry.ontology.datatypes import (
    XSD_BOOLEAN,
    XSD_INTEGER,
    XSD_STRING,
)
from rag_foundry.ontology.models import (
    SUPPORTED_DATATYPES,
    XSD_NAMESPACE,
    OntologyClass,
    OntologyProperty,
    OntologyRelease,
    UnsupportedConstraintError,
    UnsupportedFeatureError,
)

OWL_NAMESPACE = "http://www.w3.org/2002/07/owl#"
RDFS_NAMESPACE = "http://www.w3.org/2000/01/rdf-schema#"
SH_NAMESPACE = "http://www.w3.org/ns/shacl#"
RF_NAMESPACE = "urn:rag-foundry:vocab#"

PREFIXES: Dict[str, str] = {
    "owl": OWL_NAMESPACE,
    "rdfs": RDFS_NAMESPACE,
    "sh": SH_NAMESPACE,
    "xsd": XSD_NAMESPACE,
    "rf": RF_NAMESPACE,
}

OWL_ONTOLOGY = OWL_NAMESPACE + "Ontology"
OWL_CLASS = OWL_NAMESPACE + "Class"
OWL_OBJECT_PROPERTY = OWL_NAMESPACE + "ObjectProperty"
OWL_DATATYPE_PROPERTY = OWL_NAMESPACE + "DatatypeProperty"
OWL_DEPRECATED = OWL_NAMESPACE + "deprecated"
OWL_INVERSE_OF = OWL_NAMESPACE + "inverseOf"
OWL_THING = OWL_NAMESPACE + "Thing"
OWL_UNION_OF = OWL_NAMESPACE + "unionOf"
OWL_VERSION_INFO = OWL_NAMESPACE + "versionInfo"
RDFS_COMMENT = RDFS_NAMESPACE + "comment"
RDFS_DOMAIN = RDFS_NAMESPACE + "domain"
RDFS_LABEL = RDFS_NAMESPACE + "label"
RDFS_RANGE = RDFS_NAMESPACE + "range"
RDFS_SUBCLASS_OF = RDFS_NAMESPACE + "subClassOf"
SH_IN = SH_NAMESPACE + "in"
SH_MAX_COUNT = SH_NAMESPACE + "maxCount"
SH_MIN_COUNT = SH_NAMESPACE + "minCount"
SH_PATH = SH_NAMESPACE + "path"
SH_PROPERTY_SHAPE = SH_NAMESPACE + "PropertyShape"
SH_TARGET_CLASS = SH_NAMESPACE + "targetClass"
SH_TARGET_SUBJECTS_OF = SH_NAMESPACE + "targetSubjectsOf"
RF_IDENTITY_RULE = RF_NAMESPACE + "identityRule"
RF_PROVENANCE_REQUIRED = RF_NAMESPACE + "provenanceRequired"
RF_TEMPORAL = RF_NAMESPACE + "temporal"

# BCP 47 tag for "undetermined", used for labels without a language tag.
UNDETERMINED_LANGUAGE = "und"

_NODE_KINDS = {
    OWL_ONTOLOGY: "ontology",
    OWL_CLASS: "class",
    OWL_OBJECT_PROPERTY: "object",
    OWL_DATATYPE_PROPERTY: "data",
    SH_PROPERTY_SHAPE: "shape",
}


class OntologyImportError(ValueError):
    """Raised for a structurally invalid ontology document."""


# --- Export ---------------------------------------------------------------


def export_jsonld(release: OntologyRelease) -> Dict[str, Any]:
    """Export a release as a JSON-LD document.

    Nodes appear in a fixed order (ontology, classes, properties, shapes),
    each group sorted by IRI, so equal releases give identical documents.

    Args:
        release: Release to export.

    Returns:
        A JSON-serializable JSON-LD document with an ``@graph``.
    """
    properties = sorted(release.properties, key=lambda p: p.uri)
    graph: List[Dict[str, Any]] = [_ontology_node(release)]
    graph.extend(
        _class_node(cls)
        for cls in sorted(release.classes, key=lambda c: c.uri)
    )
    graph.extend(_property_node(prop) for prop in properties)
    graph.extend(_shape_node(prop) for prop in properties if prop.constraints)
    return {"@context": dict(PREFIXES), "@graph": graph}


def _ontology_node(release: OntologyRelease) -> Dict[str, Any]:
    """Build the owl:Ontology header node."""
    node: Dict[str, Any] = {
        "@id": release.ontology_uri,
        "@type": "owl:Ontology",
        "owl:versionInfo": release.version,
        "rdfs:label": release.title,
    }
    if release.description:
        node["rdfs:comment"] = release.description
    return node


def _language_values(texts: Dict[str, str]) -> List[Dict[str, str]]:
    """Build language-tagged literals, sorted by language tag."""
    return [
        {"@value": text, "@language": language}
        for language, text in sorted(texts.items())
    ]


def _class_expression(uris: List[str]) -> Dict[str, Any]:
    """Reference one class, or the union of several."""
    if len(uris) == 1:
        return {"@id": uris[0]}
    return {
        "@type": "owl:Class",
        "owl:unionOf": {"@list": [{"@id": uri} for uri in uris]},
    }


def _class_node(cls: OntologyClass) -> Dict[str, Any]:
    """Build an owl:Class node."""
    node: Dict[str, Any] = {
        "@id": cls.uri,
        "@type": "owl:Class",
        "rdfs:label": _language_values(cls.preferred_labels),
    }
    if cls.description:
        node["rdfs:comment"] = _language_values(cls.description)
    if cls.parent_class_uris:
        node["rdfs:subClassOf"] = [
            {"@id": uri} for uri in cls.parent_class_uris
        ]
    if cls.identity_rules:
        node["rf:identityRule"] = list(cls.identity_rules)
    if cls.status == "deprecated":
        node["owl:deprecated"] = True
    return node


def _property_node(prop: OntologyProperty) -> Dict[str, Any]:
    """Build an owl:ObjectProperty or owl:DatatypeProperty node."""
    is_object = prop.property_type == "object"
    node: Dict[str, Any] = {
        "@id": prop.uri,
        "@type": "owl:ObjectProperty" if is_object else "owl:DatatypeProperty",
        "rdfs:label": _language_values(prop.preferred_labels),
    }
    if prop.description:
        node["rdfs:comment"] = _language_values(prop.description)
    if prop.domain_class_uris:
        node["rdfs:domain"] = _class_expression(prop.domain_class_uris)
    if is_object and prop.range_class_uris:
        node["rdfs:range"] = _class_expression(prop.range_class_uris)
    if not is_object:
        node["rdfs:range"] = {"@id": prop.datatype}
    if prop.inverse_property_uri:
        node["owl:inverseOf"] = {"@id": prop.inverse_property_uri}
    node["rf:temporal"] = prop.temporal
    node["rf:provenanceRequired"] = prop.provenance_required
    if prop.status == "deprecated":
        node["owl:deprecated"] = True
    return node


def _shape_node(prop: OntologyProperty) -> Dict[str, Any]:
    """Build the sh:PropertyShape holding a property's constraints."""
    node: Dict[str, Any] = {
        "@type": "sh:PropertyShape",
        "sh:path": {"@id": prop.uri},
        "sh:targetSubjectsOf": {"@id": prop.uri},
    }
    cardinality = prop.constraint("cardinality")
    if cardinality is not None and cardinality.min_count:
        node["sh:targetClass"] = [
            {"@id": uri} for uri in prop.domain_class_uris
        ]
    if cardinality is not None:
        if cardinality.min_count is not None:
            node["sh:minCount"] = cardinality.min_count
        if cardinality.max_count is not None:
            node["sh:maxCount"] = cardinality.max_count
    allowed = prop.constraint("allowed_values")
    if allowed is not None:
        node["sh:in"] = {
            "@list": [
                _allowed_value(prop, value)
                for value in allowed.allowed_values
            ]
        }
    return node


def _allowed_value(prop: OntologyProperty, value: str) -> Any:
    """Encode an allowed value as an IRI reference or typed literal."""
    if prop.property_type == "object":
        return {"@id": value}
    if prop.datatype == XSD_STRING:
        return value
    local_name = prop.datatype[len(XSD_NAMESPACE):]
    return {"@value": value, "@type": "xsd:" + local_name}


# --- Import ---------------------------------------------------------------


def import_jsonld(document: Any) -> OntologyRelease:
    """Import a release from a JSON-LD document.

    The document must be an object with an inline ``@context`` of prefix
    mappings and an ``@graph`` holding exactly one ``owl:Ontology`` node.

    Args:
        document: Parsed JSON-LD document.

    Returns:
        A draft release.

    Raises:
        OntologyImportError: If the document is structurally invalid or
            describes an inconsistent release.
        UnsupportedFeatureError: If it uses a feature outside the subset.
        UnsupportedConstraintError: If a shape uses an unsupported SHACL
            constraint component.
    """
    if not isinstance(document, dict):
        raise OntologyImportError("An ontology document must be an object")
    extra_keys = set(document) - {"@context", "@graph"}
    if extra_keys:
        raise UnsupportedFeatureError(
            f"Unsupported top-level JSON-LD keys: {sorted(extra_keys)}; "
            "only @context and @graph are supported"
        )
    graph = document.get("@graph")
    if not isinstance(graph, list):
        raise OntologyImportError("The document needs an @graph array")
    reader = _Reader(_read_context(document.get("@context", {})))
    return reader.read(graph)


def _read_context(context: Any) -> Dict[str, str]:
    """Read an inline @context made only of prefix mappings.

    Raises:
        UnsupportedFeatureError: For remote contexts, keywords such as
            ``@vocab``, or expanded term definitions.
        OntologyImportError: If the context is not an object.
    """
    if isinstance(context, (str, list)):
        raise UnsupportedFeatureError(
            "Remote or multiple @context values are unsupported; inline one "
            "object of prefix mappings"
        )
    if not isinstance(context, dict):
        raise OntologyImportError("@context must be an object")
    prefixes: Dict[str, str] = {}
    for key, value in context.items():
        if key.startswith("@"):
            raise UnsupportedFeatureError(
                f"@context keyword {key} is unsupported"
            )
        if not isinstance(value, str):
            raise UnsupportedFeatureError(
                f"@context term definition for {key!r} is unsupported; "
                "only prefix mappings are"
            )
        prefixes[key] = value
    return prefixes


def _as_list(value: Any) -> List[Any]:
    """Treat a JSON-LD value as a list of values."""
    return value if isinstance(value, list) else [value]


class _Node:
    """A graph node whose predicates are consumed as they are read."""

    def __init__(self, raw: Any, reader: "_Reader") -> None:
        if not isinstance(raw, dict):
            raise OntologyImportError(f"Graph entries must be objects: {raw!r}")
        raw_id = raw.get("@id")
        self.id: Optional[str] = (
            None if raw_id is None else reader.expand(raw_id)
        )
        self.types: Set[str] = {
            reader.expand(t) for t in _as_list(raw.get("@type", []))
        }
        self._values: Dict[str, List[Any]] = {}
        for key, value in raw.items():
            if key in ("@id", "@type"):
                continue
            if key.startswith("@"):
                raise UnsupportedFeatureError(
                    f"JSON-LD keyword {key} is unsupported on graph nodes"
                )
            self._values.setdefault(reader.expand(key), []).extend(
                _as_list(value)
            )

    @property
    def name(self) -> str:
        """Describe the node for error messages."""
        return self.id or "an anonymous node"

    def take(self, predicate: str) -> List[Any]:
        """Remove and return a predicate's values (empty if absent)."""
        return self._values.pop(predicate, [])

    def remaining(self) -> List[str]:
        """List predicates that have not been read."""
        return sorted(self._values)

    def finish(self) -> None:
        """Fail if any predicate was not understood.

        Raises:
            UnsupportedFeatureError: If unread predicates remain.
        """
        if self._values:
            raise UnsupportedFeatureError(
                f"Unsupported predicates on {self.name}: {self.remaining()}"
            )


class _Reader:
    """Reads graph nodes into release fields using one prefix map."""

    def __init__(self, prefixes: Dict[str, str]) -> None:
        self.prefixes = prefixes

    def expand(self, term: Any) -> str:
        """Expand a compact IRI; absolute IRIs and blank ids pass through.

        Raises:
            OntologyImportError: For non-strings and relative IRIs.
        """
        if not isinstance(term, str):
            raise OntologyImportError(f"Expected an IRI, got {term!r}")
        if term.startswith("_:"):
            return term
        prefix, colon, suffix = term.partition(":")
        if not colon:
            raise OntologyImportError(
                f"{term!r} is a relative IRI; use absolute or compact IRIs"
            )
        if not suffix.startswith("//") and prefix in self.prefixes:
            return self.prefixes[prefix] + suffix
        return term

    def read(self, graph: List[Any]) -> OntologyRelease:
        """Read every node of the graph into a validated release."""
        headers: List[Dict[str, Any]] = []
        classes: List[Dict[str, Any]] = []
        properties: List[Dict[str, Any]] = []
        shapes: List[Tuple[str, List[Dict[str, Any]], List[str]]] = []
        for raw in graph:
            node = _Node(raw, self)
            kind = self._kind(node)
            if kind == "ontology":
                headers.append(self._read_header(node))
            elif kind == "class":
                classes.append(self._read_class(node))
            elif kind == "shape":
                shapes.append(self._read_shape(node))
            else:
                properties.append(self._read_property(node, kind))
        if len(headers) != 1:
            raise OntologyImportError(
                f"Expected exactly one owl:Ontology node, found {len(headers)}"
            )
        self._attach_shapes(properties, shapes)
        fields = dict(headers[0], classes=classes, properties=properties)
        try:
            return OntologyRelease.model_validate(fields)
        except ValidationError as exc:
            raise OntologyImportError(
                f"The imported ontology is invalid: {exc}"
            ) from exc

    @staticmethod
    def _kind(node: _Node) -> str:
        """Classify a node by its single supported @type."""
        if not node.types:
            raise OntologyImportError(f"{node.name} has no @type")
        if len(node.types) != 1 or next(iter(node.types)) not in _NODE_KINDS:
            raise UnsupportedFeatureError(
                f"Unsupported node type(s) on {node.name}: "
                f"{sorted(node.types)}"
            )
        return _NODE_KINDS[next(iter(node.types))]

    def _read_header(self, node: _Node) -> Dict[str, Any]:
        """Read the owl:Ontology node."""
        if node.id is None or node.id.startswith("_:"):
            raise OntologyImportError("The owl:Ontology node needs an IRI")
        version = self._text(node.take(OWL_VERSION_INFO), "owl:versionInfo")
        title = self._text(node.take(RDFS_LABEL), "ontology rdfs:label")
        comments = node.take(RDFS_COMMENT)
        description = (
            self._text(comments, "ontology rdfs:comment") if comments else None
        )
        node.finish()
        return {
            "ontology_uri": node.id,
            "version": version,
            "title": title,
            "description": description,
        }

    def _read_class(self, node: _Node) -> Dict[str, Any]:
        """Read an owl:Class node."""
        uri = self._named(node)
        parents = [
            self._reference(value, f"rdfs:subClassOf of {uri}")
            for value in node.take(RDFS_SUBCLASS_OF)
        ]
        fields = {
            "uri": uri,
            "preferred_labels": self._language_map(
                node.take(RDFS_LABEL), f"rdfs:label of {uri}"
            ),
            "description": self._language_map(
                node.take(RDFS_COMMENT), f"rdfs:comment of {uri}"
            ),
            "parent_class_uris": [p for p in parents if p != OWL_THING],
            "identity_rules": [
                self._string(value, f"rf:identityRule of {uri}")
                for value in node.take(RF_IDENTITY_RULE)
            ],
            "status": self._status(node, uri),
        }
        node.finish()
        return fields

    def _read_property(self, node: _Node, kind: str) -> Dict[str, Any]:
        """Read an owl:ObjectProperty or owl:DatatypeProperty node."""
        uri = self._named(node)
        domain = node.take(RDFS_DOMAIN)
        ranges = node.take(RDFS_RANGE)
        inverse = node.take(OWL_INVERSE_OF)
        fields: Dict[str, Any] = {
            "uri": uri,
            "property_type": kind,
            "preferred_labels": self._language_map(
                node.take(RDFS_LABEL), f"rdfs:label of {uri}"
            ),
            "description": self._language_map(
                node.take(RDFS_COMMENT), f"rdfs:comment of {uri}"
            ),
            "domain_class_uris": (
                self._classes(domain, f"rdfs:domain of {uri}")
                if domain else []
            ),
            "inverse_property_uri": (
                self._reference(
                    self._single(inverse, f"owl:inverseOf of {uri}"),
                    f"owl:inverseOf of {uri}",
                )
                if inverse else None
            ),
            "temporal": self._boolean(
                node.take(RF_TEMPORAL), f"rf:temporal of {uri}", False
            ),
            "provenance_required": self._boolean(
                node.take(RF_PROVENANCE_REQUIRED),
                f"rf:provenanceRequired of {uri}",
                True,
            ),
            "status": self._status(node, uri),
        }
        if kind == "object":
            fields["range_class_uris"] = (
                self._classes(ranges, f"rdfs:range of {uri}")
                if ranges else []
            )
        else:
            fields["datatype"] = self._datatype(ranges, uri)
        node.finish()
        return fields

    def _read_shape(
        self, node: _Node
    ) -> Tuple[str, List[Dict[str, Any]], List[str]]:
        """Read a sh:PropertyShape into its path, constraints and classes."""
        path = self._reference(
            self._single(node.take(SH_PATH), "sh:path"), "sh:path"
        )
        for target in node.take(SH_TARGET_SUBJECTS_OF):
            if self._reference(target, "sh:targetSubjectsOf") != path:
                raise UnsupportedFeatureError(
                    f"The shape for {path} must target the subjects of "
                    "its own sh:path"
                )
        target_classes = [
            self._reference(target, "sh:targetClass")
            for target in node.take(SH_TARGET_CLASS)
        ]
        minimum = node.take(SH_MIN_COUNT)
        maximum = node.take(SH_MAX_COUNT)
        members = node.take(SH_IN)
        for predicate in node.remaining():
            if predicate.startswith(SH_NAMESPACE):
                raise UnsupportedConstraintError(predicate)
        node.finish()

        constraints: List[Dict[str, Any]] = []
        if minimum or maximum:
            constraints.append(
                {
                    "kind": "cardinality",
                    "min_count": (
                        self._count(minimum, f"sh:minCount of {path}")
                        if minimum else None
                    ),
                    "max_count": (
                        self._count(maximum, f"sh:maxCount of {path}")
                        if maximum else None
                    ),
                }
            )
        if members:
            constraints.append(
                {
                    "kind": "allowed_values",
                    "allowed_values": self._list_members(
                        members, f"sh:in of {path}"
                    ),
                }
            )
        return path, constraints, target_classes

    @staticmethod
    def _attach_shapes(
        properties: List[Dict[str, Any]],
        shapes: List[Tuple[str, List[Dict[str, Any]], List[str]]],
    ) -> None:
        """Move each shape's constraints onto the property it targets.

        Raises:
            OntologyImportError: For duplicate shapes or unknown paths.
            UnsupportedFeatureError: If ``sh:targetClass`` is not exactly
                the property's domain, given exactly when minCount > 0.
        """
        by_uri = {prop["uri"]: prop for prop in properties}
        seen: Set[str] = set()
        for path, constraints, target_classes in shapes:
            if path in seen:
                raise OntologyImportError(f"{path} has more than one shape")
            seen.add(path)
            if path not in by_uri:
                raise OntologyImportError(
                    f"sh:path {path} is not a property of this ontology"
                )
            required = any(
                c["kind"] == "cardinality" and c["min_count"]
                for c in constraints
            )
            domain = set(by_uri[path].get("domain_class_uris", []))
            if required != bool(target_classes) or (
                target_classes and set(target_classes) != domain
            ):
                raise UnsupportedFeatureError(
                    f"The shape for {path} must target the property's "
                    "domain with sh:targetClass exactly when sh:minCount "
                    "is above zero"
                )
            by_uri[path]["constraints"] = constraints

    # --- Value helpers ----------------------------------------------------

    @staticmethod
    def _named(node: _Node) -> str:
        """Return the IRI of a named term node.

        Raises:
            UnsupportedFeatureError: For anonymous terms.
        """
        if node.id is None or node.id.startswith("_:"):
            raise UnsupportedFeatureError(
                "Anonymous classes and properties are unsupported"
            )
        return node.id

    def _status(self, node: _Node, uri: str) -> str:
        """Read owl:deprecated into a term status."""
        deprecated = self._boolean(
            node.take(OWL_DEPRECATED), f"owl:deprecated of {uri}", False
        )
        return "deprecated" if deprecated else "draft"

    @staticmethod
    def _single(values: List[Any], what: str) -> Any:
        """Return the only value of a predicate."""
        if len(values) != 1:
            raise OntologyImportError(
                f"Expected exactly one {what}, found {len(values)}"
            )
        return values[0]

    @staticmethod
    def _literal(value: Any, what: str) -> Tuple[Any, Optional[str], str]:
        """Split a literal into (value, language, datatype-or-empty).

        Raises:
            OntologyImportError: If the value is not a literal.
            UnsupportedFeatureError: For value-object keys other than
                ``@value``, ``@language`` and ``@type``.
        """
        if isinstance(value, dict):
            if "@value" not in value:
                raise OntologyImportError(
                    f"{what}: expected a literal, got {value!r}"
                )
            extra = set(value) - {"@value", "@language", "@type"}
            if extra:
                raise UnsupportedFeatureError(
                    f"{what}: unsupported value keys {sorted(extra)}"
                )
            return value["@value"], value.get("@language"), value.get(
                "@type", ""
            )
        if isinstance(value, (str, int, float, bool)):
            return value, None, ""
        raise OntologyImportError(f"{what}: expected a literal, got {value!r}")

    def _string(self, value: Any, what: str) -> str:
        """Read a string literal."""
        text = self._literal(value, what)[0]
        if not isinstance(text, str):
            raise OntologyImportError(f"{what}: expected text, got {text!r}")
        return text

    def _text(self, values: List[Any], what: str) -> str:
        """Read the single string literal of a predicate."""
        return self._string(self._single(values, what), what)

    def _language_map(self, values: List[Any], what: str) -> Dict[str, str]:
        """Read language-tagged literals into a language-to-text map."""
        texts: Dict[str, str] = {}
        for value in values:
            text = self._string(value, what)
            language = self._literal(value, what)[1] or UNDETERMINED_LANGUAGE
            if language in texts:
                raise OntologyImportError(
                    f"{what}: more than one value for language {language!r}"
                )
            texts[language] = text
        return texts

    def _boolean(self, values: List[Any], what: str, default: bool) -> bool:
        """Read an optional boolean literal."""
        if not values:
            return default
        value, _, datatype = self._literal(self._single(values, what), what)
        if isinstance(value, bool):
            return value
        if (
            isinstance(value, str)
            and self.expand_or_empty(datatype) == XSD_BOOLEAN
            and value in ("true", "false", "1", "0")
        ):
            return value in ("true", "1")
        raise OntologyImportError(f"{what}: expected a boolean, got {value!r}")

    def _count(self, values: List[Any], what: str) -> int:
        """Read a non-boolean integer literal."""
        value, _, datatype = self._literal(self._single(values, what), what)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if (
            isinstance(value, str)
            and self.expand_or_empty(datatype) == XSD_INTEGER
            and value.lstrip("+-").isdigit()
        ):
            return int(value)
        raise OntologyImportError(f"{what}: expected an integer, got {value!r}")

    def expand_or_empty(self, term: str) -> str:
        """Expand a datatype IRI, keeping an empty string empty."""
        return self.expand(term) if term else ""

    def _reference(self, value: Any, what: str) -> str:
        """Read an IRI reference ``{"@id": ...}``.

        Raises:
            UnsupportedFeatureError: For anonymous class expressions or
                embedded node objects.
            OntologyImportError: For literals where an IRI is expected.
        """
        if not isinstance(value, dict):
            raise OntologyImportError(
                f'{what}: expected an IRI reference {{"@id": ...}}, '
                f"got {value!r}"
            )
        if "@id" not in value:
            raise UnsupportedFeatureError(
                f"{what}: anonymous class expressions are unsupported"
            )
        if set(value) != {"@id"}:
            raise UnsupportedFeatureError(
                f"{what}: embedded node objects are unsupported"
            )
        return self.expand(value["@id"])

    def _classes(self, values: List[Any], what: str) -> List[str]:
        """Read one class reference or an owl:unionOf of references."""
        if len(values) > 1:
            raise UnsupportedFeatureError(
                f"{what}: several values mean an intersection in RDFS; "
                "use owl:unionOf for 'any of'"
            )
        value = values[0]
        if isinstance(value, dict) and "@id" not in value:
            union = _Node(value, self)
            if union.types - {OWL_CLASS}:
                raise UnsupportedFeatureError(
                    f"{what}: unsupported class expression "
                    f"{sorted(union.types)}"
                )
            members = union.take(OWL_UNION_OF)
            if not members:
                raise UnsupportedFeatureError(
                    f"{what}: only owl:unionOf class expressions are "
                    "supported"
                )
            union.finish()
            items = self._single(members, f"owl:unionOf in {what}")
            if not isinstance(items, dict) or set(items) != {"@list"}:
                raise OntologyImportError(
                    f"{what}: owl:unionOf needs an @list"
                )
            return [self._reference(item, what) for item in items["@list"]]
        return [self._reference(value, what)]

    def _datatype(self, ranges: List[Any], uri: str) -> str:
        """Read the supported XSD datatype of a datatype property."""
        if not ranges:
            raise UnsupportedFeatureError(
                f"Datatype property {uri} has no rdfs:range; untyped "
                "literals are unsupported"
            )
        if len(ranges) > 1:
            raise UnsupportedFeatureError(
                f"rdfs:range of {uri}: several datatypes mean an "
                "intersection in RDFS and are unsupported"
            )
        datatype = self._reference(
            self._single(ranges, f"rdfs:range of {uri}"),
            f"rdfs:range of {uri}",
        )
        if datatype not in SUPPORTED_DATATYPES:
            raise UnsupportedFeatureError(
                f"Datatype {datatype} of {uri} is unsupported"
            )
        return datatype

    def _list_members(self, values: List[Any], what: str) -> List[str]:
        """Read an ``{"@list": [...]}`` of IRIs or literals as strings."""
        items = self._single(values, what)
        if not isinstance(items, dict) or set(items) != {"@list"}:
            raise OntologyImportError(f"{what}: expected an @list")
        members: List[str] = []
        for item in items["@list"]:
            if isinstance(item, dict) and "@id" in item:
                members.append(self._reference(item, what))
                continue
            value = self._literal(item, what)[0]
            if isinstance(value, bool):
                members.append("true" if value else "false")
            else:
                members.append(str(value))
        return members


# --- Turtle export --------------------------------------------------------

# A conservative subset of Turtle's PN_LOCAL that never needs escaping;
# other local names are written as full <IRI>s.
_LOCAL_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")
_TURTLE_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}
_STATEMENT_SEPARATOR = " ;\n    "
_INLINE_SEPARATOR = " ; "


def export_turtle(release: OntologyRelease) -> str:
    """Export a release as Turtle.

    The ontology namespace (the ontology IRI, plus ``#`` unless it already
    ends in ``#`` or ``/``) becomes the empty prefix. Output is
    deterministic: equal releases give identical text.

    Args:
        release: Release to export.

    Returns:
        UTF-8 Turtle text ending in a newline.
    """
    namespace = _default_namespace(release.ontology_uri)
    writer = _TurtleWriter(namespace)
    lines = [
        f"@prefix {prefix}: <{iri}> ."
        for prefix, iri in sorted(PREFIXES.items())
    ]
    lines.append(f"@prefix : <{namespace}> .")
    for node in export_jsonld(release)["@graph"]:
        lines.extend(["", writer.statement(node)])
    return "\n".join(lines) + "\n"


def _default_namespace(ontology_uri: str) -> str:
    """Derive the namespace used for the empty Turtle prefix."""
    if ontology_uri.endswith(("#", "/")):
        return ontology_uri
    return ontology_uri + "#"


def _turtle_string(text: str) -> str:
    """Quote a string as a Turtle literal, escaping as needed."""
    escaped = []
    for char in text:
        if char in _TURTLE_ESCAPES:
            escaped.append(_TURTLE_ESCAPES[char])
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            escaped.append(f"\\u{ord(char):04X}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


class _TurtleWriter:
    """Renders exported JSON-LD nodes as Turtle statements."""

    def __init__(self, namespace: str) -> None:
        self._namespaces = [(namespace, "")] + [
            (iri, prefix) for prefix, iri in PREFIXES.items()
        ]

    def statement(self, node: Dict[str, Any]) -> str:
        """Render a top-level node, using ``[]`` for anonymous subjects."""
        subject = self.iri(node["@id"]) if "@id" in node else "[]"
        return f"{subject} {self._predicates(node, _STATEMENT_SEPARATOR)} ."

    def iri(self, iri: str) -> str:
        """Write an IRI as a prefixed name when that is safe."""
        for namespace, prefix in self._namespaces:
            if iri.startswith(namespace):
                local_name = iri[len(namespace):]
                if _LOCAL_NAME_PATTERN.match(local_name):
                    return f"{prefix}:{local_name}"
        return f"<{iri}>"

    def _predicates(self, node: Dict[str, Any], separator: str) -> str:
        """Render a node's predicate-object list."""
        parts = []
        for key, value in node.items():
            if key == "@id":
                continue
            if key == "@type":
                parts.append(f"a {value}")
            else:
                parts.append(f"{key} {self._objects(value)}")
        return separator.join(parts)

    def _objects(self, value: Any) -> str:
        """Render one value or a comma-separated list of values."""
        values = value if isinstance(value, list) else [value]
        return ", ".join(self._object(item) for item in values)

    def _object(self, value: Any) -> str:
        """Render a literal, IRI reference, RDF list or blank node."""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            return _turtle_string(value)
        if "@list" in value:
            items = " ".join(self._object(item) for item in value["@list"])
            return f"( {items} )"
        if "@value" in value:
            text = _turtle_string(value["@value"])
            if "@language" in value:
                return f"{text}@{value['@language']}"
            return f"{text}^^{value['@type']}"
        if set(value) == {"@id"}:
            return self.iri(value["@id"])
        return f"[ {self._predicates(value, _INLINE_SEPARATOR)} ]"
