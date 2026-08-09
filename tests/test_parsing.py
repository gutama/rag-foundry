"""Unit tests for ParserProvider, NativePDFParserAdapter, and DoclingParserAdapter."""

import io
import fitz
import docx
import openpyxl
import pytest


@pytest.fixture
def sample_pdf_bytes():
    """Generate sample PDF in bytes with text and headings."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Institutional Architecture Report", fontsize=18)
    page.insert_text(
        (50, 100),
        "This section details the canonical parsing model.",
        fontsize=12,
    )
    pdf_buffer = io.BytesIO()
    doc.save(pdf_buffer)
    doc.close()
    return pdf_buffer.getvalue()


@pytest.fixture
def sample_docx_bytes():
    """Generate sample DOCX in bytes with heading, paragraph, and table."""
    doc = docx.Document()
    doc.add_heading("Financial Summary 2026", level=1)
    doc.add_paragraph("Revenue increased by 15% year over year.")

    table = doc.add_table(rows=2, cols=2)
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = "Quarter"
    hdr_cells[1].text = "Revenue"

    row_cells = table.rows[1].cells
    row_cells[0].text = "Q1"
    row_cells[1].text = "$1,500,000"

    docx_buffer = io.BytesIO()
    doc.save(docx_buffer)
    return docx_buffer.getvalue()


@pytest.fixture
def sample_xlsx_bytes():
    """Generate sample XLSX in bytes with spreadsheet sheet and table data."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Q1 Data"
    ws.append(["Metric", "Value"])
    ws.append(["Ingestion Throughput", "500 docs/min"])

    xlsx_buffer = io.BytesIO()
    wb.save(xlsx_buffer)
    return xlsx_buffer.getvalue()


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
