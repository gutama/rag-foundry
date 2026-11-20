"""Structure-aware hierarchical chunking for canonical documents (ADR-0002)."""

from rag_foundry.chunking.models import ChunkingConfig, DocumentChunk
from rag_foundry.chunking.structural import StructuralChunker

__all__ = [
    "ChunkingConfig",
    "DocumentChunk",
    "StructuralChunker",
]
