"""Curated-vs-extracted evidence formatter and context budgeting (ADR-0013)."""

import uuid
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from rag_foundry.generation.models import (
    EvidenceEntry,
    KnowledgeAuthority,
    QAMode,
)
from rag_foundry.retrieval.models import EvidenceItem, RankedChunk

CURATED_BANNER = "=== [CURATED / APPROVED] Institutional Knowledge ==="
DOCUMENT_BANNER = "=== [DOCUMENT EVIDENCE] Authorized Source Excerpts ==="
EXTRACTED_BANNER = (
    "=== [EXTRACTED / CANDIDATE — UNVERIFIED] Automated Extractions ==="
)

CURATED_TAG = "[CURATED / APPROVED]"
DOCUMENT_TAG = "[DOCUMENT EVIDENCE]"
EXTRACTED_TAG = "[EXTRACTED / CANDIDATE — UNVERIFIED]"

_EMPTY_CONTEXT_TEXT = "No authorized evidence available."


class FormattedEvidenceContext(BaseModel):
    """Deterministically labeled and budgeted evidence context for prompts."""

    model_config = ConfigDict(frozen=True)

    entries: Tuple[EvidenceEntry, ...] = Field(
        default=(),
        description="Included authorized evidence entries with final handles.",
    )
    evidence_map: Dict[str, EvidenceEntry] = Field(
        default_factory=dict,
        description="Mapping from citation handle ('E1'/'A1') to entry.",
    )
    context_text: str = Field(
        description="Formatted context string rendered into user prompts."
    )
    curated_count: int = Field(default=0, ge=0)
    extracted_count: int = Field(default=0, ge=0)
    document_count: int = Field(default=0, ge=0)
    truncated_count: int = Field(default=0, ge=0)


def _clamp_score(score: float) -> float:
    """Clamp confidence/relevance scores into [0.0, 1.0]."""
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return float(score)


def _truncate_text(text: str, max_chars: int) -> str:
    """Truncate a single evidence passage cleanly within max_chars."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    if max_chars <= 3:
        return cleaned[:max_chars]
    return cleaned[: max_chars - 3].rstrip() + "..."


def _authority_tag(authority: KnowledgeAuthority) -> str:
    """Map KnowledgeAuthority to its explicit ADR-0013 prompt tag."""
    if authority == KnowledgeAuthority.CURATED:
        return CURATED_TAG
    if authority == KnowledgeAuthority.EXTRACTED:
        return EXTRACTED_TAG
    return DOCUMENT_TAG


def _render_entry_line(entry: EvidenceEntry, max_item_chars: int) -> str:
    """Format a single evidence entry line with handle, tag, and metadata."""
    tag = _authority_tag(entry.authority)
    meta_parts: List[str] = []
    if entry.document_title:
        meta_parts.append(entry.document_title)
    if entry.section_path:
        meta_parts.append(" > ".join(entry.section_path))
    if entry.page_numbers:
        pages = ",".join(str(p) for p in entry.page_numbers)
        meta_parts.append(f"p. {pages}")
    if entry.assertion_status:
        meta_parts.append(f"status={entry.assertion_status}")
    meta_parts.append(f"confidence={entry.confidence_score:.2f}")
    meta_str = f" ({'; '.join(meta_parts)})" if meta_parts else ""
    snippet = _truncate_text(entry.text, max_item_chars)
    return f"[{entry.evidence_id}] {tag}{meta_str}: {snippet}"


class EvidenceFormatter:
    """Formats authorized evidence with deterministic handles and budgets."""

    def __init__(
        self,
        *,
        max_context_chars: int = 16000,
        max_item_chars: int = 2000,
    ) -> None:
        """Initialize the evidence formatter.

        Args:
            max_context_chars: Hard character ceiling for formatted context.
            max_item_chars: Per-item character truncation ceiling.

        Raises:
            ValueError: If budgets are non-positive.
        """
        if max_context_chars <= 0:
            raise ValueError("max_context_chars must be positive.")
        if max_item_chars <= 0:
            raise ValueError("max_item_chars must be positive.")
        self._max_context_chars = max_context_chars
        self._max_item_chars = max_item_chars

    @staticmethod
    def build_document_entries(
        ranked_chunks: Sequence[RankedChunk],
        evidence_items: Sequence[EvidenceItem] = (),
        *,
        security_domain_map: Optional[Mapping[uuid.UUID, str]] = None,
        default_security_domain: str = "general",
    ) -> List[EvidenceEntry]:
        """Bridge Phase 5 RetrievalResult objects into EvidenceEntry items.

        Args:
            ranked_chunks: Authorized ranked chunks in retrieval rank order.
            evidence_items: Optional EvidenceItem records providing titles.
            security_domain_map: Optional chunk_id -> security_domain lookup.
            default_security_domain: Fallback domain when not in map.

        Returns:
            Ordered list of DOCUMENT_EVIDENCE EvidenceEntry objects.
        """
        ev_by_chunk: Dict[uuid.UUID, EvidenceItem] = {
            item.chunk_id: item for item in evidence_items
        }
        domain_lookup = security_domain_map or {}
        entries: List[EvidenceEntry] = []

        for idx, chunk in enumerate(ranked_chunks, start=1):
            ev_item = ev_by_chunk.get(chunk.chunk_id)
            doc_title = (
                ev_item.document_title
                if ev_item is not None
                else f"Document {str(chunk.document_version_id)[:8]}"
            )
            pages = tuple(
                chunk.page_numbers
                if chunk.page_numbers
                else (ev_item.page_numbers if ev_item is not None else ())
            )
            sections = tuple(
                chunk.section_path
                if chunk.section_path
                else (ev_item.section_path if ev_item is not None else ())
            )
            bboxes = tuple(
                chunk.bounding_boxes
                if chunk.bounding_boxes
                else (ev_item.bounding_boxes if ev_item is not None else ())
            )
            domain = domain_lookup.get(chunk.chunk_id, default_security_domain)
            entries.append(
                EvidenceEntry(
                    evidence_id=f"E{idx}",
                    authority=KnowledgeAuthority.DOCUMENT_EVIDENCE,
                    text=chunk.text,
                    workspace_id=chunk.workspace_id,
                    security_domain=domain,
                    document_version_id=chunk.document_version_id,
                    document_title=doc_title,
                    chunk_id=chunk.chunk_id,
                    section_path=sections,
                    page_numbers=pages,
                    bounding_boxes=bboxes,
                    confidence_score=_clamp_score(chunk.score),
                )
            )
        return entries

    def format(
        self,
        *,
        document_entries: Sequence[EvidenceEntry] = (),
        assertion_entries: Sequence[EvidenceEntry] = (),
        mode: QAMode = "standard",
        include_extracted_candidates: bool = True,
    ) -> FormattedEvidenceContext:
        """Assign deterministic handles and render budgeted authority blocks.

        Curated assertions always appear before document evidence, and
        unverified extracted candidates are segregated into a dedicated block
        at the end (or omitted when ``include_extracted_candidates=False``).
        Entries omitted due to character budget are excluded from both
        ``entries`` and ``evidence_map`` so unseen handles cannot be cited.

        Args:
            document_entries: Authorized document evidence entries.
            assertion_entries: Authorized curated and/or extracted assertions.
            mode: Active QA mode (``standard``, ``curated_knowledge``, or
                ``decomposed``).
            include_extracted_candidates: Whether to include unapproved
                extracted assertions in the prompt context.

        Returns:
            FormattedEvidenceContext containing rendered text and handle map.
        """
        del mode  # Authority ordering is consistent & safe across all modes.

        curated_raw = [
            e
            for e in assertion_entries
            if e.authority == KnowledgeAuthority.CURATED
        ]
        extracted_raw = (
            [
                e
                for e in assertion_entries
                if e.authority == KnowledgeAuthority.EXTRACTED
            ]
            if include_extracted_candidates
            else []
        )
        doc_raw = [
            e
            for e in document_entries
            if e.authority == KnowledgeAuthority.DOCUMENT_EVIDENCE
        ]

        curated_sorted = sorted(
            curated_raw,
            key=lambda e: (
                -e.confidence_score,
                str(e.assertion_id or ""),
                e.text,
            ),
        )
        extracted_sorted = sorted(
            extracted_raw,
            key=lambda e: (
                -e.confidence_score,
                str(e.assertion_id or ""),
                e.text,
            ),
        )

        # Assign deterministic handles: A1..An for assertions, E1..En for docs.
        a_idx = 1
        curated_labeled: List[EvidenceEntry] = []
        for item in curated_sorted:
            curated_labeled.append(
                item.model_copy(update={"evidence_id": f"A{a_idx}"})
            )
            a_idx += 1

        extracted_labeled: List[EvidenceEntry] = []
        for item in extracted_sorted:
            extracted_labeled.append(
                item.model_copy(update={"evidence_id": f"A{a_idx}"})
            )
            a_idx += 1

        doc_labeled: List[EvidenceEntry] = []
        for e_idx, item in enumerate(doc_raw, start=1):
            doc_labeled.append(
                item.model_copy(update={"evidence_id": f"E{e_idx}"})
            )

        sections: List[Tuple[str, List[EvidenceEntry]]] = [
            (CURATED_BANNER, curated_labeled),
            (DOCUMENT_BANNER, doc_labeled),
            (EXTRACTED_BANNER, extracted_labeled),
        ]

        rendered_sections: List[str] = []
        included: List[EvidenceEntry] = []
        total_len = 0
        truncated_count = 0

        for banner, items in sections:
            if not items:
                continue

            sec_sep = 2 if rendered_sections else 0
            sec_lines: List[str] = []
            sec_len = len(banner)

            for item in items:
                line = _render_entry_line(item, self._max_item_chars)
                projected = total_len + sec_sep + sec_len + 1 + len(line)
                if projected <= self._max_context_chars:
                    sec_lines.append(line)
                    sec_len += 1 + len(line)
                    included.append(item)
                else:
                    truncated_count += 1

            if sec_lines:
                block = "\n".join([banner, *sec_lines])
                rendered_sections.append(block)
                total_len += sec_sep + len(block)

        if not included:
            return FormattedEvidenceContext(
                entries=(),
                evidence_map={},
                context_text=_EMPTY_CONTEXT_TEXT,
                curated_count=0,
                extracted_count=0,
                document_count=0,
                truncated_count=truncated_count,
            )

        context_text = "\n\n".join(rendered_sections)
        evidence_map = {entry.evidence_id: entry for entry in included}
        curated_count = sum(
            1 for e in included if e.authority == KnowledgeAuthority.CURATED
        )
        extracted_count = sum(
            1 for e in included if e.authority == KnowledgeAuthority.EXTRACTED
        )
        document_count = sum(
            1
            for e in included
            if e.authority == KnowledgeAuthority.DOCUMENT_EVIDENCE
        )

        return FormattedEvidenceContext(
            entries=tuple(included),
            evidence_map=evidence_map,
            context_text=context_text,
            curated_count=curated_count,
            extracted_count=extracted_count,
            document_count=document_count,
            truncated_count=truncated_count,
        )
