"""Graph-enhanced retrieval provider and conformance in-memory implementation (ADR-0016)."""

import abc
import re
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from rag_foundry.retrieval.models import (
    RankedChunk,
    RetrievalQuery,
)


class GraphEntity(BaseModel):
    """Knowledge graph entity node with provenance attribution."""

    entity_id: str = Field(description="Unique entity identifier")
    workspace_id: uuid.UUID = Field(description="Workspace identifier")
    name: str = Field(description="Human-readable entity name")
    entity_type: str = Field(default="Entity", description="Ontological entity type")
    description: str = Field(default="", description="Summary description")
    source_chunk_ids: List[uuid.UUID] = Field(
        default_factory=list, description="Source chunk IDs asserting this entity"
    )


class GraphRelation(BaseModel):
    """Knowledge graph edge asserting a relationship between two entities."""

    relation_id: str = Field(description="Unique relationship identifier")
    workspace_id: uuid.UUID = Field(description="Workspace identifier")
    source_entity: str = Field(description="Source entity name")
    target_entity: str = Field(description="Target entity name")
    relation_type: str = Field(description="Predicate or relationship type")
    description: str = Field(default="", description="Relationship statement")
    weight: float = Field(default=1.0, description="Assertion confidence weight")
    source_chunk_ids: List[uuid.UUID] = Field(
        default_factory=list, description="Source chunk IDs asserting this relation"
    )


class GraphEvidence(BaseModel):
    """Structured knowledge subgraph retrieved to substantiate claims."""

    entities: List[GraphEntity] = Field(default_factory=list)
    relations: List[GraphRelation] = Field(default_factory=list)
    subgraph_text: str = Field(default="", description="Formatted subgraph summary")


class GraphRetrievalProvider(abc.ABC):
    """Abstract interface for knowledge graph retrieval engines (e.g. LightRAG adapter)."""

    @abc.abstractmethod
    async def query_graph(
        self, query: RetrievalQuery
    ) -> Tuple[List[RankedChunk], Optional[GraphEvidence]]:
        """Traverse the knowledge graph and return relevant entity chunks and evidence subgraph."""
        pass


class ConformanceGraphProvider(GraphRetrievalProvider):
    """In-memory reference graph provider for testing, validation, and conformance verification."""

    def __init__(self) -> None:
        """Initialize ConformanceGraphProvider."""
        self._entities: Dict[str, GraphEntity] = {}
        self._relations: Dict[str, GraphRelation] = {}

    async def index_graph_elements(
        self,
        entities: List[GraphEntity],
        relations: Optional[List[GraphRelation]] = None,
    ) -> None:
        """Index entities and relations into graph memory."""
        for ent in entities:
            self._entities[ent.entity_id] = ent
        if relations:
            for rel in relations:
                self._relations[rel.relation_id] = rel

    @staticmethod
    def _tokenize(text: str) -> Set[str]:
        return set(re.findall(r"\b\w+\b", text.lower()))

    async def query_graph(
        self, query: RetrievalQuery
    ) -> Tuple[List[RankedChunk], Optional[GraphEvidence]]:
        """Query knowledge graph for entities and relations matching query text."""
        if not query.enable_graph:
            return [], None

        q_tokens = self._tokenize(query.query_text)
        matched_entities: List[Tuple[float, GraphEntity]] = []

        # Find matching entities in workspace
        for ent in self._entities.values():
            if ent.workspace_id != query.filter.workspace_id:
                continue

            ent_tokens = self._tokenize(ent.name + " " + ent.description)
            if not ent_tokens:
                continue

            overlap = len(q_tokens.intersection(ent_tokens))
            if overlap > 0:
                score = float(overlap) / float(max(1, len(q_tokens)))
                matched_entities.append((score, ent))

        matched_entities.sort(key=lambda x: x[0], reverse=True)
        top_entities = [ent for _, ent in matched_entities[: query.top_k]]
        entity_names = {e.name.lower() for e in top_entities}

        # Find associated relations
        matched_relations: List[GraphRelation] = []
        for rel in self._relations.values():
            if rel.workspace_id != query.filter.workspace_id:
                continue
            if (
                rel.source_entity.lower() in entity_names
                or rel.target_entity.lower() in entity_names
            ):
                matched_relations.append(rel)

        # Build subgraph textual narrative
        lines: List[str] = []
        for ent in top_entities:
            lines.append(f"Entity [{ent.name}] ({ent.entity_type}): {ent.description}")
        for rel in matched_relations:
            lines.append(
                f"Relationship: [{rel.source_entity}] --({rel.relation_type})--> [{rel.target_entity}]: {rel.description}"
            )
        subgraph_text = "\n".join(lines)

        evidence = GraphEvidence(
            entities=top_entities,
            relations=matched_relations,
            subgraph_text=subgraph_text,
        )

        # Convert top entities into RankedChunks
        ranked_chunks: List[RankedChunk] = []
        for rank_idx, (score, ent) in enumerate(matched_entities[: query.top_k], start=1):
            source_chunk = ent.source_chunk_ids[0] if ent.source_chunk_ids else uuid.uuid4()
            ranked_chunks.append(
                RankedChunk(
                    chunk_id=source_chunk,
                    document_version_id=uuid.uuid4(),
                    workspace_id=ent.workspace_id,
                    text=f"{ent.name} ({ent.entity_type}): {ent.description}",
                    score=round(min(1.0, score), 4),
                    retrieval_sources=["graph"],
                    graph_rank=rank_idx,
                )
            )

        return ranked_chunks, evidence
