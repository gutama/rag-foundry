"""Retrieval and semantic search module for RAG Foundry."""

from rag_foundry.retrieval.dense import (
    DenseVectorRecord,
    DenseVectorRetriever,
)
from rag_foundry.retrieval.embeddings import (
    EmbeddingService,
    HttpEmbeddingService,
    MockDeterministicEmbeddingService,
    SentenceTransformerEmbeddingService,
)
from rag_foundry.retrieval.evidence import (
    AbstentionEngine,
    EvidenceAssembler,
)
from rag_foundry.retrieval.expansion import (
    SemanticQueryExpansionService,
    TaxonomyExpansionBridge,
)
from rag_foundry.retrieval.fusion import (
    ReciprocalRankFusion,
)
from rag_foundry.retrieval.graph import (
    ConformanceGraphProvider,
    GraphEntity,
    GraphEvidence,
    GraphRelation,
    GraphRetrievalProvider,
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
from rag_foundry.retrieval.ontology_expansion import (
    EntityQueryExpander,
    ExpansionPolicy,
    OntologyQueryExpander,
    SemanticExpansionTerm,
    SemanticExpansionTrace,
)
from rag_foundry.retrieval.pipeline import (
    RetrievalPipeline,
)
from rag_foundry.retrieval.postgres_dense import (
    PostgresDenseRetriever,
)
from rag_foundry.retrieval.postgres_lexical import (
    PostgresLexicalRetriever,
)
from rag_foundry.retrieval.protocols import (
    DenseRetrieverProtocol,
    LexicalRetrieverProtocol,
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
    "AbstentionEngine",
    "AbstentionResult",
    "BoundingBox",
    "ConformanceGraphProvider",
    "CrossEncoderReranker",
    "DenseRetrieverProtocol",
    "DenseVectorRecord",
    "DenseVectorRetriever",
    "EmbeddingService",
    "EntityQueryExpander",
    "EvidenceAssembler",
    "EvidenceItem",
    "ExpansionPolicy",
    "GraphEntity",
    "GraphEvidence",
    "GraphRelation",
    "GraphRetrievalProvider",
    "HttpEmbeddingService",
    "LexicalRecord",
    "LexicalRetriever",
    "LexicalRetrieverProtocol",
    "MockDeterministicEmbeddingService",
    "OntologyQueryExpander",
    "PostgresDenseRetriever",
    "PostgresLexicalRetriever",
    "RankedChunk",
    "ReciprocalRankFusion",
    "RerankerService",
    "RetrievalFilter",
    "RetrievalPipeline",
    "RetrievalQuery",
    "RetrievalResult",
    "ScoringReranker",
    "SecurityAuthorizationError",
    "SecurityContext",
    "SemanticExpansionTerm",
    "SemanticExpansionTrace",
    "SemanticQueryExpansionService",
    "SentenceTransformerEmbeddingService",
    "TaxonomyExpansionBridge",
    "WorkspaceGuard",
]
