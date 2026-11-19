"""Structure-aware hierarchical chunker for CanonicalDocument objects."""

import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from rag_foundry.chunking.models import (
    ChunkingConfig,
    DocumentChunk,
    compute_chunk_checksum,
)
from rag_foundry.parsing.models import CanonicalDocument, DocumentElement
from rag_foundry.retrieval.models import BoundingBox

_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+")
_TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:-]+(?:\|[\s:-]+)*\|?$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_DEFAULT_PAGE_WIDTH = 612.0
_DEFAULT_PAGE_HEIGHT = 792.0


@dataclass
class _HeadingEntry:
    """Tracked heading node on the active section hierarchy stack."""

    level: int
    title: str
    element: DocumentElement
    has_emitted_content: bool = False


class StructuralChunker:
    """Splits a CanonicalDocument into structure-aware, provenance chunks."""

    name: str = "structural"
    version: str = "1.0.0"

    def __init__(self, config: Optional[ChunkingConfig] = None) -> None:
        """Initialize the structural chunker.

        Args:
            config: Optional ChunkingConfig; defaults to ChunkingConfig().
        """
        self.config = config or ChunkingConfig()

    def chunk_document(
        self, document: CanonicalDocument
    ) -> List[DocumentChunk]:
        """Chunk an ordered CanonicalDocument while preserving hierarchy.

        Args:
            document: CanonicalDocument produced by a ParserProvider.

        Returns:
            Ordered list of deterministic DocumentChunk instances.
        """
        if not document.elements:
            return []

        ordered = sorted(document.elements, key=lambda e: e.sequence_number)
        page_extents = self._compute_page_extents(ordered)
        heading_stack: List[_HeadingEntry] = []
        heading_by_id: Dict[uuid.UUID, _HeadingEntry] = {}
        prose_buffer: List[DocumentElement] = []
        chunks: List[DocumentChunk] = []

        for elem in ordered:
            text = elem.text.strip()
            if not text:
                continue

            if elem.element_type == "heading":
                self._flush_prose(
                    prose_buffer, heading_stack, chunks, page_extents
                )
                level = self._resolve_heading_level(elem, heading_by_id)
                self._emit_unbodied_leaf_heading(
                    heading_stack, level, chunks, page_extents
                )
                self._push_heading(
                    elem, level, text, heading_stack, heading_by_id
                )
            elif elem.element_type == "table":
                self._flush_prose(
                    prose_buffer, heading_stack, chunks, page_extents
                )
                self._emit_table(elem, heading_stack, chunks, page_extents)
            elif elem.element_type == "figure":
                self._flush_prose(
                    prose_buffer, heading_stack, chunks, page_extents
                )
                self._emit_figure(elem, heading_stack, chunks, page_extents)
            else:
                prose_buffer.append(elem)

        self._flush_prose(prose_buffer, heading_stack, chunks, page_extents)
        self._emit_unbodied_leaf_heading(
            heading_stack, 1, chunks, page_extents
        )

        return chunks

    @staticmethod
    def _resolve_heading_level(
        elem: DocumentElement,
        heading_by_id: Dict[uuid.UUID, _HeadingEntry],
    ) -> int:
        """Infer 1-based heading depth from metadata, markdown, or parent ID.

        Args:
            elem: Heading DocumentElement.
            heading_by_id: Previously seen headings keyed by element_id.

        Returns:
            Positive integer heading level (1 = top-level heading).
        """
        meta_level = elem.metadata.get("heading_level")
        if isinstance(meta_level, int) and meta_level >= 1:
            return meta_level

        if elem.markdown:
            match = _MARKDOWN_HEADING_RE.match(elem.markdown.strip())
            if match is not None:
                return len(match.group(1))

        if (
            elem.parent_element_id is not None
            and elem.parent_element_id in heading_by_id
        ):
            return heading_by_id[elem.parent_element_id].level + 1

        return 1

    def _emit_unbodied_leaf_heading(
        self,
        heading_stack: List[_HeadingEntry],
        next_level: int,
        chunks: List[DocumentChunk],
        page_extents: Dict[int, Tuple[float, float]],
    ) -> None:
        """Emit a chunk for a leaf heading that had no child headings or body.

        Args:
            heading_stack: Current active heading stack.
            next_level: Heading level of the incoming heading (or 1 at EOF).
            chunks: Output list to append emitted DocumentChunk instances to.
            page_extents: Per-page fallback (width, height) bounds.
        """
        if not heading_stack:
            return
        top = heading_stack[-1]
        if not top.has_emitted_content and next_level <= top.level:
            section_path = [entry.title for entry in heading_stack]
            chunks.append(
                self._build_chunk(
                    chunk_index=len(chunks),
                    text=top.title,
                    section_path=section_path,
                    elements=[top.element],
                    extra_metadata={"heading_only": True},
                    page_extents=page_extents,
                )
            )
            self._mark_stack_emitted(heading_stack)

    @staticmethod
    def _push_heading(
        elem: DocumentElement,
        level: int,
        title: str,
        heading_stack: List[_HeadingEntry],
        heading_by_id: Dict[uuid.UUID, _HeadingEntry],
    ) -> None:
        """Update the active heading stack for a new heading element.

        Args:
            elem: Heading DocumentElement.
            level: Resolved 1-based heading level.
            title: Clean heading text.
            heading_stack: Active heading stack mutated in place.
            heading_by_id: Map of element_id -> _HeadingEntry mutated in place.
        """
        if (
            elem.parent_element_id is not None
            and elem.parent_element_id in heading_by_id
        ):
            while (
                heading_stack
                and heading_stack[-1].element.element_id
                != elem.parent_element_id
            ):
                heading_stack.pop()
        else:
            while heading_stack and heading_stack[-1].level >= level:
                heading_stack.pop()

        if heading_stack:
            heading_stack[-1].has_emitted_content = True

        entry = _HeadingEntry(level=level, title=title, element=elem)
        heading_stack.append(entry)
        heading_by_id[elem.element_id] = entry

    @staticmethod
    def _mark_stack_emitted(heading_stack: List[_HeadingEntry]) -> None:
        """Mark all headings currently on the stack as having content."""
        for entry in heading_stack:
            entry.has_emitted_content = True

    def _emit_figure(
        self,
        elem: DocumentElement,
        heading_stack: List[_HeadingEntry],
        chunks: List[DocumentChunk],
        page_extents: Dict[int, Tuple[float, float]],
    ) -> None:
        """Emit a figure element as an atomic chunk under the active section.

        Args:
            elem: Figure DocumentElement.
            heading_stack: Active heading stack.
            chunks: Output chunk list.
            page_extents: Per-page fallback (width, height) bounds.
        """
        section_path = [entry.title for entry in heading_stack]
        chunks.append(
            self._build_chunk(
                chunk_index=len(chunks),
                text=elem.text.strip(),
                section_path=section_path,
                elements=[elem],
                extra_metadata={"atomic_element": "figure"},
                page_extents=page_extents,
            )
        )
        self._mark_stack_emitted(heading_stack)

    def _emit_table(
        self,
        elem: DocumentElement,
        heading_stack: List[_HeadingEntry],
        chunks: List[DocumentChunk],
        page_extents: Dict[int, Tuple[float, float]],
    ) -> None:
        """Emit a table intact, or split oversized tables by row with headers.

        Args:
            elem: Table DocumentElement.
            heading_stack: Active heading stack.
            chunks: Output chunk list.
            page_extents: Per-page fallback (width, height) bounds.
        """
        section_path = [entry.title for entry in heading_stack]
        raw_text = elem.text.strip()

        if len(raw_text) <= self.config.max_chars:
            chunks.append(
                self._build_chunk(
                    chunk_index=len(chunks),
                    text=raw_text,
                    section_path=section_path,
                    elements=[elem],
                    extra_metadata={"atomic_element": "table"},
                    page_extents=page_extents,
                )
            )
            self._mark_stack_emitted(heading_stack)
            return

        lines = [line for line in raw_text.splitlines() if line.strip()]
        header_lines, data_rows = self._split_table_header_and_rows(lines)
        if not data_rows:
            chunks.append(
                self._build_chunk(
                    chunk_index=len(chunks),
                    text=raw_text,
                    section_path=section_path,
                    elements=[elem],
                    extra_metadata={"atomic_element": "table"},
                    page_extents=page_extents,
                )
            )
            self._mark_stack_emitted(heading_stack)
            return

        header_block = "\n".join(header_lines)
        groups: List[List[str]] = []
        current_rows: List[str] = []

        for row in data_rows:
            candidate_rows = current_rows + [row]
            candidate_text = f"{header_block}\n" + "\n".join(candidate_rows)
            if current_rows and len(candidate_text) > self.config.max_chars:
                groups.append(current_rows)
                current_rows = [row]
            else:
                current_rows = candidate_rows

        if current_rows:
            groups.append(current_rows)

        total_parts = len(groups)
        for part_idx, row_group in enumerate(groups, start=1):
            part_text = f"{header_block}\n" + "\n".join(row_group)
            chunks.append(
                self._build_chunk(
                    chunk_index=len(chunks),
                    text=part_text,
                    section_path=section_path,
                    elements=[elem],
                    extra_metadata={
                        "atomic_element": "table",
                        "table_part": part_idx,
                        "table_total_parts": total_parts,
                    },
                    page_extents=page_extents,
                )
            )
        self._mark_stack_emitted(heading_stack)

    @staticmethod
    def _split_table_header_and_rows(
        lines: List[str],
    ) -> Tuple[List[str], List[str]]:
        """Separate repeating table header lines from data rows.

        Handles Markdown tables (header + separator), plain pipe-delimited
        tables, and XLSX sheet tables (sheet title + column header).

        Args:
            lines: Non-empty table text lines.

        Returns:
            Tuple of (header_lines, data_rows).
        """
        if len(lines) <= 1:
            return lines, []

        idx = 0
        header_lines: List[str] = []
        if lines[0].lstrip().startswith("###") and len(lines) >= 2:
            header_lines.append(lines[0])
            idx = 1

        header_lines.append(lines[idx])
        idx += 1

        if idx < len(lines) and "-" in lines[idx]:
            if _TABLE_SEPARATOR_RE.match(lines[idx].strip()) is not None:
                header_lines.append(lines[idx])
                idx += 1

        return header_lines, lines[idx:]

    def _flush_prose(
        self,
        prose_buffer: List[DocumentElement],
        heading_stack: List[_HeadingEntry],
        chunks: List[DocumentChunk],
        page_extents: Dict[int, Tuple[float, float]],
    ) -> None:
        """Pack buffered prose elements into size-bounded overlapping chunks.

        Args:
            prose_buffer: Buffered non-heading elements (cleared in place).
            heading_stack: Active heading stack.
            chunks: Output chunk list.
            page_extents: Per-page fallback (width, height) bounds.
        """
        if not prose_buffer:
            return

        section_path = [entry.title for entry in heading_stack]
        max_chars = self.config.max_chars
        target_chars = self.config.target_chars
        overlap_chars = self.config.overlap_chars

        # Flatten buffered elements into bounded segments (plus pre-sliced runs
        # for single unbroken tokens longer than max_chars).
        units: List[Tuple[DocumentElement, str, bool]] = []
        for elem in prose_buffer:
            text = elem.text.strip()
            if len(text) <= max_chars:
                units.append((elem, text, False))
            else:
                for seg, is_hard_slice in self._split_oversized_text(
                    text, max_chars, overlap_chars
                ):
                    units.append((elem, seg, is_hard_slice))

        current_items: List[Tuple[DocumentElement, str]] = []
        current_text = ""

        def _emit_current() -> None:
            nonlocal current_items, current_text
            if not current_text:
                return
            unique_elems = self._dedupe_elements(
                [item[0] for item in current_items]
            )
            chunks.append(
                self._build_chunk(
                    chunk_index=len(chunks),
                    text=current_text,
                    section_path=section_path,
                    elements=unique_elems,
                    page_extents=page_extents,
                )
            )

        for elem, seg, is_hard_slice in units:
            if is_hard_slice:
                _emit_current()
                current_items = []
                current_text = ""
                chunks.append(
                    self._build_chunk(
                        chunk_index=len(chunks),
                        text=seg,
                        section_path=section_path,
                        elements=[elem],
                        page_extents=page_extents,
                    )
                )
                continue

            if not current_text:
                current_items = [(elem, seg)]
                current_text = seg
                continue

            same_elem = current_items[-1][0].element_id == elem.element_id
            sep = " " if same_elem else "\n\n"
            candidate = f"{current_text}{sep}{seg}"
            if len(candidate) <= target_chars:
                current_items.append((elem, seg))
                current_text = candidate
                continue

            _emit_current()
            prev_elem = current_items[-1][0]
            overlap_sep = (
                " " if prev_elem.element_id == elem.element_id else "\n\n"
            )
            max_overlap = min(
                overlap_chars,
                max(0, max_chars - len(overlap_sep) - len(seg)),
            )
            overlap_text = self._extract_word_aligned_tail(
                current_text, max_overlap
            )
            if overlap_text:
                current_items = [(prev_elem, overlap_text), (elem, seg)]
                current_text = f"{overlap_text}{overlap_sep}{seg}"
            else:
                current_items = [(elem, seg)]
                current_text = seg

        _emit_current()
        self._mark_stack_emitted(heading_stack)
        prose_buffer.clear()

    @classmethod
    def _split_oversized_text(
        cls,
        text: str,
        max_chars: int,
        overlap_chars: int,
    ) -> List[Tuple[str, bool]]:
        """Split oversized prose by sentence, word, or hard slice fallback.

        Args:
            text: Source paragraph text exceeding max_chars.
            max_chars: Hard character limit per chunk.
            overlap_chars: Overlap budget for hard-sliced unbroken tokens.

        Returns:
            List of (segment_text, is_hard_slice) tuples.
        """
        sentences = [
            s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()
        ]
        segments: List[Tuple[str, bool]] = []

        for sentence in sentences:
            if len(sentence) <= max_chars:
                segments.append((sentence, False))
                continue

            # Sentence itself exceeds max_chars: split on word boundaries.
            words = sentence.split()
            word_buf = ""
            for word in words:
                if len(word) > max_chars:
                    if word_buf:
                        segments.append((word_buf, False))
                        word_buf = ""
                    step = max(1, max_chars - overlap_chars)
                    for start in range(0, len(word), step):
                        piece = word[start : start + max_chars]
                        segments.append((piece, True))
                        if start + max_chars >= len(word):
                            break
                elif not word_buf:
                    word_buf = word
                elif len(word_buf) + 1 + len(word) <= max_chars:
                    word_buf = f"{word_buf} {word}"
                else:
                    segments.append((word_buf, False))
                    word_buf = word
            if word_buf:
                segments.append((word_buf, False))

        return segments

    @staticmethod
    def _extract_word_aligned_tail(text: str, max_len: int) -> str:
        """Return up to max_len trailing characters aligned to a word boundary.

        Args:
            text: Full text of the previously emitted chunk.
            max_len: Maximum character length of the overlap snippet.

        Returns:
            Word-aligned trailing overlap snippet, or empty string if none fits.
        """
        if max_len <= 0 or not text:
            return ""
        if len(text) <= max_len:
            return text

        tail = text[-max_len:]
        # If the character immediately preceding tail is not whitespace, drop
        # the leading partial word so we never cut mid-word.
        if not text[-max_len - 1].isspace():
            first_space = tail.find(" ")
            if first_space == -1:
                return ""
            tail = tail[first_space + 1 :]
        return tail.strip()

    @staticmethod
    def _dedupe_elements(
        elements: List[DocumentElement],
    ) -> List[DocumentElement]:
        """Deduplicate elements by element_id while preserving order."""
        seen: set[uuid.UUID] = set()
        unique: List[DocumentElement] = []
        for elem in elements:
            if elem.element_id not in seen:
                seen.add(elem.element_id)
                unique.append(elem)
        return unique

    @staticmethod
    def _compute_page_extents(
        elements: List[DocumentElement],
    ) -> Dict[int, Tuple[float, float]]:
        """Compute fallback per-page (width, height) bounds for raw boxes.

        Args:
            elements: Ordered DocumentElement instances in the document.

        Returns:
            Mapping from 1-based page number to fallback (width, height).
        """
        extents: Dict[int, Tuple[float, float]] = {}
        for elem in elements:
            if (
                elem.bounding_box is None
                or elem.page_number is None
                or elem.page_number < 1
            ):
                continue
            x0, y0, x1, y1 = (float(v) for v in elem.bounding_box)
            if min(x0, y0, x1, y1) < 0.0 or x1 < x0 or y1 < y0:
                continue
            prev_w, prev_h = extents.get(
                elem.page_number, (_DEFAULT_PAGE_WIDTH, _DEFAULT_PAGE_HEIGHT)
            )
            extents[elem.page_number] = (max(prev_w, x1), max(prev_h, y1))
        return extents

    @staticmethod
    def _extract_bounding_boxes(
        elements: List[DocumentElement],
        page_extents: Optional[Dict[int, Tuple[float, float]]] = None,
    ) -> List[BoundingBox]:
        """Extract normalized, deduplicated BoundingBox provenance records.

        Args:
            elements: Contributing DocumentElement objects.
            page_extents: Optional fallback per-page (width, height) bounds.

        Returns:
            Ordered list of unique validated BoundingBox instances.
        """
        boxes: List[BoundingBox] = []
        seen: set[Tuple[int, float, float, float, float]] = set()

        for elem in elements:
            if (
                elem.bounding_box is None
                or elem.page_number is None
                or elem.page_number < 1
            ):
                continue

            x0, y0, x1, y1 = (float(v) for v in elem.bounding_box)
            if min(x0, y0, x1, y1) < 0.0 or x1 < x0 or y1 < y0:
                continue

            if max(x0, y0, x1, y1) > 1.0:
                raw_w = elem.metadata.get("page_width")
                raw_h = elem.metadata.get("page_height")
                if (
                    isinstance(raw_w, (int, float))
                    and isinstance(raw_h, (int, float))
                    and raw_w > 0
                    and raw_h > 0
                ):
                    width, height = float(raw_w), float(raw_h)
                elif page_extents and elem.page_number in page_extents:
                    width, height = page_extents[elem.page_number]
                else:
                    width, height = _DEFAULT_PAGE_WIDTH, _DEFAULT_PAGE_HEIGHT
                x0 = min(1.0, max(0.0, x0 / width))
                y0 = min(1.0, max(0.0, y0 / height))
                x1 = min(1.0, max(x0, x1 / width))
                y1 = min(1.0, max(y0, y1 / height))

            key = (elem.page_number, x0, y0, x1, y1)
            if key in seen:
                continue
            seen.add(key)
            boxes.append(
                BoundingBox(
                    page=elem.page_number,
                    l=x0,
                    t=y0,
                    r=x1,
                    b=y1,
                )
            )
        return boxes

    def _build_chunk(
        self,
        chunk_index: int,
        text: str,
        section_path: List[str],
        elements: List[DocumentElement],
        extra_metadata: Optional[Dict[str, Any]] = None,
        page_extents: Optional[Dict[int, Tuple[float, float]]] = None,
    ) -> DocumentChunk:
        """Construct a DocumentChunk with deterministic checksum and provenance.

        Args:
            chunk_index: Zero-based sequential chunk index.
            text: Chunk text content.
            section_path: Active section heading path.
            elements: Contributing DocumentElement objects.
            extra_metadata: Optional additional chunk metadata.
            page_extents: Optional fallback per-page (width, height) bounds.

        Returns:
            Populated DocumentChunk instance.
        """
        final_text = text
        if (
            self.config.include_heading_in_text
            and section_path
            and not (extra_metadata and extra_metadata.get("heading_only"))
        ):
            header = " > ".join(section_path)
            final_text = f"{header}\n\n{text}"

        page_numbers = sorted(
            {
                elem.page_number
                for elem in elements
                if elem.page_number is not None and elem.page_number >= 1
            }
        )
        bounding_boxes = self._extract_bounding_boxes(elements, page_extents)
        element_ids = [elem.element_id for elem in elements]
        element_types: List[str] = []
        for elem in elements:
            if elem.element_type not in element_types:
                element_types.append(elem.element_type)

        metadata: Dict[str, Any] = {}
        if extra_metadata:
            metadata.update(extra_metadata)

        return DocumentChunk(
            chunk_index=chunk_index,
            text=final_text,
            section_path=list(section_path),
            page_numbers=page_numbers,
            bounding_boxes=bounding_boxes,
            element_ids=element_ids,
            element_types=element_types,
            checksum=compute_chunk_checksum(section_path, final_text),
            chunker_name=self.name,
            chunker_version=self.version,
            metadata=metadata,
        )
