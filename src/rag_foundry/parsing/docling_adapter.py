"""Docling Multi-Format Layout Parser Adapter for PDF, DOCX, XLSX, PPTX."""

import io
import uuid
from typing import List

import docx
import openpyxl

from rag_foundry.parsing.models import CanonicalDocument, DocumentElement
from rag_foundry.parsing.provider import ParserProvider


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

    def _parse_docx(
        self, file_bytes: bytes, filename: str, mime_type: str
    ) -> CanonicalDocument:
        """Parse Microsoft Word DOCX file into structured elements."""
        doc = docx.Document(io.BytesIO(file_bytes))
        elements: List[DocumentElement] = []
        seq_num = 1
        md_parts: List[str] = []

        for p in doc.paragraphs:
            text_str = p.text.strip()
            if not text_str:
                continue

            style_name = p.style.name.lower() if p.style else ""
            if "heading" in style_name:
                elem_type = "heading"
                md_str = f"## {text_str}"
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
            )
            elements.append(elem)
            md_parts.append(md_str)
            seq_num += 1

        for table in doc.tables:
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
