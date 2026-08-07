"""Metadata Registry & Validation Service for RAG Foundry governance plane."""

from typing import Any, Dict, List, Optional, Tuple

import jsonschema
from pydantic import BaseModel, Field


class RegisteredSchema(BaseModel):
    """Registered metadata schema entry."""

    name: str = Field(description="Schema identifier")
    version: str = Field(description="Semantic version string")
    schema_definition: Dict[str, Any] = Field(
        description="JSON Schema draft-2020-12 definition"
    )
    description: Optional[str] = Field(
        default=None, description="Human-readable schema description"
    )


class ValidationResult(BaseModel):
    """Result of validating metadata against a registered schema."""

    is_valid: bool = Field(description="True if validation passed")
    errors: List[str] = Field(
        default_factory=list, description="List of validation error messages"
    )
    validated_data: Optional[Dict[str, Any]] = Field(
        default=None, description="Validated metadata dictionary"
    )


class MetadataRegistry:
    """Registry for managing versioned metadata schemas and validation."""

    def __init__(self) -> None:
        self._schemas: Dict[Tuple[str, str], RegisteredSchema] = {}

    def register_schema(
        self,
        name: str,
        version: str,
        schema_definition: Dict[str, Any],
        description: Optional[str] = None,
    ) -> RegisteredSchema:
        """Register a new versioned metadata schema.

        Args:
            name: Unique name identifier of the schema.
            version: Semantic version (e.g. '1.0.0').
            schema_definition: JSON Schema definition dictionary.
            description: Optional description.

        Returns:
            RegisteredSchema object.

        Raises:
            ValueError: If schema version is already registered or schema
                is invalid.
        """
        key = (name, version)
        if key in self._schemas:
            raise ValueError(
                f"Schema '{name}' version '{version}' is already registered."
            )

        # Validate schema format
        try:
            jsonschema.Draft202012Validator.check_schema(schema_definition)
        except jsonschema.exceptions.SchemaError as e:
            raise ValueError(f"Invalid JSON Schema definition: {e.message}")

        entry = RegisteredSchema(
            name=name,
            version=version,
            schema_definition=schema_definition,
            description=description,
        )
        self._schemas[key] = entry
        return entry

    def get_schema(
        self, name: str, version: str
    ) -> Optional[RegisteredSchema]:
        """Retrieve a registered schema by name and version.

        Args:
            name: Schema name.
            version: Schema version.

        Returns:
            RegisteredSchema if found, otherwise None.
        """
        return self._schemas.get((name, version))

    def list_versions(self, name: str) -> List[str]:
        """List all registered version strings for a schema name.

        Args:
            name: Schema name.

        Returns:
            Sorted list of version strings.
        """
        versions = [v for n, v in self._schemas.keys() if n == name]
        return sorted(versions)

    def validate(
        self, name: str, version: str, data: Dict[str, Any]
    ) -> ValidationResult:
        """Validate metadata dictionary against a registered schema version.

        Args:
            name: Schema name.
            version: Schema version.
            data: Metadata dictionary to validate.

        Returns:
            ValidationResult containing status, errors, and validated data.

        Raises:
            ValueError: If schema is not registered.
        """
        schema = self.get_schema(name, version)
        if schema is None:
            raise ValueError(
                f"Schema '{name}' version '{version}' is not registered."
            )

        validator = jsonschema.Draft202012Validator(schema.schema_definition)
        errors = [err.message for err in validator.iter_errors(data)]

        if errors:
            return ValidationResult(
                is_valid=False, errors=errors, validated_data=None
            )

        return ValidationResult(
            is_valid=True, errors=[], validated_data=data
        )
