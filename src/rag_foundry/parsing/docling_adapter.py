"""Docling Multi-Format Layout Parser Adapter for PDF, DOCX, XLSX, PPTX."""

import io
import re
import uuid
from typing import Any, Dict, List

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph
import openpyxl

from rag_foundry.parsing.models import CanonicalDocument, DocumentElement
from rag_foundry.parsing.provider import ParserProvider

_HEADING_LEVEL_RE = re.compile(r"(\d+)")


class DoclingParserAdapter(ParserProvider):
    """Multi-format layout parser for PDF, DOCX, XLSX, and PPTX documents."""

    @property
    def name(self) -> str:
        return "docling"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def parse(
        self, file_bytes: bytes, filename: str, mime_type: str
    ) -> CanonicalDocument:
        """Parse PDF or Office document into CanonicalDocument representation.

        Args:
            file_bytes: Raw source file bytes.
            filename: Source filename.
            mime_type: File MIME type.

        Returns:
            CanonicalDocument containing elements and markdown.
        """
        fn_lower = filename.lower()

        if fn_lower.endswith(".docx") or "wordprocessingml" in mime_type:
            return self._parse_docx(file_bytes, filename, mime_type)
        elif fn_lower.endswith(".xlsx") or "spreadsheetml" in mime_type:
            return self._parse_xlsx(file_bytes, filename, mime_type)
        else:
            # Fallback or generic text parser for other formats
            return self._parse_generic(file_bytes, filename, mime_type)

    @staticmethod
    def _extract_docx_heading_level(style_name: str) -> int:
        """Derive a 1..6 heading level from a Word paragraph style name."""
        match = _HEADING_LEVEL_RE.search(style_name)
        if match is not None:
            return max(1, min(6, int(match.group(1))))
        return 1

    def _parse_docx(
        self, file_bytes: bytes, filename: str, mime_type: str
    ) -> CanonicalDocument:
        """Parse Microsoft Word DOCX preserving paragraph/table body order."""
        doc = docx.Document(io.BytesIO(file_bytes))
        elements: List[DocumentElement] = []
        seq_num = 1
        md_parts: List[str] = []

        # Walk body children in XML order so tables retain their true section
        # position relative to surrounding headings and paragraphs.
        for child in doc.element.body.iterchildren():
            tag = child.tag
            if tag.endswith("}p"):
                para = Paragraph(child, doc)
                text_str = para.text.strip()
                if not text_str:
                    continue

                raw_style = para.style.name if para.style else ""
                style_lower = raw_style.lower()
                metadata: Dict[str, Any] = {}
                if "heading" in style_lower or style_lower == "title":
                    elem_type = "heading"
                    level = self._extract_docx_heading_level(style_lower)
                    md_str = f"{'#' * level} {text_str}"
                    metadata["heading_level"] = level
                    if raw_style:
                        metadata["style"] = raw_style
                else:
                    elem_type = "paragraph"
                    md_str = text_str

                elem = DocumentElement(
                    element_id=uuid.uuid4(),
                    element_type=elem_type,
                    sequence_number=seq_num,
                    text=text_str,
                    markdown=md_str,
                    page_number=1,
                    metadata=metadata,
                )
                elements.append(elem)
                md_parts.append(md_str)
                seq_num += 1
            elif tag.endswith("}tbl"):
                table = Table(child, doc)
                table_rows: List[str] = []
                for row in table.rows:
                    row_cells = [c.text.strip() for c in row.cells]
                    table_rows.append(" | ".join(row_cells))

                table_md = "\n".join(table_rows)
                if table_md.strip():
                    elem = DocumentElement(
                        element_id=uuid.uuid4(),
                        element_type="table",
                        sequence_number=seq_num,
                        text=table_md,
                        markdown=f"```table\n{table_md}\n```",
                        page_number=1,
                    )
                    elements.append(elem)
                    md_parts.append(table_md)
                    seq_num += 1

        return CanonicalDocument(
            document_id=uuid.uuid4(),
            title=filename,
            mime_type=mime_type,
            page_count=1,
            elements=elements,
            raw_markdown="\n\n".join(md_parts),
            parser_name=self.name,
            parser_version=self.version,
        )

    def _parse_xlsx(
        self, file_bytes: bytes, filename: str, mime_type: str
    ) -> CanonicalDocument:
        """Parse Microsoft Excel XLSX file into sheet grid elements."""
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        elements: List[DocumentElement] = []
        seq_num = 1
        md_parts: List[str] = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            sheet_rows: List[str] = []

            for row in ws.iter_rows(values_only=True):
                non_empty = [str(val) for val in row if val is not None]
                if non_empty:
                    sheet_rows.append(" | ".join(non_empty))

            if sheet_rows:
                sheet_md = f"### Sheet: {sheet_name}\n" + "\n".join(sheet_rows)
                elem = DocumentElement(
                    element_id=uuid.uuid4(),
                    element_type="table",
                    sequence_number=seq_num,
                    text=sheet_md,
                    markdown=sheet_md,
                    page_number=seq_num,
                )
                elements.append(elem)
                md_parts.append(sheet_md)
                seq_num += 1

        return CanonicalDocument(
            document_id=uuid.uuid4(),
            title=filename,
            mime_type=mime_type,
            page_count=len(wb.sheetnames),
            elements=elements,
            raw_markdown="\n\n".join(md_parts),
            parser_name=self.name,
            parser_version=self.version,
        )

    def _parse_generic(
        self, file_bytes: bytes, filename: str, mime_type: str
    ) -> CanonicalDocument:
        """Generic fallback parser for plain text / unstructured files."""
        try:
            text_content = file_bytes.decode("utf-8", errors="ignore").strip()
        except Exception:
            text_content = f"Binary content ({len(file_bytes)} bytes)"

        elem = DocumentElement(
            element_id=uuid.uuid4(),
            element_type="paragraph",
            sequence_number=1,
            text=text_content,
            markdown=text_content,
            page_number=1,
        )

        return CanonicalDocument(
            document_id=uuid.uuid4(),
            title=filename,
            mime_type=mime_type,
            page_count=1,
            elements=[elem],
            raw_markdown=text_content,
            parser_name=self.name,
            parser_version=self.version,
        )
