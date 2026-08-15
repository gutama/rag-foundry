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
from rag_foundry.retrieval.reranking import (
    CrossEncoderReranker,
    RerankerService,
    ScoringReranker,
)
from rag_foundry.retrieval.security import (
    SecurityAuthorizationError,
    SecurityContext,
    WorkspaceGuard,
)

__all__ = [
    "AbstentionResult",
    "BoundingBox",
    "CrossEncoderReranker",
    "DenseVectorRecord",
    "DenseVectorRetriever",
    "EmbeddingService",
    "EvidenceItem",
    "LexicalRecord",
    "LexicalRetriever",
    "MockDeterministicEmbeddingService",
    "RankedChunk",
    "ReciprocalRankFusion",
    "RerankerService",
    "RetrievalFilter",
    "RetrievalQuery",
    "RetrievalResult",
    "ScoringReranker",
    "SecurityAuthorizationError",
    "SecurityContext",
    "TaxonomyExpansionBridge",
    "WorkspaceGuard",
]
