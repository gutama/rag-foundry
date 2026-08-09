"""Unit tests for ParserProvider, NativePDFParserAdapter, and DoclingParserAdapter."""

import pytest


@pytest.mark.asyncio
async def test_native_pdf_parser_adapter(sample_pdf_bytes):
    """Test NativePDFParserAdapter extracting elements, page numbers, and bounding boxes."""
    from rag_foundry.parsing.native_pdf import NativePDFParserAdapter

    parser = NativePDFParserAdapter()
    canonical_doc = await parser.parse(
        file_bytes=sample_pdf_bytes,
        filename="report.pdf",
        mime_type="application/pdf",
    )

    assert canonical_doc.parser_name == "native_pdf"
    assert canonical_doc.page_count == 1
    assert len(canonical_doc.elements) >= 1

    first_elem = canonical_doc.elements[0]
    assert "Institutional Architecture Report" in first_elem.text
    assert first_elem.page_number == 1
    assert first_elem.bounding_box is not None
    assert len(first_elem.bounding_box) == 4


@pytest.mark.asyncio
async def test_docling_parser_adapter_docx(sample_docx_bytes):
    """Test DoclingParserAdapter parsing DOCX files with headings, paragraphs, and tables."""
    from rag_foundry.parsing.docling_adapter import DoclingParserAdapter

    parser = DoclingParserAdapter()
    canonical_doc = await parser.parse(
        file_bytes=sample_docx_bytes,
        filename="summary.docx",
        mime_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )

    assert canonical_doc.parser_name == "docling"
    assert len(canonical_doc.elements) >= 2

    types = [e.element_type for e in canonical_doc.elements]
    assert "heading" in types
    assert "paragraph" in types or "table" in types


@pytest.mark.asyncio
async def test_docling_parser_adapter_xlsx(sample_xlsx_bytes):
    """Test DoclingParserAdapter parsing XLSX spreadsheet sheets and grid rows."""
    from rag_foundry.parsing.docling_adapter import DoclingParserAdapter

    parser = DoclingParserAdapter()
    canonical_doc = await parser.parse(
        file_bytes=sample_xlsx_bytes,
        filename="data.xlsx",
        mime_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )

    assert canonical_doc.parser_name == "docling"
    assert len(canonical_doc.elements) >= 1
    assert "Ingestion Throughput" in canonical_doc.raw_markdown
