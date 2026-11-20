"""Native PDF Parser Adapter using PyMuPDF (fitz)."""

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import fitz

from rag_foundry.parsing.models import CanonicalDocument, DocumentElement
from rag_foundry.parsing.provider import ParserProvider

_BULLET_PREFIXES = ("•", "-", "*", "–", "—", "▪", "◦")
_HEADING_SIZE_RATIO = 1.15
_BOLD_FLAG_MASK = 16


@dataclass
class _ExtractedPDFBlock:
    """Intermediate PDF text block carrying typographic metrics."""

    page_num: int
    page_width: float
    page_height: float
    bbox: Tuple[float, float, float, float]
    text: str
    line_count: int
    font_size: float
    size_bucket: float
    char_count: int
    is_bold: bool


def _bucket_font_size(size: float) -> float:
    """Round font size to nearest 0.5 pt to absorb floating-point jitter."""
    return round(size * 2.0) / 2.0


class NativePDFParserAdapter(ParserProvider):
    """Fast native PDF text and layout element extractor using PyMuPDF."""

    @property
    def name(self) -> str:
        return "native_pdf"

    @property
    def version(self) -> str:
        return "1.0.0"

    @staticmethod
    def _extract_page_blocks(
        page: Any,
        page_num: int,
    ) -> List[_ExtractedPDFBlock]:
        """Extract text blocks and font metrics from one PyMuPDF page."""
        page_width = float(page.rect.width) if page.rect.width > 0 else 1.0
        page_height = (
            float(page.rect.height) if page.rect.height > 0 else 1.0
        )
        page_dict = page.get_text("dict")
        extracted: List[_ExtractedPDFBlock] = []

        for block in page_dict.get("blocks", []):
            if block.get("type", 0) != 0:
                continue
            raw_bbox = block.get("bbox")
            if not raw_bbox or len(raw_bbox) < 4:
                continue

            line_texts: List[str] = []
            size_weights: Dict[float, int] = {}
            bold_chars = 0
            total_chars = 0

            for line in block.get("lines", []):
                span_texts: List[str] = []
                for span in line.get("spans", []):
                    span_text = str(span.get("text", ""))
                    if not span_text:
                        continue
                    span_texts.append(span_text)
                    non_ws = len(span_text.strip())
                    if non_ws == 0:
                        continue
                    size_val = float(span.get("size", 12.0))
                    bucket = _bucket_font_size(size_val)
                    size_weights[bucket] = size_weights.get(bucket, 0) + non_ws
                    flags = int(span.get("flags", 0))
                    font_name = str(span.get("font", "")).lower()
                    if (flags & _BOLD_FLAG_MASK) != 0 or "bold" in font_name:
                        bold_chars += non_ws
                    total_chars += non_ws

                joined_line = "".join(span_texts).strip()
                if joined_line:
                    line_texts.append(joined_line)

            text_str = "\n".join(line_texts).strip()
            if not text_str or total_chars == 0:
                continue

            dominant_bucket = max(
                size_weights.items(), key=lambda item: (item[1], item[0])
            )[0]
            x0 = min(1.0, max(0.0, float(raw_bbox[0]) / page_width))
            y0 = min(1.0, max(0.0, float(raw_bbox[1]) / page_height))
            x1 = min(1.0, max(x0, float(raw_bbox[2]) / page_width))
            y1 = min(1.0, max(y0, float(raw_bbox[3]) / page_height))

            extracted.append(
                _ExtractedPDFBlock(
                    page_num=page_num,
                    page_width=page_width,
                    page_height=page_height,
                    bbox=(x0, y0, x1, y1),
                    text=text_str,
                    line_count=len(line_texts),
                    font_size=dominant_bucket,
                    size_bucket=dominant_bucket,
                    char_count=total_chars,
                    is_bold=(bold_chars / float(total_chars)) >= 0.7,
                )
            )

        return extracted

    @staticmethod
    def _classify_headings(
        blocks: List[_ExtractedPDFBlock],
    ) -> Dict[int, int]:
        """Determine heading indices and 1..6 levels from font metrics.

        Args:
            blocks: All extracted text blocks across the PDF document.

        Returns:
            Mapping from block index to 1-based heading level for blocks
            identified as headings.
        """
        if not blocks:
            return {}

        # Modal (char-weighted) body font size and bold baseline
        size_totals: Dict[float, int] = {}
        for blk in blocks:
            size_totals[blk.size_bucket] = (
                size_totals.get(blk.size_bucket, 0) + blk.char_count
            )
        # Prefer the highest character count; break ties toward smaller size
        # (body text is smaller than headings).
        body_size = max(
            size_totals.items(), key=lambda item: (item[1], -item[0])
        )[0]
        body_chars = sum(
            b.char_count for b in blocks if b.size_bucket == body_size
        )
        body_bold_chars = sum(
            b.char_count
            for b in blocks
            if b.size_bucket == body_size and b.is_bold
        )
        body_is_bold = (
            body_chars > 0 and (body_bold_chars / float(body_chars)) >= 0.5
        )

        size_heading_indices: Dict[int, float] = {}
        bold_heading_indices: List[int] = []

        for idx, blk in enumerate(blocks):
            if blk.text.startswith(_BULLET_PREFIXES):
                continue
            if len(blk.text) > 120 or blk.line_count > 2:
                continue

            if blk.size_bucket >= body_size * _HEADING_SIZE_RATIO:
                size_heading_indices[idx] = blk.size_bucket
            elif (
                blk.size_bucket >= body_size
                and blk.is_bold
                and not body_is_bold
                and blk.line_count == 1
                and len(blk.text) < 80
                and not blk.text.endswith((".", "!", "?", ";"))
            ):
                bold_heading_indices.append(idx)

        distinct_sizes = sorted(
            set(size_heading_indices.values()), reverse=True
        )
        level_by_size = {
            sz: min(6, rank)
            for rank, sz in enumerate(distinct_sizes, start=1)
        }

        levels: Dict[int, int] = {
            idx: level_by_size[sz]
            for idx, sz in size_heading_indices.items()
        }
        bold_level = min(6, len(distinct_sizes) + 1)
        for idx in bold_heading_indices:
            levels[idx] = bold_level

        return levels

    async def parse(
        self, file_bytes: bytes, filename: str, mime_type: str
    ) -> CanonicalDocument:
        """Extract text blocks, page numbers, headings, and bounding boxes.

        Args:
            file_bytes: Raw PDF bytes.
            filename: PDF filename.
            mime_type: File MIME type.

        Returns:
            CanonicalDocument object.
        """
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        raw_blocks: List[_ExtractedPDFBlock] = []
        for page_idx in range(len(doc)):
            raw_blocks.extend(
                self._extract_page_blocks(doc[page_idx], page_idx + 1)
            )
        page_count = len(doc)
        doc.close()

        heading_levels = self._classify_headings(raw_blocks)
        elements: List[DocumentElement] = []
        full_text_blocks: List[str] = []

        for idx, blk in enumerate(raw_blocks):
            seq_num = idx + 1
            level = heading_levels.get(idx)
            metadata: Dict[str, Any] = {
                "page_width": blk.page_width,
                "page_height": blk.page_height,
                "font_size": blk.font_size,
                "is_bold": blk.is_bold,
            }
            if level is not None:
                elem_type = "heading"
                md_str = f"{'#' * level} {blk.text}"
                metadata["heading_level"] = level
            else:
                elem_type = "paragraph"
                md_str = blk.text

            elements.append(
                DocumentElement(
                    element_id=uuid.uuid4(),
                    element_type=elem_type,
                    sequence_number=seq_num,
                    text=blk.text,
                    markdown=md_str,
                    page_number=blk.page_num,
                    bounding_box=blk.bbox,
                    metadata=metadata,
                )
            )
            full_text_blocks.append(md_str)

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
