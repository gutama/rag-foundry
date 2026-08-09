"""Native PDF Parser Adapter using PyMuPDF (fitz)."""

import uuid
from typing import List

import fitz

from rag_foundry.parsing.models import CanonicalDocument, DocumentElement
from rag_foundry.parsing.provider import ParserProvider


class NativePDFParserAdapter(ParserProvider):
    """Fast native PDF text and layout element extractor using PyMuPDF."""

    @property
    def name(self) -> str:
        return "native_pdf"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def parse(
        self, file_bytes: bytes, filename: str, mime_type: str
    ) -> CanonicalDocument:
        """Extract text blocks, page numbers, and bounding boxes from PDF bytes.

        Args:
            file_bytes: Raw PDF bytes.
            filename: PDF filename.
            mime_type: File MIME type.

        Returns:
            CanonicalDocument object.
        """
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        elements: List[DocumentElement] = []
        seq_num = 1
        full_text_blocks: List[str] = []

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_num = page_idx + 1
            blocks = page.get_text("blocks")

            for b in blocks:
                # b tuple: (x0, y0, x1, y1, text, block_no, block_type)
                if len(b) >= 5:
                    x0, y0 = float(b[0]), float(b[1])
                    x1, y1 = float(b[2]), float(b[3])
                    text_str = str(b[4]).strip()
                    if not text_str:
                        continue

                    # Basic heading heuristic
                    elem_type = (
                        "heading"
                        if len(text_str) < 80 and "\n" not in text_str
                        else "paragraph"
                    )
                    bbox = (x0, y0, x1, y1)

                    elem = DocumentElement(
                        element_id=uuid.uuid4(),
                        element_type=elem_type,
                        sequence_number=seq_num,
                        text=text_str,
                        markdown=text_str,
                        page_number=page_num,
                        bounding_box=bbox,
                    )
                    elements.append(elem)
                    full_text_blocks.append(text_str)
                    seq_num += 1

        page_count = len(doc)
        doc.close()
        raw_md = "\n\n".join(full_text_blocks)

        return CanonicalDocument(
            document_id=uuid.uuid4(),
            title=filename,
            mime_type=mime_type,
            page_count=page_count,
            elements=elements,
            raw_markdown=raw_md,
            parser_name=self.name,
            parser_version=self.version,
        )
