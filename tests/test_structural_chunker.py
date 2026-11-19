"""Unit tests for the structure-aware hierarchical chunker (ADR-0002)."""

import hashlib
import uuid

import pytest
from pydantic import ValidationError

from rag_foundry.chunking.models import ChunkingConfig, DocumentChunk
from rag_foundry.chunking.structural import StructuralChunker
from rag_foundry.parsing.models import CanonicalDocument, DocumentElement


def _make_doc(elements: list[DocumentElement]) -> CanonicalDocument:
    """Build a CanonicalDocument fixture from ordered elements."""
    return CanonicalDocument(
        document_id=uuid.uuid4(),
        title="Test Specification",
        mime_type="text/markdown",
        page_count=2,
        elements=elements,
        raw_markdown="\n\n".join(e.markdown or e.text for e in elements),
        parser_name="test_parser",
        parser_version="1.0.0",
    )


def test_chunking_config_defaults_and_validation() -> None:
    """ChunkingConfig enforces positive bounds and overlap < max_chars."""
    cfg = ChunkingConfig()
    assert cfg.target_chars > 0
    assert cfg.max_chars >= cfg.target_chars
    assert 0 <= cfg.overlap_chars < cfg.max_chars

    with pytest.raises(ValidationError):
        ChunkingConfig(target_chars=0)

    with pytest.raises(ValidationError):
        ChunkingConfig(target_chars=500, max_chars=400)

    with pytest.raises(ValidationError):
        ChunkingConfig(target_chars=200, max_chars=300, overlap_chars=300)


def test_document_chunk_deterministic_checksum_and_metadata() -> None:
    """Identical chunk inputs yield deterministic SHA-256 checksums and provenance."""
    elem = DocumentElement(
        element_type="paragraph",
        sequence_number=1,
        text="Governed retrieval enforces ACLs before scoring.",
        page_number=1,
    )
    doc = _make_doc([elem])
    chunker = StructuralChunker()

    first_run = chunker.chunk_document(doc)
    second_run = chunker.chunk_document(doc)

    assert len(first_run) == 1
    chunk = first_run[0]
    assert isinstance(chunk, DocumentChunk)
    assert chunk.chunk_index == 0
    assert chunk.text == elem.text
    assert chunk.chunker_name == chunker.name
    assert chunk.chunker_version == chunker.version
    assert chunk.element_ids == [elem.element_id]
    assert chunk.element_types == ["paragraph"]
    assert len(chunk.checksum) == 64
    assert chunk.checksum == second_run[0].checksum
    expected_digest = hashlib.sha256(
        f"{'|'.join(chunk.section_path)}\n{chunk.text}".encode("utf-8")
    ).hexdigest()
    assert chunk.checksum == expected_digest


def test_heading_hierarchy_tracks_levels_and_flushes_buffers() -> None:
    """Heading level transitions maintain section_path and isolate sections."""
    elements = [
        DocumentElement(
            element_type="heading",
            sequence_number=1,
            text="Architecture",
            markdown="# Architecture",
            page_number=1,
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=2,
            text="High-level system overview.",
            page_number=1,
        ),
        DocumentElement(
            element_type="heading",
            sequence_number=3,
            text="Storage Plane",
            markdown="## Storage Plane",
            page_number=1,
        ),
        DocumentElement(
            element_type="heading",
            sequence_number=4,
            text="Compact Profile",
            markdown="### Compact Profile",
            page_number=1,
            metadata={"heading_level": 3},
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=5,
            text="PostgreSQL with pgvector and FTS.",
            page_number=1,
        ),
        DocumentElement(
            element_type="heading",
            sequence_number=6,
            text="Retrieval Plane",
            markdown="## Retrieval Plane",
            page_number=2,
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=7,
            text="Hybrid lexical and dense retrieval with RRF.",
            page_number=2,
        ),
    ]
    chunker = StructuralChunker(ChunkingConfig(target_chars=1000, max_chars=2000))
    chunks = chunker.chunk_document(_make_doc(elements))

    assert len(chunks) == 3
    assert chunks[0].section_path == ["Architecture"]
    assert chunks[0].text == "High-level system overview."
    assert chunks[1].section_path == [
        "Architecture",
        "Storage Plane",
        "Compact Profile",
    ]
    assert chunks[1].text == "PostgreSQL with pgvector and FTS."
    assert chunks[2].section_path == ["Architecture", "Retrieval Plane"]
    assert chunks[2].text == "Hybrid lexical and dense retrieval with RRF."
    assert [c.chunk_index for c in chunks] == [0, 1, 2]


def test_heading_hierarchy_uses_parent_element_id_fallback() -> None:
    """When heading levels are omitted, parent_element_id builds section_path."""
    root_id = uuid.uuid4()
    child_id = uuid.uuid4()
    elements = [
        DocumentElement(
            element_id=root_id,
            element_type="heading",
            sequence_number=1,
            text="Governance",
            page_number=1,
        ),
        DocumentElement(
            element_id=child_id,
            element_type="heading",
            sequence_number=2,
            text="Stewardship",
            parent_element_id=root_id,
            page_number=1,
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=3,
            text="Curators review ontology proposals.",
            parent_element_id=child_id,
            page_number=1,
        ),
    ]
    chunks = StructuralChunker().chunk_document(_make_doc(elements))

    assert len(chunks) == 1
    assert chunks[0].section_path == ["Governance", "Stewardship"]
    assert chunks[0].text == "Curators review ontology proposals."


def test_heading_only_sections_are_not_silently_dropped() -> None:
    """A leaf heading with no body before the next sibling or EOF emits a chunk."""
    elements = [
        DocumentElement(
            element_type="heading",
            sequence_number=1,
            text="Institutional Architecture Report",
            page_number=1,
        ),
        DocumentElement(
            element_type="heading",
            sequence_number=2,
            text="Standalone Summary Line",
            page_number=1,
        ),
    ]
    chunks = StructuralChunker().chunk_document(_make_doc(elements))

    assert len(chunks) == 2
    assert chunks[0].text == "Institutional Architecture Report"
    assert chunks[0].section_path == ["Institutional Architecture Report"]
    assert chunks[1].text == "Standalone Summary Line"
    assert chunks[1].section_path == ["Standalone Summary Line"]


def test_empty_document_produces_no_chunks() -> None:
    """Empty CanonicalDocument or whitespace-only elements yield an empty list."""
    doc = _make_doc(
        [
            DocumentElement(
                element_type="paragraph",
                sequence_number=1,
                text="   \n\t  ",
                page_number=1,
            )
        ]
    )
    assert StructuralChunker().chunk_document(doc) == []
    assert StructuralChunker().chunk_document(_make_doc([])) == []


def test_include_heading_in_text_and_sibling_parent_transitions() -> None:
    """include_heading_in_text prepends section path; siblings pop cleanly."""
    root_id = uuid.uuid4()
    child_a = uuid.uuid4()
    child_b = uuid.uuid4()
    elements = [
        DocumentElement(
            element_id=root_id,
            element_type="heading",
            sequence_number=1,
            text="Policy",
            page_number=1,
        ),
        DocumentElement(
            element_id=child_a,
            element_type="heading",
            sequence_number=2,
            text="Scope",
            parent_element_id=root_id,
            page_number=1,
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=3,
            text="Applies to all governed workspaces.",
            parent_element_id=child_a,
            page_number=1,
        ),
        DocumentElement(
            element_id=child_b,
            element_type="heading",
            sequence_number=4,
            text="Exceptions",
            parent_element_id=root_id,
            page_number=1,
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=5,
            text="None without curator approval.",
            parent_element_id=child_b,
            page_number=1,
        ),
    ]
    chunker = StructuralChunker(ChunkingConfig(include_heading_in_text=True))
    chunks = chunker.chunk_document(_make_doc(elements))

    assert len(chunks) == 2
    assert chunks[0].section_path == ["Policy", "Scope"]
    assert chunks[0].text.startswith("Policy > Scope\n\n")
    assert chunks[1].section_path == ["Policy", "Exceptions"]
    assert chunks[1].text.startswith("Policy > Exceptions\n\n")

