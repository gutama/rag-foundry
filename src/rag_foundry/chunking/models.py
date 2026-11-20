"""Domain models for structure-aware document chunking (ADR-0002)."""

import hashlib
import uuid
from typing import Any, Dict, List

from pydantic import BaseModel, Field, model_validator

from rag_foundry.retrieval.models import BoundingBox


def compute_chunk_checksum(section_path: List[str], text: str) -> str:
    """Compute a deterministic SHA-256 checksum for a chunk's section and text.

    Args:
        section_path: Hierarchical section headings leading to this chunk.
        text: Chunk text content.

    Returns:
        64-character lowercase hexadecimal SHA-256 digest.
    """
    payload = f"{'|'.join(section_path)}\n{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ChunkingConfig(BaseModel):
    """Configuration controlling structural chunk sizing and overlap."""

    target_chars: int = Field(
        default=1000,
        ge=1,
        description="Preferred character budget for packed prose chunks.",
    )
    max_chars: int = Field(
        default=1500,
        ge=1,
        description="Hard upper character limit for a single emitted chunk.",
    )
    overlap_chars: int = Field(
        default=150,
        ge=0,
        description="Character overlap carried between consecutive prose chunks.",
    )
    include_heading_in_text: bool = Field(
        default=False,
        description="Whether to prepend the active section heading to chunk text.",
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> "ChunkingConfig":
        """Ensure target_chars <= max_chars and overlap_chars < max_chars.

        Returns:
            Validated ChunkingConfig instance.

        Raises:
            ValueError: If size or overlap constraints are violated.
        """
        if self.target_chars > self.max_chars:
            raise ValueError("target_chars must be <= max_chars")
        if self.overlap_chars >= self.max_chars:
            raise ValueError("overlap_chars must be < max_chars")
        return self


class DocumentChunk(BaseModel):
    """Deterministic structural chunk emitted from a CanonicalDocument."""

    chunk_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique chunk identifier.",
    )
    chunk_index: int = Field(
        ge=0,
        description="Zero-based sequential index of this chunk in the document.",
    )
    text: str = Field(
        min_length=1,
        description="Chunk text content.",
    )
    section_path: List[str] = Field(
        default_factory=list,
        description="Ordered hierarchical heading path for this chunk.",
    )
    page_numbers: List[int] = Field(
        default_factory=list,
        description="Sorted unique 1-based page numbers covered by this chunk.",
    )
    bounding_boxes: List[BoundingBox] = Field(
        default_factory=list,
        description="Normalized page-coordinate bounding boxes for citations.",
    )
    element_ids: List[uuid.UUID] = Field(
        default_factory=list,
        description="Ordered canonical element UUIDs contributing to this chunk.",
    )
    element_types: List[str] = Field(
        default_factory=list,
        description="Unique contributing element types in order of appearance.",
    )
    checksum: str = Field(
        min_length=64,
        max_length=64,
        description="Deterministic SHA-256 hex digest of section_path and text.",
    )
    chunker_name: str = Field(
        description="Identifier of the chunker implementation.",
    )
    chunker_version: str = Field(
        description="Semantic version of the chunker implementation.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional chunk-level structural metadata.",
    )
