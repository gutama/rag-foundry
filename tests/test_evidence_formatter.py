"""Unit tests for EvidenceFormatter and mode-specific prompt policies."""

import uuid

from rag_foundry.generation.models import (
    EvidenceEntry,
    KnowledgeAuthority,
)
from rag_foundry.retrieval.models import (
    BoundingBox,
    EvidenceItem,
    RankedChunk,
)


def _make_entry(
    *,
    handle: str = "tmp",
    authority: KnowledgeAuthority,
    text: str,
    ws_id: uuid.UUID,
    confidence: float = 0.9,
    title: str | None = None,
    pages: tuple[int, ...] = (),
    assertion_id: uuid.UUID | None = None,
) -> EvidenceEntry:
    """Create a sample EvidenceEntry for formatter tests."""
    return EvidenceEntry(
        evidence_id=handle,
        authority=authority,
        text=text,
        workspace_id=ws_id,
        security_domain="compliance",
        document_version_id=uuid.uuid4()
        if authority == KnowledgeAuthority.DOCUMENT_EVIDENCE
        else None,
        document_title=title,
        chunk_id=uuid.uuid4()
        if authority == KnowledgeAuthority.DOCUMENT_EVIDENCE
        else None,
        assertion_id=assertion_id,
        assertion_origin=(
            "curated"
            if authority == KnowledgeAuthority.CURATED
            else (
                "extracted"
                if authority == KnowledgeAuthority.EXTRACTED
                else None
            )
        ),
        assertion_status=(
            "approved"
            if authority == KnowledgeAuthority.CURATED
            else (
                "candidate"
                if authority == KnowledgeAuthority.EXTRACTED
                else None
            )
        ),
        page_numbers=pages,
        confidence_score=confidence,
    )


def test_formatter_deterministic_handles_and_authority_banners() -> None:
    """Formatter assigns A1..An and E1..En with distinct ADR-0013 banners."""
    from rag_foundry.generation.formatter import EvidenceFormatter

    ws_id = uuid.uuid4()
    cur_low = _make_entry(
        authority=KnowledgeAuthority.CURATED,
        text="Policy requires annual review.",
        ws_id=ws_id,
        confidence=0.85,
        assertion_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
    )
    cur_high = _make_entry(
        authority=KnowledgeAuthority.CURATED,
        text="Retention period is 7 years.",
        ws_id=ws_id,
        confidence=1.0,
        assertion_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    )
    ext_cand = _make_entry(
        authority=KnowledgeAuthority.EXTRACTED,
        text="Draft memo mentions 5-year archive.",
        ws_id=ws_id,
        confidence=0.72,
        assertion_id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
    )
    doc1 = _make_entry(
        authority=KnowledgeAuthority.DOCUMENT_EVIDENCE,
        text="Section 4.1: Keep financial logs for seven years.",
        ws_id=ws_id,
        title="Compliance Manual",
        pages=(4,),
        confidence=0.95,
    )
    doc2 = _make_entry(
        authority=KnowledgeAuthority.DOCUMENT_EVIDENCE,
        text="Appendix B lists archival storage tiers.",
        ws_id=ws_id,
        title="Compliance Manual",
        pages=(12,),
        confidence=0.80,
    )

    formatter = EvidenceFormatter()
    ctx_a = formatter.format(
        document_entries=[doc1, doc2],
        assertion_entries=[ext_cand, cur_low, cur_high],
        mode="curated_knowledge",
    )
    # Reversed assertion input produces identical deterministic output
    ctx_b = formatter.format(
        document_entries=[doc1, doc2],
        assertion_entries=[cur_high, ext_cand, cur_low],
        mode="curated_knowledge",
    )
    assert ctx_a.context_text == ctx_b.context_text
    assert [e.evidence_id for e in ctx_a.entries] == [
        "A1",
        "A2",
        "E1",
        "E2",
        "A3",
    ]
    assert ctx_a.evidence_map["A1"].text == "Retention period is 7 years."
    assert ctx_a.evidence_map["A1"].authority == KnowledgeAuthority.CURATED
    assert ctx_a.evidence_map["A3"].authority == KnowledgeAuthority.EXTRACTED
    assert ctx_a.evidence_map["E1"].document_title == "Compliance Manual"
    assert ctx_a.curated_count == 2
    assert ctx_a.extracted_count == 1
    assert ctx_a.document_count == 2
    assert ctx_a.truncated_count == 0

    assert "[CURATED / APPROVED]" in ctx_a.context_text
    assert "[DOCUMENT EVIDENCE]" in ctx_a.context_text
    assert "[EXTRACTED / CANDIDATE — UNVERIFIED]" in ctx_a.context_text
    assert ctx_a.context_text.index("[CURATED / APPROVED]") < (
        ctx_a.context_text.index("[EXTRACTED / CANDIDATE — UNVERIFIED]")
    )

    # Excluding extracted candidates removes them from text and evidence_map
    curated_only = formatter.format(
        document_entries=[doc1],
        assertion_entries=[cur_high, ext_cand],
        mode="curated_knowledge",
        include_extracted_candidates=False,
    )
    assert curated_only.extracted_count == 0
    assert (
        "[EXTRACTED / CANDIDATE — UNVERIFIED]"
        not in curated_only.context_text
    )
    assert set(curated_only.evidence_map.keys()) == {"A1", "E1"}


def test_formatter_budget_truncation_excludes_omitted_handles() -> None:
    """Budget truncation caps context length and omits truncated handles."""
    from rag_foundry.generation.formatter import EvidenceFormatter

    ws_id = uuid.uuid4()
    docs = [
        _make_entry(
            authority=KnowledgeAuthority.DOCUMENT_EVIDENCE,
            text=f"Document passage number {idx} " + ("detail " * 25),
            ws_id=ws_id,
            title=f"Doc {idx}",
            pages=(idx,),
            confidence=0.9 - idx * 0.05,
        )
        for idx in range(1, 6)
    ]

    formatter = EvidenceFormatter(max_context_chars=450, max_item_chars=120)
    ctx = formatter.format(document_entries=docs, mode="standard")

    assert len(ctx.context_text) <= 450
    assert ctx.truncated_count > 0
    assert ctx.document_count < len(docs)
    assert len(ctx.evidence_map) == ctx.document_count
    # Omitted entries must not be present in evidence_map
    for idx in range(ctx.document_count + 1, len(docs) + 1):
        assert f"E{idx}" not in ctx.evidence_map

    # Empty input produces explicit empty-context notice
    empty_ctx = formatter.format(document_entries=[], assertion_entries=[])
    assert empty_ctx.entries == ()
    assert empty_ctx.evidence_map == {}
    assert "No authorized evidence" in empty_ctx.context_text


def test_build_document_entries_bridges_retrieval_models() -> None:
    """build_document_entries maps RankedChunk and EvidenceItem provenance."""
    from rag_foundry.generation.formatter import EvidenceFormatter

    ws_id = uuid.uuid4()
    doc_ver_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    bbox = BoundingBox(page=2, l=0.1, t=0.2, r=0.9, b=0.4)

    chunk = RankedChunk(
        chunk_id=chunk_id,
        document_version_id=doc_ver_id,
        workspace_id=ws_id,
        text="Quarterly audits require dual sign-off.",
        score=0.91,
        section_path=["Controls", "Audits"],
        page_numbers=[2],
        bounding_boxes=[bbox],
    )
    ev_item = EvidenceItem(
        chunk_id=chunk_id,
        document_id=doc_ver_id,
        document_title="Internal Controls Charter",
        snippet="Quarterly audits require dual sign-off.",
        confidence_score=0.91,
        page_numbers=[2],
        section_path=["Controls", "Audits"],
        bounding_boxes=[bbox],
        attribution_tag="[Internal Controls Charter, p. 2]",
    )

    entries = EvidenceFormatter.build_document_entries(
        ranked_chunks=[chunk],
        evidence_items=[ev_item],
        security_domain_map={chunk_id: "audit"},
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry.authority == KnowledgeAuthority.DOCUMENT_EVIDENCE
    assert entry.chunk_id == chunk_id
    assert entry.document_version_id == doc_ver_id
    assert entry.document_title == "Internal Controls Charter"
    assert entry.security_domain == "audit"
    assert entry.page_numbers == (2,)
    assert entry.section_path == ("Controls", "Audits")
    assert entry.bounding_boxes == (bbox,)


def test_mode_specific_prompt_policies_and_decomposition_prompt() -> None:
    """Prompt builders enforce grounding, ADR-0013 distinction, and modes."""
    from rag_foundry.generation.formatter import EvidenceFormatter
    from rag_foundry.generation.prompts import (
        build_decomposition_messages,
        build_qa_messages,
    )

    ws_id = uuid.uuid4()
    ctx = EvidenceFormatter().format(
        document_entries=[
            _make_entry(
                authority=KnowledgeAuthority.DOCUMENT_EVIDENCE,
                text="Access logs rotate monthly.",
                ws_id=ws_id,
            )
        ],
        assertion_entries=[
            _make_entry(
                authority=KnowledgeAuthority.CURATED,
                text="Access logs must be retained 7 years.",
                ws_id=ws_id,
            )
        ],
        mode="curated_knowledge",
    )

    std_msgs = build_qa_messages(
        "How long are logs kept?", ctx, mode="standard"
    )
    assert len(std_msgs) == 2
    assert std_msgs[0].role == "system"
    assert std_msgs[1].role == "user"
    assert "evidence_ids" in std_msgs[0].content
    assert "sufficient_evidence" in std_msgs[0].content
    assert "How long are logs kept?" in std_msgs[1].content

    cur_msgs = build_qa_messages(
        "What is the official rule?", ctx, mode="curated_knowledge"
    )
    assert "[CURATED / APPROVED]" in cur_msgs[0].content
    assert "[EXTRACTED / CANDIDATE — UNVERIFIED]" in cur_msgs[0].content

    dec_msgs = build_qa_messages(
        "Compare retention and rotation.",
        ctx,
        mode="decomposed",
        sub_answers_summary="- Sub-Q1: Retained 7 years [A1].",
    )
    assert "Sub-Q1" in dec_msgs[1].content
    assert "synthesize" in dec_msgs[0].content.lower()

    split_msgs = build_decomposition_messages(
        "Compare retention policy and encryption standards.",
        max_sub_questions=3,
    )
    assert len(split_msgs) == 2
    assert "sub_questions" in split_msgs[0].content
    assert "3" in split_msgs[0].content
