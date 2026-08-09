"""Canonical document parsing domain models."""

import uuid
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class DocumentElement(BaseModel):
    """Canonical document element representation."""

    element_id: uuid.UUID = Field(
        default_factory=uuid.uuid4, description="Unique element UUID"
    )
    element_type: str = Field(
        description="Type (heading, paragraph, table, list_item, figure)"
    )
    sequence_number: int = Field(
        description="Sequential position of element in document"
    )
    text: str = Field(description="Plain text content")
    markdown: Optional[str] = Field(
        default=None, description="Formatted markdown representation"
    )
    page_number: Optional[int] = Field(
        default=None, description="1-based page number"
    )
    bounding_box: Optional[Tuple[float, float, float, float]] = Field(
        default=None, description="Normalized bounding box (x0, y0, x1, y1)"
    )
    parent_element_id: Optional[uuid.UUID] = Field(
        default=None, description="Parent element UUID for hierarchy"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Custom element metadata"
    )


class CanonicalDocument(BaseModel):
    """Canonical parsed document output model."""

    document_id: uuid.UUID = Field(
        default_factory=uuid.uuid4, description="Canonical document UUID"
    )
    title: Optional[str] = Field(
        default=None, description="Document title if inferred or extracted"
    )
    mime_type: str = Field(description="Source document MIME type")
    page_count: Optional[int] = Field(
        default=None, description="Total page count"
    )
    elements: List[DocumentElement] = Field(
        default_factory=list, description="Ordered document elements"
    )
    raw_markdown: str = Field(
        default="", description="Full aggregated markdown document text"
    )
    parser_name: str = Field(description="Name of parser provider used")
    parser_version: str = Field(description="Version of parser provider used")
