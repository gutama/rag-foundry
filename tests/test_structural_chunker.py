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


def test_tables_and_figures_emit_as_atomic_chunks_separate_from_prose() -> None:
    """Tables and figures flush prose and stay intact under active section."""
    elements = [
        DocumentElement(
            element_type="heading",
            sequence_number=1,
            text="Quarterly Metrics",
            markdown="# Quarterly Metrics",
            page_number=1,
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=2,
            text="Introductory narrative before the table.",
            page_number=1,
        ),
        DocumentElement(
            element_type="table",
            sequence_number=3,
            text="Quarter | Revenue\nQ1 | $1.5M\nQ2 | $1.8M",
            page_number=1,
        ),
        DocumentElement(
            element_type="figure",
            sequence_number=4,
            text="Figure 1: Revenue trend across quarters.",
            page_number=1,
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=5,
            text="Closing commentary after the figure.",
            page_number=1,
        ),
    ]
    chunker = StructuralChunker(ChunkingConfig(target_chars=1000, max_chars=2000))
    chunks = chunker.chunk_document(_make_doc(elements))

    assert len(chunks) == 4
    assert [c.element_types for c in chunks] == [
        ["paragraph"],
        ["table"],
        ["figure"],
        ["paragraph"],
    ]
    assert all(c.section_path == ["Quarterly Metrics"] for c in chunks)
    assert "Quarter | Revenue" in chunks[1].text
    assert chunks[2].text == "Figure 1: Revenue trend across quarters."


def test_oversized_markdown_table_splits_by_rows_with_repeated_header() -> None:
    """Oversized tables split on row boundaries repeating header + separator."""
    table_text = "\n".join(
        [
            "| Metric | Value | Notes |",
            "| --- | --- | --- |",
            "| Latency P50 | 12ms | Compact profile |",
            "| Latency P99 | 48ms | Compact profile |",
            "| Recall@10 | 0.94 | Hybrid RRF |",
            "| Precision@5 | 0.91 | Reranked |",
        ]
    )
    elements = [
        DocumentElement(
            element_type="heading",
            sequence_number=1,
            text="Benchmarks",
            markdown="# Benchmarks",
            page_number=2,
        ),
        DocumentElement(
            element_type="table",
            sequence_number=2,
            text=table_text,
            page_number=2,
        ),
    ]
    chunker = StructuralChunker(
        ChunkingConfig(target_chars=120, max_chars=150, overlap_chars=20)
    )
    chunks = chunker.chunk_document(_make_doc(elements))

    assert len(chunks) >= 2
    for idx, chunk in enumerate(chunks, start=1):
        lines = chunk.text.splitlines()
        assert lines[0] == "| Metric | Value | Notes |"
        assert lines[1] == "| --- | --- | --- |"
        assert len(lines) >= 3
        assert len(chunk.text) <= 150
        assert chunk.section_path == ["Benchmarks"]
        assert chunk.element_types == ["table"]
        assert chunk.metadata["table_part"] == idx
        assert chunk.metadata["table_total_parts"] == len(chunks)

    combined_data = "\n".join(chunks_i.text for chunks_i in chunks)
    assert "Latency P50" in combined_data
    assert "Precision@5" in combined_data


def test_oversized_sheet_table_repeats_sheet_and_column_headers() -> None:
    """XLSX sheet tables repeat both sheet heading and column header on splits."""
    sheet_text = "\n".join(
        [
            "### Sheet: Q1 Data",
            "Metric | Value",
            "Ingestion Throughput | 500 docs/min",
            "Dense Recall | 0.89 baseline",
            "Lexical Recall | 0.85 baseline",
            "Hybrid Fused | 0.95 baseline",
        ]
    )
    elem = DocumentElement(
        element_type="table",
        sequence_number=1,
        text=sheet_text,
        page_number=1,
    )
    chunker = StructuralChunker(
        ChunkingConfig(target_chars=90, max_chars=110, overlap_chars=10)
    )
    chunks = chunker.chunk_document(_make_doc([elem]))

    assert len(chunks) >= 2
    for chunk in chunks:
        lines = chunk.text.splitlines()
        assert lines[0] == "### Sheet: Q1 Data"
        assert lines[1] == "Metric | Value"


def test_prose_packing_respects_target_chars_and_overlap() -> None:
    """Consecutive prose/list items pack up to target_chars and carry overlap."""
    elements = [
        DocumentElement(
            element_type="paragraph",
            sequence_number=1,
            text="Alpha governance rule checks workspace permissions before search.",
            page_number=1,
        ),
        DocumentElement(
            element_type="list_item",
            sequence_number=2,
            text="Beta metadata schemas validate every document attribute strictly.",
            page_number=1,
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=3,
            text="Gamma semantic profiles pin approved taxonomy and ontology versions.",
            page_number=2,
        ),
    ]
    chunker = StructuralChunker(
        ChunkingConfig(target_chars=100, max_chars=150, overlap_chars=30)
    )
    chunks = chunker.chunk_document(_make_doc(elements))

    assert len(chunks) >= 2
    assert all(len(c.text) <= 150 for c in chunks)
    # Overlap: tail phrase from chunk 0 should appear at start of chunk 1
    tail_words = chunks[0].text.split()[-3:]
    assert " ".join(tail_words) in chunks[1].text


def test_oversized_single_paragraph_splits_on_sentence_and_word_boundaries() -> None:
    """Single paragraph exceeding max_chars splits cleanly without mid-word cuts."""
    paragraph = (
        "First sentence explains authorization before retrieval in detail. "
        "Second sentence covers reciprocal rank fusion across lexical and dense hits. "
        "Third sentence specifies ontology query expansion provenance traces. "
        "Fourth sentence guarantees exact term retrieval never regresses."
    )
    elem = DocumentElement(
        element_type="paragraph",
        sequence_number=1,
        text=paragraph,
        page_number=1,
    )
    chunker = StructuralChunker(
        ChunkingConfig(target_chars=90, max_chars=110, overlap_chars=25)
    )
    chunks = chunker.chunk_document(_make_doc([elem]))

    assert len(chunks) >= 3
    assert all(len(c.text) <= 110 for c in chunks)
    # Verify words are not chopped mid-word
    original_words = set(paragraph.split())
    for chunk in chunks:
        for word in chunk.text.split():
            assert word in original_words


def test_single_unbroken_token_exceeding_max_chars_makes_progress() -> None:
    """A single token longer than max_chars hard-slices without infinite loop."""
    long_token = "A" * 120
    elem = DocumentElement(
        element_type="paragraph",
        sequence_number=1,
        text=long_token,
        page_number=1,
    )
    chunker = StructuralChunker(
        ChunkingConfig(target_chars=40, max_chars=50, overlap_chars=10)
    )
    chunks = chunker.chunk_document(_make_doc([elem]))

    assert len(chunks) >= 3
    assert all(len(c.text) <= 50 for c in chunks)
    assert chunks[0].text == "A" * 50


def test_single_line_table_and_long_sentence_word_split_edge_cases() -> None:
    """Single-line tables stay intact; long punctuation-free sentences split by words."""
    single_line_table = DocumentElement(
        element_type="table",
        sequence_number=1,
        text="OnlyHeaderCol1 | OnlyHeaderCol2 | OnlyHeaderCol3 | OnlyHeaderCol4",
        page_number=1,
    )
    long_sentence = DocumentElement(
        element_type="paragraph",
        sequence_number=2,
        text=(
            "governance metadata taxonomy ontology retrieval fusion reranking "
            "citations provenance security workspace isolation verification"
        ),
        page_number=1,
    )
    chunker = StructuralChunker(
        ChunkingConfig(target_chars=45, max_chars=55, overlap_chars=0)
    )
    chunks = chunker.chunk_document(_make_doc([single_line_table, long_sentence]))

    assert chunks[0].element_types == ["table"]
    assert chunks[0].text == single_line_table.text
    prose_chunks = chunks[1:]
    assert len(prose_chunks) >= 3
    assert all(len(c.text) <= 55 for c in prose_chunks)
    assert " ".join(c.text for c in prose_chunks) == long_sentence.text


def test_provenance_aggregates_sorted_pages_and_normalized_bounding_boxes() -> None:
    """Chunk aggregates unique sorted page numbers and validated BoundingBoxes."""
    elements = [
        DocumentElement(
            element_type="paragraph",
            sequence_number=1,
            text="First paragraph on page 2 with normalized box.",
            page_number=2,
            bounding_box=(0.1, 0.2, 0.9, 0.35),
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=2,
            text="Second paragraph on page 1 with raw page-point box.",
            page_number=1,
            bounding_box=(60.0, 100.0, 540.0, 200.0),
            metadata={"page_width": 600.0, "page_height": 800.0},
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=3,
            text="Third paragraph missing coordinates and page number.",
            page_number=None,
            bounding_box=None,
        ),
    ]
    chunker = StructuralChunker(ChunkingConfig(target_chars=1000, max_chars=2000))
    chunks = chunker.chunk_document(_make_doc(elements))

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.page_numbers == [1, 2]
    assert len(chunk.bounding_boxes) == 2

    box_a, box_b = chunk.bounding_boxes
    assert box_a.page == 2
    assert (box_a.l, box_a.t, box_a.r, box_a.b) == (0.1, 0.2, 0.9, 0.35)
    assert box_b.page == 1
    assert pytest.approx((box_b.l, box_b.t, box_b.r, box_b.b)) == (
        0.1,
        0.125,
        0.9,
        0.25,
    )


def test_provenance_gracefully_skips_invalid_or_unpaged_bounding_boxes() -> None:
    """Inverted or unpaged boxes are skipped without failing chunk emission."""
    elements = [
        DocumentElement(
            element_type="paragraph",
            sequence_number=1,
            text="Inverted box coordinates should be skipped safely.",
            page_number=1,
            bounding_box=(0.8, 0.2, 0.2, 0.5),
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=2,
            text="Box without page number should also be skipped.",
            page_number=None,
            bounding_box=(0.1, 0.1, 0.5, 0.5),
        ),
    ]
    chunks = StructuralChunker().chunk_document(_make_doc(elements))

    assert len(chunks) == 1
    assert chunks[0].bounding_boxes == []
    assert chunks[0].page_numbers == [1]


@pytest.mark.asyncio
async def test_end_to_end_parsing_to_chunking_across_pdf_docx_xlsx(
    sample_pdf_bytes: bytes,
    sample_docx_bytes: bytes,
    sample_xlsx_bytes: bytes,
) -> None:
    """ParserRouter + StructuralChunker works across PDF, DOCX, and XLSX."""
    from rag_foundry.parsing.router import ParserRouter

    router = ParserRouter()
    chunker = StructuralChunker()

    pdf_doc, _ = await router.parse_document(
        sample_pdf_bytes, "report.pdf", "application/pdf"
    )
    pdf_chunks = chunker.chunk_document(pdf_doc)
    assert len(pdf_chunks) >= 1
    assert any("Institutional Architecture Report" in c.text for c in pdf_chunks)
    assert all(c.page_numbers == [1] for c in pdf_chunks)
    assert any(len(c.bounding_boxes) >= 1 for c in pdf_chunks)
    for chunk in pdf_chunks:
        for box in chunk.bounding_boxes:
            assert 0.0 <= box.l <= box.r <= 1.0
            assert 0.0 <= box.t <= box.b <= 1.0

    docx_doc, _ = await router.parse_document(
        sample_docx_bytes,
        "summary.docx",
        (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )
    docx_chunks = chunker.chunk_document(docx_doc)
    assert len(docx_chunks) >= 2
    assert any(
        c.section_path == ["Financial Summary 2026"]
        and "Revenue increased by 15%" in c.text
        for c in docx_chunks
    )
    assert any(
        c.element_types == ["table"] and "$1,500,000" in c.text
        for c in docx_chunks
    )

    xlsx_doc, _ = await router.parse_document(
        sample_xlsx_bytes,
        "metrics.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    xlsx_chunks = chunker.chunk_document(xlsx_doc)
    assert len(xlsx_chunks) >= 1
    assert xlsx_chunks[0].element_types == ["table"]
    assert "Ingestion Throughput" in xlsx_chunks[0].text
    assert xlsx_chunks[0].page_numbers == [1]


def test_provenance_fallback_page_extents_and_deduplication() -> None:
    """Raw boxes without page metadata normalize via page extents and dedupe."""
    elements = [
        DocumentElement(
            element_type="paragraph",
            sequence_number=1,
            text="Oversized raw coordinates without page metadata.",
            page_number=1,
            bounding_box=(100.0, 100.0, 1000.0, 1000.0),
        ),
        DocumentElement(
            element_type="paragraph",
            sequence_number=2,
            text="Duplicate raw coordinates should be deduplicated.",
            page_number=1,
            bounding_box=(100.0, 100.0, 1000.0, 1000.0),
        ),
    ]
    chunker = StructuralChunker(
        ChunkingConfig(target_chars=1000, max_chars=2000)
    )
    chunks = chunker.chunk_document(_make_doc(elements))

    assert len(chunks) == 1
    assert len(chunks[0].bounding_boxes) == 1
    box = chunks[0].bounding_boxes[0]
    assert box.page == 1
    assert pytest.approx((box.l, box.t, box.r, box.b)) == (0.1, 0.1, 1.0, 1.0)
