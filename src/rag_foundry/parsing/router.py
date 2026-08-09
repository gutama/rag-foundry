"""Intelligent ParserRouter with OCR fallback and diagnostics (ADR-0008)."""

import time
from typing import Optional, Tuple

from pydantic import BaseModel, Field

from rag_foundry.parsing.docling_adapter import DoclingParserAdapter
from rag_foundry.parsing.models import CanonicalDocument
from rag_foundry.parsing.native_pdf import NativePDFParserAdapter
from rag_foundry.parsing.ocr_adapter import PaddleOCRProviderAdapter


class ParsingDiagnostics(BaseModel):
    """Diagnostic metadata for document parsing execution."""

    primary_parser: str = Field(description="Name of primary parser used")
    primary_score: float = Field(description="Parse quality score (0.0 - 1.0)")
    fallback_triggered: bool = Field(description="True if OCR fallback ran")
    fallback_parser: Optional[str] = Field(
        default=None, description="Name of fallback parser if triggered"
    )
    parse_duration_seconds: float = Field(description="Parse time in seconds")
    total_elements: int = Field(description="Total extracted element count")


class ParserRouter:
    """Router selecting optimal parser & handling OCR fallback (ADR-0008)."""

    def __init__(self) -> None:
        self.native_pdf = NativePDFParserAdapter()
        self.docling = DoclingParserAdapter()
        self.ocr = PaddleOCRProviderAdapter()

    async def parse_document(
        self, file_bytes: bytes, filename: str, mime_type: str
    ) -> Tuple[CanonicalDocument, ParsingDiagnostics]:
        """Route file to primary parser and evaluate score for OCR fallback.

        Args:
            file_bytes: Source document bytes.
            filename: Source filename.
            mime_type: File MIME type.

        Returns:
            Tuple of (CanonicalDocument, ParsingDiagnostics).
        """
        start_time = time.time()
        fn_lower = filename.lower()

        # Select primary parser
        if mime_type == "application/pdf" or fn_lower.endswith(".pdf"):
            primary_adapter = self.native_pdf
        else:
            primary_adapter = self.docling

        primary_doc = await primary_adapter.parse(
            file_bytes=file_bytes, filename=filename, mime_type=mime_type
        )

        # Quality scoring (ADR-0008 text density check)
        pages = max(1, primary_doc.page_count or 1)
        total_chars = len(primary_doc.raw_markdown.strip())
        density = total_chars / pages

        if total_chars > 0 and density >= 50.0:
            primary_score = min(1.0, 0.5 + round(density / 200.0, 2))
        else:
            primary_score = 0.1

        fallback_triggered = False
        fallback_parser = None
        final_doc = primary_doc

        # Trigger OCR Fallback if text density < 50 chars/page on PDF
        if primary_score < 0.5 and (
            mime_type == "application/pdf" or fn_lower.endswith(".pdf")
        ):
            fallback_triggered = True
            fallback_parser = self.ocr.name
            final_doc = await self.ocr.parse(
                file_bytes=file_bytes, filename=filename, mime_type=mime_type
            )

        duration = round(time.time() - start_time, 4)

        diagnostics = ParsingDiagnostics(
            primary_parser=primary_adapter.name,
            primary_score=primary_score,
            fallback_triggered=fallback_triggered,
            fallback_parser=fallback_parser,
            parse_duration_seconds=duration,
            total_elements=len(final_doc.elements),
        )

        return final_doc, diagnostics
