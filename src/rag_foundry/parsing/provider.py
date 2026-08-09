"""Abstract ParserProvider base class."""

from abc import ABC, abstractmethod

from rag_foundry.parsing.models import CanonicalDocument


class ParserProvider(ABC):
    """Abstract provider for parsing raw file bytes into CanonicalDocument."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Parser provider name."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Parser provider version."""
        pass

    @abstractmethod
    async def parse(
        self, file_bytes: bytes, filename: str, mime_type: str
    ) -> CanonicalDocument:
        """Parse raw file bytes into a CanonicalDocument representation.

        Args:
            file_bytes: Raw bytes of the source file.
            filename: Source filename.
            mime_type: MIME type of the file.

        Returns:
            CanonicalDocument containing elements and markdown.
        """
        pass
