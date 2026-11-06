# Ontology Representation and Supported Constraint Subset

This document states exactly which ontology semantics RAG Foundry implements.
[ADR-0011](../adr/0011-ontology-representation-constraints-and-versioning.md)
requires the supported subset to be documented and tested, and anything outside
it to fail explicitly rather than be ignored. Everything here is enforced by the
code in `src/rag_foundry/ontology/` and covered by `tests/test_ontology_*.py`.

## 1. Releases and terms

An ontology is published as **releases**. A release has an ontology IRI, a
version that is unique per ontology, a title, and a set of classes and
properties.

| Release status | Meaning | Allowed changes |
| --- | --- | --- |
| `draft` | Being edited | Add terms, deprecate terms, publish |
| `approved` | Published; immutable | Deprecate the release, derive a new draft |
| `deprecated` | Retired | Derive a new draft |

- Every edit to a draft revalidates the whole release, so a stored draft is
  always internally consistent. Terms are therefore added in dependency order:
  parent classes before subclasses, classes before the properties that use
  them, and an inverse property before the property that names it.
- Publishing turns `draft` terms into `approved` terms. `deprecated` terms stay
  deprecated.
- `create_draft_from` copies a published release into a new draft linked by
  `previous_release_id`. Term IRIs stay the same across releases; only the
  pair (release, IRI) is unique.

### Identifiers and labels

- Terms are identified by **absolute IRIs**: a scheme, a colon, and no
  whitespace, control characters or `<>"{}|\^` characters. Relative IRIs are
  refused.
- Labels and descriptions are maps from a **BCP 47 language tag** to text,
  such as `en`, `id`, `en-US` or `zh-Hant-TW`. Every term needs at least one
  preferred label. On import, an untagged label is stored under `und`
  ("undetermined").

## 2. Classes and properties

| Model field | Meaning |
| --- | --- |
| `OntologyClass.parent_class_uris` | Direct superclasses (`rdfs:subClassOf`). The hierarchy must be acyclic, and every parent must be defined in the same release. |
| `OntologyClass.identity_rules` | Free-text rules for deciding when two entities of the class are the same, for entity resolution ([ADR-0012](../adr/0012-entity-identity-merge-split-and-resolution.md)). |
| `OntologyProperty.property_type` | `object` (links two entities) or `data` (links an entity to a literal). |
| `OntologyProperty.domain_class_uris` | Classes a subject may belong to. **Empty means any class.** |
| `OntologyProperty.range_class_uris` | Object properties only: classes an object may belong to. **Empty means any class.** |
| `OntologyProperty.datatype` | Data properties only, and required: one supported XSD datatype (§4). |
| `OntologyProperty.inverse_property_uri` | Object properties only: `owl:inverseOf`. Declaring it on one side is enough, because the relation is symmetric. |
| `OntologyProperty.temporal` | The value holds for a time interval; assertions record `valid_from`/`valid_to` (ARCHITECTURE.md §8.7). |
| `OntologyProperty.provenance_required` | Assertions using the property must cite evidence. Defaults to `true`. |

### Domain and range semantics

- **Several domain or range classes mean "any of".** A subject satisfies the
  domain if its class is, or descends from, *at least one* listed class. Range
  works the same way for objects.
- **Subclasses count.** `rdfs:subClassOf` is applied transitively, so a `Bank`
  that is a subclass of `Organization` satisfies a domain of `Organization`.
- Plain RDFS reads several `rdfs:domain` values as an **intersection**. To
  stay faithful, "any of" is exported as `owl:unionOf`, and an imported
  document that repeats `rdfs:domain` or `rdfs:range` is refused (§5).

## 3. Constraints

Each property carries at most one constraint of each kind. Any other kind
raises `UnsupportedConstraintError`, both when a model is built or imported and
when a validator is created.

| Kind | Fields | SHACL equivalent | Rules |
| --- | --- | --- | --- |
| `cardinality` | `min_count`, `max_count` | `sh:minCount`, `sh:maxCount` | At least one bound is set; bounds are non-negative; `min_count ≤ max_count`. A `min_count` above zero needs a non-empty domain. Counted per subject and property. |
| `allowed_values` | `allowed_values` | `sh:in` | The list is non-empty with no duplicates. Object properties list entity IRIs. Data properties list lexical forms that must be valid for the property's datatype. |

Constraints apply to every subject of the property, the way SHACL's
`sh:targetSubjectsOf` does. A `min_count` above zero also applies to every
instance of the property's domain classes (including subclasses): an
`Organization` without a required `foundedOn` violates it. The exported shape
expresses this with `sh:targetClass` for each domain class, next to
`sh:targetSubjectsOf`. Node shapes (`sh:NodeShape`), other targets and all
other SHACL components are not supported.

## 4. Datatypes

| Datatype | Accepted lexical forms | Canonical form for comparison |
| --- | --- | --- |
| `xsd:string` | Any text, including the empty string | As written |
| `xsd:integer` | `[+-]?[0-9]+` | No sign for positive values, no leading zeros (`+02` → `2`) |
| `xsd:decimal` | `[+-]?(digits[.digits?] \| .digits)`; no exponent | No trailing zeros (`1.50` → `1.5`, `100` stays `100`) |
| `xsd:boolean` | `true`, `false`, `1`, `0` | `true` / `false` |
| `xsd:date` | `YYYY-MM-DD` with an optional `Z` or `±hh:mm` (hours ≤ 14); must be a real calendar date | As written |
| `xsd:dateTime` | `YYYY-MM-DDThh:mm:ss[.fraction]` with an optional timezone; must be a real date and time | As written |

The validator converts Python values to lexical forms before checking them:
`bool` becomes `true`/`false`, `Decimal` is written without an exponent, and
`date`/`datetime` use ISO 8601. So `True` is **not** a valid `xsd:integer`, and
a `datetime` is not a valid `xsd:date`. Years must have four digits.

## 5. Interchange (JSON-LD import and export, Turtle export)

`export_jsonld`, `import_jsonld` and `export_turtle` live in
`ontology/serialization.py`. Turtle is rendered from the JSON-LD export, so both
formats always state the same triples.

| Model | Vocabulary |
| --- | --- |
| Release | `owl:Ontology` with `owl:versionInfo` (version), `rdfs:label` (title) and `rdfs:comment` (description) |
| Class | `owl:Class`, `rdfs:label`, `rdfs:comment`, `rdfs:subClassOf`, `owl:deprecated true` |
| Object or data property | `owl:ObjectProperty` / `owl:DatatypeProperty`, `rdfs:domain`, `rdfs:range`, `owl:inverseOf`, `owl:deprecated true` |
| Several domain or range classes | `[ a owl:Class ; owl:unionOf ( … ) ]` |
| Constraints | One `sh:PropertyShape` per property, with `sh:path`, `sh:targetSubjectsOf`, `sh:minCount`, `sh:maxCount` and `sh:in`; when `sh:minCount` is above zero, also `sh:targetClass` for each domain class |
| Identity rules, `temporal`, `provenance_required` | `rf:identityRule`, `rf:temporal`, `rf:provenanceRequired`, where `rf:` is `urn:rag-foundry:vocab#` |

Export is deterministic: nodes are ordered ontology, classes, properties, then
shapes, and each group is sorted by IRI. In Turtle, the ontology namespace (its
IRI plus `#`, unless it already ends in `#` or `/`) becomes the empty prefix.

Import is **closed-world**:

- **Accepted input:** a JSON object with an inline `@context` made only of prefix
  mappings, and an `@graph` containing exactly one `owl:Ontology` node.
- **Imported status:** every imported release and term is a `draft` unless
  marked `owl:deprecated`. Approval is not part of the format; it happens
  through the registry.
- **`rdfs:subClassOf owl:Thing`** is implied, so it is dropped.
- **Ordering:** the order of repeated values (labels, parents, identity rules)
  carries no meaning in RDF. Constraints are always kept in the order
  cardinality, then allowed values.

### What fails explicitly

| Input | Error |
| --- | --- |
| Remote or multiple `@context`, `@vocab`, `@base`, expanded term definitions, top-level `@id`, `@reverse` and other JSON-LD keywords | `UnsupportedFeatureError` |
| Node types other than the five above, e.g. `owl:NamedIndividual`, `sh:NodeShape`, `owl:FunctionalProperty` | `UnsupportedFeatureError` |
| Predicates outside the mapping, e.g. `owl:equivalentClass`, `owl:imports`, `owl:versionIRI`, `dcterms:*` | `UnsupportedFeatureError` |
| Anonymous classes or class expressions other than `owl:unionOf`, e.g. `owl:Restriction`, `owl:intersectionOf` | `UnsupportedFeatureError` |
| Repeated `rdfs:domain` or `rdfs:range` values (RDFS intersection) | `UnsupportedFeatureError` |
| Datatype properties without `rdfs:range`, or with a datatype not in §4 | `UnsupportedFeatureError` |
| A shape whose `sh:targetSubjectsOf` differs from its `sh:path` | `UnsupportedFeatureError` |
| A shape whose `sh:targetClass` set is not exactly the property's domain, or that has `sh:targetClass` without `sh:minCount` above zero (or the reverse) | `UnsupportedFeatureError` |
| SHACL constraint components other than `sh:minCount`, `sh:maxCount` and `sh:in`, e.g. `sh:pattern`, `sh:datatype`, `sh:class` | `UnsupportedConstraintError` (a subclass of `UnsupportedFeatureError`) |
| Structural problems: missing `@graph`, zero or several ontology nodes, a missing version or title, relative IRIs, literals where IRIs are expected, two labels in one language, shapes for unknown properties, two shapes for one property, an inconsistent release | `OntologyImportError` |

## 6. Validating statements

`ConstraintValidator(release)` in `ontology/constraints.py` validates against
one pinned release:

- `check_statement(statement)` checks terms, domain, range, value kind,
  datatype and allowed values for one statement.
- `check_cardinality(subject, class, property, count)` checks `min_count` and
  `max_count`.
- `validate(statements, subjects=None)` runs both over a set of statements.
  `subjects` lists extra subjects that must satisfy `min_count` even with no
  statements. Deprecated properties are never required. The result is a
  `ConstraintReport` naming the release id and version, with its violations
  sorted.

| Violation rule | Raised when |
| --- | --- |
| `unknown_class` | A subject or object class is not defined in the release |
| `unknown_property` | The property is not defined in the release |
| `deprecated_term` | A statement uses a deprecated property, or a subject or object of a deprecated class |
| `domain` / `range` | The subject or object class is not in the domain or range (§2) |
| `value_kind` | An object property was given a literal or no object, or a data property was given an entity or no literal |
| `datatype` | A literal is outside its datatype's lexical space (§4) |
| `allowed_values` | A value is not among the allowed values (compared in canonical form), or an object property with allowed values has no object IRI |
| `min_count` / `max_count` | A subject has too few or too many values for a property |

## 7. Not supported

The following are deliberately out of scope. Requesting any of them fails
instead of being approximated:

- OWL reasoning beyond transitive `rdfs:subClassOf`: no equivalence,
  disjointness, property chains or characteristics, restrictions or
  individuals.
- SHACL beyond the components in §3: no node shapes, SPARQL constraints,
  paths other than a single property, or severities.
- Datatypes other than the six in §4.
- Turtle **import**. Turtle is export-only.
