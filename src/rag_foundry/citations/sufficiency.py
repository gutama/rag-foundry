"""Post-generation SufficiencyGate for warnings, stripping, and abstention."""

import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from rag_foundry.citations.models import (
    CitationValidationPolicy,
    CitationValidationReport,
)
from rag_foundry.generation.models import (
    AnswerClaim,
    EvidenceEntry,
    GroundedAnswer,
    KnowledgeAuthority,
    ParsedAnswerPayload,
    QAMode,
)
from rag_foundry.retrieval.models import AbstentionResult

_DEFAULT_ABSTENTION_PREFIX = "Insufficient verified evidence to answer."


def _append_unique(items: List[str], message: str) -> None:
    """Append a non-empty limitation string without duplicates."""
    cleaned = message.strip()
    if cleaned and cleaned not in items:
        items.append(cleaned)


def _format_invalid_citation_reason(report: CitationValidationReport) -> str:
    """Summarize invalid, unauthorized, superseded, or broken handles."""
    parts: List[str] = []
    if report.invalid_citation_ids:
        joined = ", ".join(report.invalid_citation_ids)
        parts.append(f"unknown citation IDs ({joined})")
    if report.unauthorized_citation_ids:
        joined = ", ".join(report.unauthorized_citation_ids)
        parts.append(f"unauthorized citations ({joined})")
    if report.superseded_citation_ids:
        joined = ", ".join(report.superseded_citation_ids)
        parts.append(f"superseded document revisions ({joined})")
    if report.unresolvable_span_ids:
        joined = ", ".join(report.unresolvable_span_ids)
        parts.append(f"unresolvable source spans ({joined})")
    detail = "; ".join(parts) if parts else "citation policy violations"
    return f"Citation validation rejected response due to {detail}."


def _render_claims_answer(claims: Sequence[AnswerClaim]) -> str:
    """Reconstruct grounded answer prose solely from verified claims."""
    segments: List[str] = []
    for claim in claims:
        text = claim.text.strip().rstrip(".")
        tags = " ".join(f"[{eid}]" for eid in claim.evidence_ids)
        if tags:
            segments.append(f"{text} {tags}.")
        else:
            segments.append(f"{text}.")
    return " ".join(segments)


def _collect_citations(
    claims: Sequence[AnswerClaim],
    evidence_map: Mapping[str, EvidenceEntry],
) -> Tuple[EvidenceEntry, ...]:
    """Collect deduplicated EvidenceEntry citations referenced by claims."""
    seen: set[str] = set()
    citations: List[EvidenceEntry] = []
    for claim in claims:
        for eid in claim.evidence_ids:
            if eid in seen:
                continue
            entry = evidence_map.get(eid)
            if entry is not None:
                seen.add(eid)
                citations.append(entry)
    return tuple(citations)


class SufficiencyGate:
    """Applies ADR-0020 & ADR-0013 gating to produce a final GroundedAnswer.

    Evaluates retrieval abstention, strict parse failures, citation validity,
    authority misrepresentation, supported-claim ratio, and extracted-only
    policies to either emit an explicit abstention or return a grounded answer
    with verified provenance and explicit limitations.
    """

    def evaluate(
        self,
        *,
        payload: Optional[ParsedAnswerPayload],
        report: Optional[CitationValidationReport],
        evidence_map: Mapping[str, EvidenceEntry],
        policy: Optional[CitationValidationPolicy] = None,
        retrieval_abstention: Optional[AbstentionResult] = None,
        qa_mode: QAMode = "standard",
        semantic_profile_id: Optional[uuid.UUID] = None,
        model_profile_id: Optional[str] = None,
        model_profile_version: Optional[str] = None,
        execution_metrics: Optional[Dict[str, Any]] = None,
        parse_error: Optional[str] = None,
    ) -> GroundedAnswer:
        """Evaluate validation results and build the final GroundedAnswer.

        Args:
            payload: Strictly parsed model answer payload (or None on error).
            report: Post-generation CitationValidationReport (or None).
            evidence_map: Authorized handle -> EvidenceEntry map.
            policy: Optional CitationValidationPolicy (uses strict defaults).
            retrieval_abstention: Optional upstream RetrievalPipeline decision.
            qa_mode: Active QA mode (``standard``, ``curated_knowledge``, or
                ``decomposed``).
            semantic_profile_id: Optional active semantic profile UUID.
            model_profile_id: Executed approved ModelProfile ID.
            model_profile_version: Executed ModelProfile version.
            execution_metrics: Reproducibility and latency trace dictionary.
            parse_error: Optional strict JSON parser error message.

        Returns:
            Final governed GroundedAnswer (either verified or abstained).
        """
        active_policy = policy or CitationValidationPolicy()
        metrics = dict(execution_metrics or {})

        def _abstain(
            reason: str,
            extra_limitations: Sequence[str] = (),
        ) -> GroundedAnswer:
            lims: List[str] = list(extra_limitations)
            _append_unique(lims, reason)
            return GroundedAnswer(
                answer=f"{_DEFAULT_ABSTENTION_PREFIX} {reason}",
                claims=(),
                citations=(),
                limitations=tuple(lims),
                sufficient_evidence=False,
                abstained=True,
                abstention_reason=reason,
                qa_mode=qa_mode,
                semantic_profile_id=semantic_profile_id,
                model_profile_id=model_profile_id,
                model_profile_version=model_profile_version,
                validation_report=report,
                execution_metrics=metrics,
            )

        # 1. Propagate upstream retrieval abstention immediately.
        if retrieval_abstention is not None and retrieval_abstention.abstained:
            reason = (
                retrieval_abstention.reason
                or "Retrieved evidence did not meet minimum confidence."
            )
            return _abstain(reason)

        # 2. Fail closed on malformed/unparsed model output.
        if parse_error is not None:
            return _abstain(
                f"Model response failed structured parsing: {parse_error}"
            )
        if payload is None or report is None:
            return _abstain(
                "No validated model answer was produced for the request."
            )

        # 3. Respect model self-reported insufficient evidence.
        if not payload.sufficient_evidence:
            reason = (
                payload.limitations[0]
                if payload.limitations
                else "Supplied authorized evidence does not answer the query."
            )
            return _abstain(reason, extra_limitations=payload.limitations)

        # 4. Fail closed on fabricated, unauthorized, superseded, or broken IDs.
        if (
            active_policy.reject_invalid_citation_ids
            and report.has_invalid_citations
        ):
            return _abstain(
                _format_invalid_citation_reason(report),
                extra_limitations=payload.limitations,
            )

        # 5. Fail closed on curated-vs-extracted misrepresentation (ADR-0013).
        if (
            active_policy.reject_authority_misrepresentation
            and report.authority_misrepresentation_indices
        ):
            return _abstain(
                "Response misrepresented non-curated or extracted candidate "
                "evidence as steward-curated institutional truth.",
                extra_limitations=payload.limitations,
            )

        # 6. Fail closed when citations are required but zero claims exist.
        if active_policy.require_claim_citations and (
            report.total_claim_count == 0
        ):
            return _abstain(
                "Model produced no verifiable factual claims linked to "
                "authorized evidence.",
                extra_limitations=payload.limitations,
            )

        supported_claims = [
            res.claim for res in report.claim_results if res.supported
        ]
        unsupported_claims = [
            res.claim for res in report.claim_results if not res.supported
        ]
        all_annotated_claims = [res.claim for res in report.claim_results]
        ratio_ok = (
            report.supported_claim_ratio
            >= active_policy.min_supported_claim_ratio
        )

        limitations: List[str] = list(payload.limitations)
        final_claims: Tuple[AnswerClaim, ...]
        final_answer_text = payload.answer
        sufficient = ratio_ok

        # 7. Apply configured unsupported_claim_action policy.
        if unsupported_claims or not ratio_ok:
            action = active_policy.unsupported_claim_action
            if action == "abstain":
                reason = (
                    f"Only {report.supported_claim_count} of "
                    f"{report.total_claim_count} claim(s) passed citation "
                    f"verification (ratio {report.supported_claim_ratio:.2f} "
                    f"< required "
                    f"{active_policy.min_supported_claim_ratio:.2f} or "
                    "unsupported claims present)."
                )
                return _abstain(reason, extra_limitations=limitations)

            if action == "strip_and_warn":
                if not supported_claims:
                    return _abstain(
                        "All generated claims failed citation verification "
                        "and were removed.",
                        extra_limitations=limitations,
                    )
                final_claims = tuple(supported_claims)
                final_answer_text = _render_claims_answer(final_claims)
                _append_unique(
                    limitations,
                    f"Removed {len(unsupported_claims)} unsupported claim(s) "
                    "that failed citation alignment or confidence checks.",
                )
            else:
                # action == "warn"
                final_claims = tuple(all_annotated_claims)
                _append_unique(
                    limitations,
                    f"Warning: {len(unsupported_claims)} unsupported claim(s) "
                    "remain unverified against the cited evidence.",
                )
        else:
            final_claims = tuple(supported_claims)

        # 8. Resolve authorized citations & enforce ADR-0013 authority rules.
        citations = _collect_citations(final_claims, evidence_map)
        authorities = {entry.authority for entry in citations}

        if (
            authorities == {KnowledgeAuthority.EXTRACTED}
            and not active_policy.allow_extracted_only_answers
        ):
            return _abstain(
                "Policy prohibits answering solely from unapproved extracted "
                "candidate assertions without curated or document evidence.",
                extra_limitations=limitations,
            )

        if (
            KnowledgeAuthority.EXTRACTED in authorities
            and active_policy.disclose_extracted_knowledge
        ):
            if authorities == {KnowledgeAuthority.EXTRACTED}:
                _append_unique(
                    limitations,
                    "Unverified candidate knowledge notice: This answer "
                    "relies solely on unapproved extracted assertions rather "
                    "than steward-curated facts.",
                )
            else:
                _append_unique(
                    limitations,
                    "Mixed authority notice: One or more claims rely on "
                    "unapproved extracted candidate assertions alongside "
                    "curated or document evidence.",
                )

        if (
            qa_mode == "curated_knowledge"
            and KnowledgeAuthority.CURATED not in authorities
        ):
            _append_unique(
                limitations,
                "No steward-curated assertions were available for this "
                "answer; response relies on document or candidate evidence.",
            )

        return GroundedAnswer(
            answer=final_answer_text,
            claims=final_claims,
            citations=citations,
            limitations=tuple(limitations),
            sufficient_evidence=sufficient,
            abstained=False,
            abstention_reason=None,
            qa_mode=qa_mode,
            semantic_profile_id=semantic_profile_id,
            model_profile_id=model_profile_id,
            model_profile_version=model_profile_version,
            validation_report=report,
            execution_metrics=metrics,
        )
