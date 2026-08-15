"""Retrieval domain models, query specifications, and evidence containers."""

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class BoundingBox(BaseModel):
    """Normalized page-coordinate bounding box for deep document citations."""

    page: int = Field(ge=1, description="Page number (1-indexed)")
    l: float = Field(ge=0.0, le=1.0, description="Left coordinate (normalized 0-1)")
    t: float = Field(ge=0.0, le=1.0, description="Top coordinate (normalized 0-1)")
    r: float = Field(ge=0.0, le=1.0, description="Right coordinate (normalized 0-1)")
    b: float = Field(ge=0.0, le=1.0, description="Bottom coordinate (normalized 0-1)")

    @field_validator("r")
    @classmethod
    def validate_right_ge_left(cls, v: float, info: Any) -> float:
        """Ensure right coordinate is greater than or equal to left coordinate."""
        if "l" in info.data and v < info.data["l"]:
            raise ValueError("Right coordinate must be >= left coordinate")
        return v

    @field_validator("b")
    @classmethod
    def validate_bottom_ge_top(cls, v: float, info: Any) -> float:
        """Ensure bottom coordinate is greater than or equal to top coordinate."""
        if "t" in info.data and v < info.data["t"]:
            raise ValueError("Bottom coordinate must be >= top coordinate")
        return v


class RetrievalFilter(BaseModel):
    """Filter predicates enforced prior to and during retrieval execution."""

    workspace_id: uuid.UUID = Field(
        description="Target workspace identifier for strict tenant isolation"
    )
    document_ids: Optional[List[uuid.UUID]] = Field(
        default=None, description="Optional document version ID whitelist"
    )
    metadata_filters: Dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary metadata key-value constraints"
    )
    security_domains: List[str] = Field(
        default_factory=list,
        description="Allowed security domain tags (e.g. ['finance', 'public'])",
    )


class RetrievalQuery(BaseModel):
    """Specification of a retrieval request across hybrid search pipelines."""

    query_text: str = Field(min_length=1, description="Search query string")
    filter: RetrievalFilter = Field(
        description="Workspace and security filter criteria"
    )
    top_k: int = Field(default=10, ge=1, le=100, description="Number of results to retrieve")
    enable_lexical: bool = Field(
        default=True, description="Whether to execute PostgreSQL Full-Text Search"
    )
    enable_dense: bool = Field(
        default=True, description="Whether to execute pgvector dense semantic search"
    )
    enable_graph: bool = Field(
        default=False, description="Whether to execute Graph-enhanced retrieval"
    )
    enable_expansion: bool = Field(
        default=True, description="Whether to perform SKOS taxonomy query expansion"
    )
    min_relevance_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum score threshold for candidate retention / abstention",
    )


class RankedChunk(BaseModel):
    """An individual document text chunk ranked by hybrid retrieval and fusion."""

    chunk_id: uuid.UUID = Field(description="Unique chunk identifier")
    document_version_id: uuid.UUID = Field(
        description="Associated canonical document version ID"
    )
    workspace_id: uuid.UUID = Field(description="Workspace ID")
    text: str = Field(description="Extracted chunk text content")
    score: float = Field(description="Final unified or reranked relevance score")
    retrieval_sources: List[str] = Field(
        default_factory=list,
        description="Retrievers that returned this chunk (e.g. ['dense', 'lexical'])",
    )
    lexical_rank: Optional[int] = Field(
        default=None, description="Rank from lexical search (1-indexed) if found"
    )
    dense_rank: Optional[int] = Field(
        default=None, description="Rank from dense search (1-indexed) if found"
    )
    graph_rank: Optional[int] = Field(
        default=None, description="Rank from graph traversal (1-indexed) if found"
    )
    section_path: List[str] = Field(
        default_factory=list, description="Hierarchical document section path"
    )
    page_numbers: List[int] = Field(
        default_factory=list, description="Page numbers spanning this chunk"
    )
    bounding_boxes: List[BoundingBox] = Field(
        default_factory=list, description="Bounding boxes for deep citation overlay"
    )


class EvidenceItem(BaseModel):
    """Structured, claim-level grounded citation item for downstream consumers."""

    chunk_id: uuid.UUID = Field(description="Source chunk ID")
    document_id: uuid.UUID = Field(description="Source document ID")
    document_title: str = Field(description="Source document title")
    snippet: str = Field(description="Relevant text excerpt")
    confidence_score: float = Field(description="Attribution confidence score (0-1)")
    page_numbers: List[int] = Field(
        default_factory=list, description="Page numbers containing evidence"
    )
    section_path: List[str] = Field(
        default_factory=list, description="Document section path"
    )
    bounding_boxes: List[BoundingBox] = Field(
        default_factory=list, description="Coordinates on document pages"
    )
    attribution_tag: str = Field(
        description="Standard citation tag formatted for prompt grounding"
    )


class AbstentionResult(BaseModel):
    """Explains explicit abstention when retrieval confidence is insufficient."""

    abstained: bool = Field(
        default=False, description="True if evidence confidence is below threshold"
    )
    reason: Optional[str] = Field(
        default=None, description="Human-readable explanation for abstention"
    )
    threshold: float = Field(
        default=0.0, description="Minimum confidence threshold required"
    )
    highest_score: float = Field(
        default=0.0, description="Highest score found among retrieved candidates"
    )


class RetrievalResult(BaseModel):
    """Aggregated output of the end-to-end hybrid retrieval engine."""

    query_text: str = Field(description="Original search query string")
    ranked_chunks: List[RankedChunk] = Field(
        default_factory=list, description="Top ranked chunks after fusion and reranking"
    )
    evidence_items: List[EvidenceItem] = Field(
        default_factory=list, description="Grounded claim-level citation items"
    )
    abstention: AbstentionResult = Field(
        default_factory=AbstentionResult,
        description="Abstention decision and rationale",
    )
    execution_metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Execution diagnostics, latency breakdown, and query expansion trace",
    )

    @property
    def is_abstained(self) -> bool:
        """Shortcut property to check if retrieval abstained."""
        return self.abstention.abstained
