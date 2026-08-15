"""Unit tests for EvidenceAssembler and AbstentionEngine (ADR-0016)."""

import uuid
import pytest

from rag_foundry.retrieval.models import (
    BoundingBox,
    RankedChunk,
)


def test_evidence_assembler_formats_citations():
    """Test EvidenceAssembler generates structured EvidenceItem objects with formatted attribution tags."""
    from rag_foundry.retrieval.evidence import EvidenceAssembler

    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    bbox = BoundingBox(page=5, l=0.1, t=0.2, r=0.7, b=0.8)
    chunk = RankedChunk(
        chunk_id=chunk_id,
        document_version_id=doc_id,
        workspace_id=ws_id,
        text="The minimum capital conservation buffer is 2.5% composed of common equity tier 1.",
        score=0.88,
        section_path=["Capital Rules", "Conservation Buffer"],
        page_numbers=[5],
        bounding_boxes=[bbox],
    )

    assembler = EvidenceAssembler(doc_titles={doc_id: "Basel III Capital Accord"})
    evidence_items = assembler.assemble_evidence(ranked_chunks=[chunk])

    assert len(evidence_items) == 1
    item = evidence_items[0]
    assert item.chunk_id == chunk_id
    assert item.document_id == doc_id
    assert item.document_title == "Basel III Capital Accord"
    assert item.attribution_tag == "[Doc: Basel III Capital Accord, p.5]"
    assert item.confidence_score == 0.88
    assert len(item.bounding_boxes) == 1


def test_abstention_engine_triggers_on_low_confidence():
    """Test AbstentionEngine detects when candidate confidence is beneath minimum threshold."""
    from rag_foundry.retrieval.evidence import AbstentionEngine

    doc_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    low_chunk = RankedChunk(
        chunk_id=uuid.uuid4(),
        document_version_id=doc_id,
        workspace_id=ws_id,
        text="Vaguely related meeting notes from two years ago.",
        score=0.22,
    )

    engine = AbstentionEngine()

    # Threshold 0.50 should trigger abstention on 0.22 score
    result_abstained = engine.evaluate_abstention(
        ranked_chunks=[low_chunk], threshold=0.50
    )
    assert result_abstained.abstained is True
    assert result_abstained.threshold == 0.50
    assert result_abstained.highest_score == 0.22
    assert "below threshold" in result_abstained.reason

    # Threshold 0.20 should pass without abstention
    result_passed = engine.evaluate_abstention(
        ranked_chunks=[low_chunk], threshold=0.20
    )
    assert result_passed.abstained is False


def test_abstention_engine_on_empty_chunks():
    """Test AbstentionEngine abstains when no chunks were retrieved."""
    from rag_foundry.retrieval.evidence import AbstentionEngine

    engine = AbstentionEngine()
    result = engine.evaluate_abstention(ranked_chunks=[], threshold=0.40)
    assert result.abstained is True
    assert result.highest_score == 0.0
    assert "No matching evidence" in result.reason
