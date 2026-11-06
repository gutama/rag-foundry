"""Unit tests for entity and mention domain models (ADR-0012, §8.6)."""

import uuid

import pytest
from pydantic import ValidationError

from rag_foundry.entities import models

EX = "http://example.org/finance#"
WORKSPACE = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
PROFILE = uuid.UUID("00000000-0000-4000-8000-0000000000bb")


def _entity(**kwargs):
    """Build an entity with sensible defaults."""
    fields = {
        "workspace_id": WORKSPACE,
        "semantic_profile_id": PROFILE,
        "canonical_uri": "http://id.example.org/entity/bca",
        "ontology_class_uri": EX + "Bank",
        "preferred_labels": {"en": "Bank Central Asia"},
    }
    fields.update(kwargs)
    return models.Entity(**fields)


def _mention(**kwargs):
    """Build a mention with sensible defaults."""
    fields = {
        "workspace_id": WORKSPACE,
        "semantic_profile_id": PROFILE,
        "chunk_id": uuid.uuid4(),
        "start_offset": 10,
        "end_offset": 13,
        "surface_text": "BCA",
    }
    fields.update(kwargs)
    return models.Mention(**fields)


# --- Entity ---------------------------------------------------------------


def test_entity_defaults():
    """A new entity is active with no aliases, identifiers or redirect."""
    entity = _entity()
    assert entity.status == "active"
    assert entity.aliases == {}
    assert entity.identifiers == {}
    assert entity.merged_into_id is None
    assert isinstance(entity.id, uuid.UUID)
    assert entity.created_at.tzinfo is not None


@pytest.mark.parametrize("field", ["canonical_uri", "ontology_class_uri"])
def test_entity_iris_are_validated(field):
    """Canonical and class IRIs must be absolute IRIs."""
    with pytest.raises(ValidationError):
        _entity(**{field: "not an iri"})


def test_entity_labels_follow_ontology_rules():
    """Labels need at least one entry and BCP 47 tags."""
    with pytest.raises(ValidationError):
        _entity(preferred_labels={})
    with pytest.raises(ValidationError):
        _entity(preferred_labels={"en_US": "BCA"})


def test_entity_aliases():
    """Aliases are grouped by language tag."""
    entity = _entity(
        aliases={"en": ["BCA", "Bank BCA"], "id": ["PT Bank Central Asia"]}
    )
    assert entity.aliases["en"] == ["BCA", "Bank BCA"]


@pytest.mark.parametrize(
    "aliases",
    [
        {"en_US": ["BCA"]},
        {"en": [" "]},
        {"en": ["BCA", "BCA"]},
    ],
)
def test_entity_rejects_malformed_aliases(aliases):
    """Alias tags must be BCP 47; aliases non-blank and unique."""
    with pytest.raises(ValidationError):
        _entity(aliases=aliases)


def test_entity_identifiers():
    """Identifiers map a typed scheme to one value."""
    entity = _entity(
        identifiers={"lei": "5493001KJTIIGC8Y1R12", "swift_bic": "CENAIDJA"}
    )
    assert entity.identifiers["swift_bic"] == "CENAIDJA"


@pytest.mark.parametrize(
    "identifiers",
    [
        {"LEI": "X"},
        {"has space": "X"},
        {"": "X"},
        {"lei": ""},
        {"lei": "  "},
        {"lei": " padded "},
        {"lei": "X" * 257},
    ],
)
def test_entity_rejects_malformed_identifiers(identifiers):
    """Schemes are lowercase tokens; values are non-blank and trimmed."""
    with pytest.raises(ValidationError):
        _entity(identifiers=identifiers)


def test_entity_status_values_are_enforced():
    """Only the four documented statuses are allowed."""
    for status in ("active", "split", "deprecated"):
        assert _entity(status=status).status == status
    with pytest.raises(ValidationError):
        _entity(status="retired")


def test_merged_entities_need_a_redirect():
    """'merged' and merged_into_id always go together."""
    survivor = uuid.uuid4()
    merged = _entity(status="merged", merged_into_id=survivor)
    assert merged.merged_into_id == survivor
    with pytest.raises(ValidationError):
        _entity(status="merged")
    with pytest.raises(ValidationError):
        _entity(status="active", merged_into_id=survivor)


def test_entity_cannot_redirect_to_itself():
    """An entity cannot be merged into itself."""
    entity_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        _entity(id=entity_id, status="merged", merged_into_id=entity_id)


def test_entity_all_labels():
    """all_labels lists preferred labels then aliases, without repeats."""
    entity = _entity(
        preferred_labels={"en": "Bank Central Asia", "id": "BCA"},
        aliases={"en": ["BCA", "Bank BCA"]},
    )
    assert entity.all_labels() == ["Bank Central Asia", "BCA", "Bank BCA"]


# --- Mention --------------------------------------------------------------


def test_mention_defaults():
    """A new mention is unresolved."""
    mention = _mention()
    assert mention.resolution_status == "unresolved"
    assert mention.resolved_entity_id is None
    assert mention.ontology_class_uri is None
    assert mention.identifiers == {}


@pytest.mark.parametrize(
    "start, end", [(-1, 3), (5, 5), (6, 5)]
)
def test_mention_offsets(start, end):
    """Offsets are non-negative and the span is not empty."""
    with pytest.raises(ValidationError):
        _mention(start_offset=start, end_offset=end)


def test_mention_text_and_class_are_validated():
    """Surface text cannot be blank; the class hint must be an IRI."""
    with pytest.raises(ValidationError):
        _mention(surface_text="   ")
    with pytest.raises(ValidationError):
        _mention(ontology_class_uri="Bank")
    assert _mention(ontology_class_uri=EX + "Bank").ontology_class_uri


def test_mention_identifiers_are_validated():
    """Extracted identifier hints follow the entity identifier rules."""
    assert _mention(identifiers={"lei": "X1"}).identifiers == {"lei": "X1"}
    with pytest.raises(ValidationError):
        _mention(identifiers={"LEI": "X1"})


def test_mention_resolution_status():
    """'resolved' and resolved_entity_id always go together."""
    entity_id = uuid.uuid4()
    resolved = _mention(
        resolution_status="resolved", resolved_entity_id=entity_id
    )
    assert resolved.resolved_entity_id == entity_id
    assert _mention(resolution_status="candidate").resolved_entity_id is None
    with pytest.raises(ValidationError):
        _mention(resolution_status="resolved")
    with pytest.raises(ValidationError):
        _mention(resolution_status="candidate", resolved_entity_id=entity_id)
    with pytest.raises(ValidationError):
        _mention(resolution_status="linked")
