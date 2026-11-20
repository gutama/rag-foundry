"""Structural typing protocols for pluggable retrieval backends."""

from typing import List, Protocol, runtime_checkable

from rag_foundry.retrieval.models import RankedChunk, RetrievalQuery


@runtime_checkable
class DenseRetrieverProtocol(Protocol):
    """Async protocol implemented by in-memory and DB dense retrievers."""

    async def retrieve(self, query: RetrievalQuery) -> List[RankedChunk]:
        """Retrieve chunks ranked by dense semantic similarity.

        Args:
            query: RetrievalQuery containing query text, filters, and top_k.

        Returns:
            Ordered list of RankedChunk instances.
        """
        ...


@runtime_checkable
class LexicalRetrieverProtocol(Protocol):
    """Async protocol implemented by in-memory and DB lexical retrievers."""

    async def retrieve(self, query: RetrievalQuery) -> List[RankedChunk]:
        """Retrieve chunks ranked by lexical full-text relevance.

        Args:
            query: RetrievalQuery containing query text, filters, and top_k.

        Returns:
            Ordered list of RankedChunk instances.
        """
        ...
