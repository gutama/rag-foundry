"""Retrieval and semantic search module for RAG Foundry."""

from rag_foundry.retrieval.dense import (
    DenseVectorRecord,
    DenseVectorRetriever,
)
from rag_foundry.retrieval.embeddings import (
    EmbeddingService,
    MockDeterministicEmbeddingService,
)
from rag_foundry.retrieval.expansion import (
    TaxonomyExpansionBridge,
)
from rag_foundry.retrieval.fusion import (
    ReciprocalRankFusion,
)
from rag_foundry.retrieval.lexical import (
    LexicalRecord,
    LexicalRetriever,
)
from rag_foundry.retrieval.models import (
    AbstentionResult,
    BoundingBox,
    EvidenceItem,
    RankedChunk,
    RetrievalFilter,
    RetrievalQuery,
    RetrievalResult,
)
from rag_foundry.retrieval.security import (
    SecurityAuthorizationError,
    SecurityContext,
    WorkspaceGuard,
)

__all__ = [
    "AbstentionResult",
    "BoundingBox",
    "DenseVectorRecord",
    "DenseVectorRetriever",
    "EmbeddingService",
    "EvidenceItem",
    "LexicalRecord",
    "LexicalRetriever",
    "MockDeterministicEmbeddingService",
    "RankedChunk",
    "ReciprocalRankFusion",
    "RetrievalFilter",
    "RetrievalQuery",
    "RetrievalResult",
    "SecurityAuthorizationError",
    "SecurityContext",
    "TaxonomyExpansionBridge",
    "WorkspaceGuard",
]
