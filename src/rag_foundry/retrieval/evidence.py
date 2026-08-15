"""Evidence citation assembly and low-confidence abstention engine (ADR-0016)."""

import uuid
from typing import Dict, List, Optional

from rag_foundry.retrieval.models import (
    AbstentionResult,
    EvidenceItem,
    RankedChunk,
)


class EvidenceAssembler:
    """Transforms retrieved and reranked chunks into structured, grounded evidence items."""

    def __init__(self, doc_titles: Optional[Dict[uuid.UUID, str]] = None) -> None:
        """Initialize EvidenceAssembler.

        Args:
            doc_titles: Optional mapping of document_version_id to human-readable title.
        """
        self.doc_titles = doc_titles or {}

    def _format_attribution_tag(
        self,
        doc_title: str,
        page_numbers: List[int],
        section_path: List[str],
    ) -> str:
        """Format standardized citation tag for prompt grounding."""
        parts = [f"Doc: {doc_title}"]
        if page_numbers:
            pages_str = ",".join(str(p) for p in sorted(set(page_numbers)))
            parts.append(f"p.{pages_str}")
        elif section_path:
            parts.append(f"Sec: {' > '.join(section_path[:2])}")
        return f"[{', '.join(parts)}]"

    def assemble_evidence(
        self, ranked_chunks: List[RankedChunk]
    ) -> List[EvidenceItem]:
        """Assemble structured EvidenceItem instances with citation metadata.

        Args:
            ranked_chunks: List of ranked and scored candidate chunks.

        Returns:
            List of EvidenceItem citation records.
        """
        evidence_items: List[EvidenceItem] = []

        for chunk in ranked_chunks:
            title = self.doc_titles.get(
                chunk.document_version_id, "Institutional Document"
            )
            attribution_tag = self._format_attribution_tag(
                doc_title=title,
                page_numbers=chunk.page_numbers,
                section_path=chunk.section_path,
            )

            evidence_items.append(
                EvidenceItem(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_version_id,
                    document_title=title,
                    snippet=chunk.text[:300].strip(),
                    confidence_score=chunk.score,
                    page_numbers=chunk.page_numbers,
                    section_path=chunk.section_path,
                    bounding_boxes=chunk.bounding_boxes,
                    attribution_tag=attribution_tag,
                )
            )

        return evidence_items


class AbstentionEngine:
    """Evaluates evidence quality and signals explicit abstention when confidence is insufficient."""

    def evaluate_abstention(
        self,
        ranked_chunks: List[RankedChunk],
        threshold: float = 0.0,
    ) -> AbstentionResult:
        """Evaluate if retrieval results warrant explicit abstention.

        Args:
            ranked_chunks: Retrieved candidate chunks.
            threshold: Minimum acceptable confidence score.

        Returns:
            AbstentionResult indicating if and why abstention occurred.
        """
        if not ranked_chunks:
            return AbstentionResult(
                abstained=True,
                reason="No matching evidence chunks found matching query criteria.",
                threshold=threshold,
                highest_score=0.0,
            )

        highest = max(chunk.score for chunk in ranked_chunks)
        if threshold > 0.0 and highest < threshold:
            return AbstentionResult(
                abstained=True,
                reason=(
                    f"Highest retrieved candidate relevance score ({highest:.2f}) "
                    f"is below threshold ({threshold:.2f})."
                ),
                threshold=threshold,
                highest_score=highest,
            )

        return AbstentionResult(
            abstained=False,
            threshold=threshold,
            highest_score=highest,
        )
