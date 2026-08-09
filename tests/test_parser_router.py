"""Unit tests for ParserRouter quality scoring, PaddleOCR fallback, and diagnostics."""

import pytest


@pytest.mark.asyncio
async def test_parser_router_selects_primary_for_digital_pdf(sample_pdf_bytes):
    """Test ParserRouter selects native/Docling parser for digital PDF with good text density."""
    from rag_foundry.parsing.router import ParserRouter

    router = ParserRouter()
    result_doc, diagnostics = await router.parse_document(
        file_bytes=sample_pdf_bytes,
        filename="digital_report.pdf",
        mime_type="application/pdf",
    )

    assert result_doc.parser_name in ["native_pdf", "docling"]
    assert diagnostics.fallback_triggered is False
    assert diagnostics.primary_score >= 0.5
    assert diagnostics.total_elements >= 1


@pytest.mark.asyncio
async def test_parser_router_triggers_ocr_fallback_for_scanned_pdf(
    scanned_pdf_bytes,
):
    """Test ParserRouter triggers OCR fallback when text density < 50 chars/page (ADR-0008)."""
    from rag_foundry.parsing.router import ParserRouter

    router = ParserRouter()
    result_doc, diagnostics = await router.parse_document(
        file_bytes=scanned_pdf_bytes,
        filename="scanned_doc.pdf",
        mime_type="application/pdf",
    )

    assert diagnostics.fallback_triggered is True
    assert diagnostics.fallback_parser == "paddle_ocr"
    assert result_doc.parser_name == "paddle_ocr"


@pytest.mark.asyncio
async def test_parser_router_diagnostics_metadata():
    """Test ParsingDiagnostics recording parser name, score, and duration."""
    from rag_foundry.parsing.router import ParserRouter

    router = ParserRouter()
    result_doc, diagnostics = await router.parse_document(
        file_bytes=b"Sample plain text document content.",
        filename="notes.txt",
        mime_type="text/plain",
    )

    assert diagnostics.primary_parser is not None
    assert diagnostics.parse_duration_seconds >= 0.0
    assert diagnostics.primary_score > 0.0
