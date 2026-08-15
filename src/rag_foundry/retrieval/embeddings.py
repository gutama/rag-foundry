"""Embedding service abstraction and deterministic mock / local providers."""

import abc
import hashlib
import math
from typing import List


class EmbeddingService(abc.ABC):
    """Abstract base class for vector embedding generation."""

    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        """Return the vector dimensionality of this embedding service."""
        pass

    @abc.abstractmethod
    def embed_query(self, text: str) -> List[float]:
        """Generate a dense vector embedding for a query string."""
        pass

    @abc.abstractmethod
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate dense vector embeddings for a list of chunk texts."""
        pass


class MockDeterministicEmbeddingService(EmbeddingService):
    """Deterministic, lightweight embedding service for testing and conformance verification."""

    def __init__(self, dimension: int = 384) -> None:
        """Initialize mock embedding service.

        Args:
            dimension: Dimensionality of generated vector embeddings.
        """
        if dimension <= 0:
            raise ValueError("Embedding dimension must be positive.")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension

    def _generate_vector(self, text: str) -> List[float]:
        """Generate a deterministic unit-normalized pseudo-vector from text hash."""
        vec: List[float] = []
        # Use multiple sha256 digest rounds to deterministically generate sufficient float components
        seed_bytes = text.encode("utf-8")
        round_idx = 0
        while len(vec) < self._dimension:
            digest = hashlib.sha256(seed_bytes + str(round_idx).encode("utf-8")).digest()
            for i in range(0, len(digest) - 3, 4):
                if len(vec) >= self._dimension:
                    break
                # Unpack 4 bytes as signed integer and convert to float in [-1.0, 1.0]
                int_val = int.from_bytes(digest[i : i + 4], byteorder="big", signed=True)
                vec.append(float(int_val) / 2147483648.0)
            round_idx += 1

        # Normalize to unit length
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            vec[0] = 1.0
            return vec

        return [x / norm for x in vec]

    def embed_query(self, text: str) -> List[float]:
        """Embed single query string."""
        return self._generate_vector(text)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed batch of texts."""
        return [self._generate_vector(t) for t in texts]
