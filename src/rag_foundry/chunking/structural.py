"""Structure-aware hierarchical chunker for CanonicalDocument objects."""

import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from rag_foundry.chunking.models import (
    ChunkingConfig,
    DocumentChunk,
    compute_chunk_checksum,
)
from rag_foundry.parsing.models import CanonicalDocument, DocumentElement

_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+")


@dataclass
class _HeadingEntry:
    """Tracked heading node on the active section hierarchy stack."""

    level: int
    title: str
    element: DocumentElement
    has_emitted_content: bool = False


class StructuralChunker:
    """Splits a CanonicalDocument into structure-aware, provenance-rich chunks."""

    name: str = "structural"
    version: str = "1.0.0"

    def __init__(self, config: Optional[ChunkingConfig] = None) -> None:
        """Initialize the structural chunker.

        Args:
            config: Optional ChunkingConfig; defaults to ChunkingConfig().
        """
        self.config = config or ChunkingConfig()

    def chunk_document(self, document: CanonicalDocument) -> List[DocumentChunk]:
        """Chunk an ordered CanonicalDocument while preserving hierarchy.

        Args:
            document: CanonicalDocument produced by a ParserProvider.

        Returns:
            Ordered list of deterministic DocumentChunk instances.
        """
        if not document.elements:
            return []

        ordered = sorted(document.elements, key=lambda e: e.sequence_number)
        heading_stack: List[_HeadingEntry] = []
        heading_by_id: Dict[uuid.UUID, _HeadingEntry] = {}
        prose_buffer: List[DocumentElement] = []
        chunks: List[DocumentChunk] = []

        for elem in ordered:
            text = elem.text.strip()
            if not text:
                continue

            if elem.element_type == "heading":
                self._flush_prose(prose_buffer, heading_stack, chunks)
                level = self._resolve_heading_level(elem, heading_by_id)
                self._emit_unbodied_leaf_heading(heading_stack, level, chunks)
                self._push_heading(
                    elem, level, text, heading_stack, heading_by_id
                )
            else:
                prose_buffer.append(elem)

        self._flush_prose(prose_buffer, heading_stack, chunks)
        self._emit_unbodied_leaf_heading(heading_stack, 1, chunks)

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
    ) -> None:
        """Emit a chunk for a leaf heading that had no child headings or body.

        Args:
            heading_stack: Current active heading stack.
            next_level: Heading level of the incoming heading (or 1 at EOF).
            chunks: Output list to append emitted DocumentChunk instances to.
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
            # Keep ancestors up through parent_element_id
            while (
                heading_stack
                and heading_stack[-1].element.element_id
                != elem.parent_element_id
            ):
                heading_stack.pop()
        else:
            while heading_stack and heading_stack[-1].level >= level:
                heading_stack.pop()

        # Parent heading now has a subheading child, so do not emit it solo
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

    def _flush_prose(
        self,
        prose_buffer: List[DocumentElement],
        heading_stack: List[_HeadingEntry],
        chunks: List[DocumentChunk],
    ) -> None:
        """Flush buffered prose elements into one or more chunks.

        Args:
            prose_buffer: Buffered non-heading elements (cleared in place).
            heading_stack: Active heading stack.
            chunks: Output chunk list.
        """
        if not prose_buffer:
            return

        section_path = [entry.title for entry in heading_stack]
        combined_text = "\n\n".join(e.text.strip() for e in prose_buffer)
        chunks.append(
            self._build_chunk(
                chunk_index=len(chunks),
                text=combined_text,
                section_path=section_path,
                elements=list(prose_buffer),
            )
        )
        self._mark_stack_emitted(heading_stack)
        prose_buffer.clear()

    def _build_chunk(
        self,
        chunk_index: int,
        text: str,
        section_path: List[str],
        elements: List[DocumentElement],
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> DocumentChunk:
        """Construct a DocumentChunk with deterministic checksum and provenance.

        Args:
            chunk_index: Zero-based sequential chunk index.
            text: Chunk text content.
            section_path: Active section heading path.
            elements: Contributing DocumentElement objects.
            extra_metadata: Optional additional chunk metadata.

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
            bounding_boxes=[],
            element_ids=element_ids,
            element_types=element_types,
            checksum=compute_chunk_checksum(section_path, final_text),
            chunker_name=self.name,
            chunker_version=self.version,
            metadata=metadata,
        )
