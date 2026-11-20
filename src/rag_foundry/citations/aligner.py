"""Deterministic claim-to-passage alignment and span resolution (ADR-0020)."""

import re
from typing import List, Mapping, Optional, Sequence, Set, Tuple

from rag_foundry.citations.models import ClaimAlignmentResult, SourceSpan
from rag_foundry.generation.models import (
    AnswerClaim,
    ClaimAuthority,
    EvidenceEntry,
    KnowledgeAuthority,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")

_NUMBER_WORDS: Mapping[str, str] = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
}

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "must",
        "of",
        "on",
        "or",
        "shall",
        "should",
        "that",
        "the",
        "their",
        "there",
        "these",
        "this",
        "to",
        "was",
        "were",
        "which",
        "will",
        "with",
    }
)


def _normalize_token(token: str) -> str:
    """Normalize spelled-out numbers and lightweight plural suffixes."""
    low = token.lower()
    if low in _NUMBER_WORDS:
        return _NUMBER_WORDS[low]
    if len(low) > 4 and low.endswith("ies"):
        return low[:-3] + "y"
    if len(low) > 4 and low.endswith("s") and not low.endswith("ss"):
        return low[:-1]
    return low


def _extract_content_tokens(text: str) -> List[str]:
    """Extract ordered, normalized non-stopword content tokens."""
    raw_tokens = _TOKEN_RE.findall(text.lower())
    result: List[str] = []
    for tok in raw_tokens:
        if tok in _STOPWORDS:
            continue
        norm = _normalize_token(tok)
        if norm and norm not in _STOPWORDS:
            result.append(norm)
    return result


def _extract_numeric_tokens(tokens: Sequence[str]) -> Set[str]:
    """Return all normalized numeric tokens present in a token sequence."""
    return {tok for tok in tokens if _NUMBER_RE.match(tok)}


def _token_matches(token: str, evidence_tokens: Set[str]) -> bool:
    """Match exact normalized tokens or shared >=5-char morphological stems."""
    if token in evidence_tokens:
        return True
    if _NUMBER_RE.match(token) or len(token) < 5:
        return False
    prefix = token[:5]
    return any(
        ev_tok.startswith(prefix) and not _NUMBER_RE.match(ev_tok)
        for ev_tok in evidence_tokens
    )


def derive_effective_authority(
    entries: Sequence[EvidenceEntry],
) -> Optional[ClaimAuthority]:
    """Derive effective claim authority from cited EvidenceEntry objects.

    Args:
        entries: Resolved EvidenceEntry objects cited by a claim.

    Returns:
        ``"curated"``, ``"extracted"``, ``"document_evidence"``, ``"mixed"``,
        or ``None`` when ``entries`` is empty.
    """
    if not entries:
        return None
    authorities = {entry.authority for entry in entries}
    if len(authorities) > 1:
        return "mixed"
    sole = next(iter(authorities))
    if sole == KnowledgeAuthority.CURATED:
        return "curated"
    if sole == KnowledgeAuthority.EXTRACTED:
        return "extracted"
    return "document_evidence"


def resolve_source_span(entry: EvidenceEntry) -> SourceSpan:
    """Resolve and verify source provenance metadata for an EvidenceEntry.

    Args:
        entry: Candidate EvidenceEntry to inspect.

    Returns:
        SourceSpan recording provenance IDs, page/box spans, and resolvability.
    """
    has_invalid_page = any(p <= 0 for p in entry.page_numbers)

    if entry.authority == KnowledgeAuthority.DOCUMENT_EVIDENCE:
        resolvable = (
            entry.document_version_id is not None
            and entry.chunk_id is not None
            and not has_invalid_page
        )
    elif entry.authority == KnowledgeAuthority.CURATED:
        has_chunk_provenance = (
            bool(entry.source_chunk_ids)
            and entry.document_version_id is not None
        )
        is_steward_curated_rule = (
            entry.assertion_origin == "curated"
            and entry.assertion_status == "approved"
        )
        resolvable = (
            entry.assertion_id is not None
            and (has_chunk_provenance or is_steward_curated_rule)
            and not has_invalid_page
        )
    else:
        # Extracted candidates MUST resolve to backing chunk & document version
        resolvable = (
            entry.assertion_id is not None
            and bool(entry.source_chunk_ids)
            and entry.document_version_id is not None
            and not has_invalid_page
        )

    return SourceSpan(
        evidence_id=entry.evidence_id,
        document_version_id=entry.document_version_id,
        chunk_id=entry.chunk_id,
        assertion_id=entry.assertion_id,
        section_path=entry.section_path,
        page_numbers=entry.page_numbers,
        bounding_boxes=entry.bounding_boxes,
        resolvable=resolvable,
    )


class CitationAligner:
    """Computes deterministic lexical/phrase claim-to-passage support scores."""

    def score_claim_against_entries(
        self,
        claim_text: str,
        entries: Sequence[EvidenceEntry],
    ) -> Tuple[float, bool]:
        """Compute deterministic support score and numeric-mismatch flag.

        Combines key-token recall (80% weight) with content-bigram phrase
        overlap (20% weight), and penalizes explicit numbers asserted in the
        claim that are absent from all cited passages.

        Args:
            claim_text: Factual claim text to verify.
            entries: Cited EvidenceEntry passages.

        Returns:
            Tuple of ``(support_score, numeric_mismatch)``.
        """
        if not entries:
            return 0.0, False

        claim_tokens = _extract_content_tokens(claim_text)
        if not claim_tokens:
            return 0.0, False

        combined_evidence = " ".join(entry.text for entry in entries)
        evidence_token_list = _extract_content_tokens(combined_evidence)
        evidence_token_set = set(evidence_token_list)

        if not evidence_token_set:
            return 0.0, False

        unique_claim_tokens = list(dict.fromkeys(claim_tokens))
        matched = sum(
            1
            for tok in unique_claim_tokens
            if _token_matches(tok, evidence_token_set)
        )
        token_recall = matched / len(unique_claim_tokens)

        if len(claim_tokens) >= 2 and len(evidence_token_list) >= 2:
            claim_bigrams = [
                (claim_tokens[i], claim_tokens[i + 1])
                for i in range(len(claim_tokens) - 1)
            ]
            ev_bigrams = {
                (evidence_token_list[i], evidence_token_list[i + 1])
                for i in range(len(evidence_token_list) - 1)
            }
            bigram_hits = sum(1 for bg in claim_bigrams if bg in ev_bigrams)
            bigram_recall = bigram_hits / len(claim_bigrams)
            score = 0.80 * token_recall + 0.20 * bigram_recall
        else:
            score = token_recall

        claim_nums = _extract_numeric_tokens(claim_tokens)
        ev_nums = _extract_numeric_tokens(evidence_token_list)
        numeric_mismatch = bool(claim_nums and not claim_nums.issubset(ev_nums))
        if numeric_mismatch:
            score *= 0.35

        return round(min(1.0, max(0.0, score)), 4), numeric_mismatch

    def align_claim(
        self,
        claim: AnswerClaim,
        evidence_map: Mapping[str, EvidenceEntry],
        *,
        claim_index: int = 0,
        min_support_score: float = 0.25,
    ) -> ClaimAlignmentResult:
        """Align a single AnswerClaim against supplied EvidenceEntry handles.

        Args:
            claim: Candidate AnswerClaim produced by the model.
            evidence_map: Supplied handle -> EvidenceEntry map.
            claim_index: Zero-based claim position for diagnostics.
            min_support_score: Minimum support score threshold.

        Returns:
            ClaimAlignmentResult with score, spans, and derived authority.
        """
        matched_entries: List[EvidenceEntry] = []
        matched_ids: List[str] = []
        missing_ids: List[str] = []

        for eid in claim.evidence_ids:
            entry = evidence_map.get(eid)
            if entry is None:
                missing_ids.append(eid)
            else:
                matched_entries.append(entry)
                matched_ids.append(eid)

        spans = tuple(resolve_source_span(e) for e in matched_entries)
        effective_auth = derive_effective_authority(matched_entries)
        score, numeric_mismatch = self.score_claim_against_entries(
            claim.text, matched_entries
        )

        supported = (
            bool(matched_entries)
            and not missing_ids
            and not numeric_mismatch
            and score >= min_support_score
        )
        updated_claim = claim.model_copy(
            update={
                "authority": effective_auth,
                "support_score": score,
                "verified": supported,
            }
        )

        return ClaimAlignmentResult(
            claim_index=claim_index,
            claim=updated_claim,
            matched_evidence_ids=tuple(matched_ids),
            missing_evidence_ids=tuple(missing_ids),
            resolved_spans=spans,
            effective_authority=effective_auth,
            support_score=score,
            numeric_mismatch=numeric_mismatch,
            supported=supported,
        )

    def align_claims(
        self,
        claims: Sequence[AnswerClaim],
        evidence_map: Mapping[str, EvidenceEntry],
        *,
        min_support_score: float = 0.25,
    ) -> Tuple[ClaimAlignmentResult, ...]:
        """Align an ordered sequence of AnswerClaims against supplied handles.

        Args:
            claims: Candidate AnswerClaim sequence.
            evidence_map: Supplied handle -> EvidenceEntry map.
            min_support_score: Minimum support score threshold.

        Returns:
            Tuple of ClaimAlignmentResult in original claim order.
        """
        return tuple(
            self.align_claim(
                claim,
                evidence_map,
                claim_index=idx,
                min_support_score=min_support_score,
            )
            for idx, claim in enumerate(claims)
        )
