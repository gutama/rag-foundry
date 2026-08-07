"""Unit tests for Pydantic v2 MetadataRegistry and Validation Service."""

import pytest
from pydantic import ValidationError


def test_metadata_registry_register_and_get_schema():
    """Test registering a metadata schema and retrieving it by name and version."""
    from rag_foundry.metadata.registry import MetadataRegistry

    registry = MetadataRegistry()
    schema_definition = {
        "title": "DocumentMetadata",
        "type": "object",
        "properties": {
            "author": {"type": "string"},
            "classification_level": {
                "type": "string",
                "enum": ["public", "internal", "restricted", "confidential"],
            },
            "document_date": {"type": "string", "format": "date"},
        },
        "required": ["author", "classification_level"],
    }

    registry.register_schema(
        name="institutional_doc",
        version="1.0.0",
        schema_definition=schema_definition,
        description="Standard institutional document metadata schema",
    )

    registered = registry.get_schema(name="institutional_doc", version="1.0.0")
    assert registered is not None
    assert registered.name == "institutional_doc"
    assert registered.version == "1.0.0"
    assert "author" in registered.schema_definition["properties"]


def test_metadata_registry_duplicate_registration_raises():
    """Test registering the same schema version twice raises an error."""
    from rag_foundry.metadata.registry import MetadataRegistry

    registry = MetadataRegistry()
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}

    registry.register_schema("doc", "1.0.0", schema)

    with pytest.raises(ValueError, match="already registered"):
        registry.register_schema("doc", "1.0.0", schema)


def test_metadata_registry_validate_valid_data():
    """Test validating valid metadata against a registered schema passes."""
    from rag_foundry.metadata.registry import MetadataRegistry

    registry = MetadataRegistry()
    schema_definition = {
        "type": "object",
        "properties": {
            "author": {"type": "string"},
            "page_count": {"type": "integer", "minimum": 1},
        },
        "required": ["author"],
    }
    registry.register_schema("doc", "1.0.0", schema_definition)

    valid_metadata = {"author": "Jane Doe", "page_count": 10}
    result = registry.validate(
        name="doc", version="1.0.0", data=valid_metadata
    )

    assert result.is_valid is True
    assert len(result.errors) == 0
    assert result.validated_data["author"] == "Jane Doe"


def test_metadata_registry_validate_invalid_data():
    """Test validating metadata with missing required field or wrong type fails."""
    from rag_foundry.metadata.registry import MetadataRegistry

    registry = MetadataRegistry()
    schema_definition = {
        "type": "object",
        "properties": {
            "author": {"type": "string"},
            "page_count": {"type": "integer", "minimum": 1},
        },
        "required": ["author"],
    }
    registry.register_schema("doc", "1.0.0", schema_definition)

    invalid_metadata = {"page_count": -5}  # Missing author, invalid page_count
    result = registry.validate(
        name="doc", version="1.0.0", data=invalid_metadata
    )

    assert result.is_valid is False
    assert len(result.errors) >= 1


def test_metadata_registry_list_versions():
    """Test listing available versions for a schema."""
    from rag_foundry.metadata.registry import MetadataRegistry

    registry = MetadataRegistry()
    schema = {"type": "object", "properties": {}}
    registry.register_schema("policy", "1.0.0", schema)
    registry.register_schema("policy", "1.1.0", schema)
    registry.register_schema("policy", "2.0.0", schema)

    versions = registry.list_versions("policy")
    assert versions == ["1.0.0", "1.1.0", "2.0.0"]
