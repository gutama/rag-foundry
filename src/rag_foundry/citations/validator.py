"""Fail-closed post-generation CitationValidator (ADR-0020 & ADR-0013)."""

import re
import uuid
from typing import Collection, Dict, List, Mapping, Optional, Set, Tuple

from rag_foundry.citations.aligner import (
    CitationAligner,
    derive_effective_authority,
    resolve_source_span,
)
from rag_foundry.citations.models import (
    CitationIssue,
    CitationValidationPolicy,
    CitationValidationReport,
    ClaimAlignmentResult,
)
from rag_foundry.generation.models import (
    EvidenceEntry,
    ParsedAnswerPayload,
)
from rag_foundry.retrieval.security import SecurityContext

_INLINE_HANDLE_RE = re.compile(r"\[([EA]\d+)\]")


def _append_unique(items: List[str], value: str) -> None:
    """Append string to list preserving order without duplicates."""
    if value not in items:
        items.append(value)


class CitationValidator:
    """Validates every cited handle and factual claim after generation.

    Enforces ADR-0020 and ADR-0013 fail-closed invariants:
    - Existence: every cited handle (in claims or inline answer text) must
      exist in the supplied ``evidence_map``.
    - Authorization: every cited entry must pass ``SecurityContext`` checks
      for ``workspace_id`` and ALL ``security_domains``.
    - Revision freshness: cited ``document_version_id`` values must match
      active revisions (and must not appear in superseded sets).
    - Source span resolvability: every cited entry must resolve to valid
      chunk/document or curated-assertion provenance.
    - Curated-vs-extracted integrity: models cannot claim ``curated``
      authority from ``extracted``-only or non-curated evidence.
    - Claim-to-passage support: every claim must meet alignment & confidence
      thresholds without fabricated numeric distortions.
    """

    def __init__(
        self,
        aligner: Optional[CitationAligner] = None,
    ) -> None:
        """Initialize CitationValidator with an optional CitationAligner.

        Args:
            aligner: Optional CitationAligner instance.
        """
        self._aligner = aligner or CitationAligner()

    def validate(
        self,
        *,
        payload: ParsedAnswerPayload,
        evidence_map: Mapping[str, EvidenceEntry],
        security_context: SecurityContext,
        policy: Optional[CitationValidationPolicy] = None,
        active_document_version_ids: Optional[Collection[uuid.UUID]] = None,
        superseded_document_version_ids: Optional[
            Collection[uuid.UUID]
        ] = None,
    ) -> CitationValidationReport:
        """Run full post-generation citation and claim validation.

        Args:
            payload: Strictly parsed model answer payload.
            evidence_map: Authorized handle -> EvidenceEntry map supplied to
                the model.
            security_context: Caller SecurityContext for revalidation.
            policy: Optional CitationValidationPolicy (uses strict defaults).
            active_document_version_ids: Optional allowlist of active
                document version UUIDs.
            superseded_document_version_ids: Optional denylist of superseded
                document version UUIDs.

        Returns:
            Complete CitationValidationReport with claim results and issues.
        """
        active_policy = policy or CitationValidationPolicy()
        active_set: Optional[Set[uuid.UUID]] = (
            set(active_document_version_ids)
            if active_document_version_ids is not None
            else None
        )
        superseded_set: Set[uuid.UUID] = (
            set(superseded_document_version_ids)
            if superseded_document_version_ids is not None
            else set()
        )

        issues: List[CitationIssue] = []
        invalid_ids: List[str] = []
        unauthorized_ids: List[str] = []
        superseded_ids: List[str] = []
        unresolvable_ids: List[str] = []
        misrep_indices: List[int] = []

        # Validate inline handles referenced in answer prose.
        inline_handles = list(
            dict.fromkeys(_INLINE_HANDLE_RE.findall(payload.answer))
        )
        for handle in inline_handles:
            self._validate_single_handle(
                handle=handle,
                claim_index=None,
                evidence_map=evidence_map,
                security_context=security_context,
                policy=active_policy,
                active_set=active_set,
                superseded_set=superseded_set,
                issues=issues,
                invalid_ids=invalid_ids,
                unauthorized_ids=unauthorized_ids,
                superseded_ids=superseded_ids,
                unresolvable_ids=unresolvable_ids,
            )

        claim_results: List[ClaimAlignmentResult] = []
        verified_entries: List[EvidenceEntry] = []

        for idx, claim in enumerate(payload.claims):
            if active_policy.require_claim_citations and not claim.evidence_ids:
                sev = (
                    "error"
                    if active_policy.unsupported_claim_action == "abstain"
                    else "warning"
                )
                issues.append(
                    CitationIssue(
                        code="missing_claim_citation",
                        severity=sev,
                        message=(
                            f"Claim {idx} does not cite any evidence handle."
                        ),
                        claim_index=idx,
                    )
                )

            valid_claim_map: Dict[str, EvidenceEntry] = {}
            claim_has_handle_error = False

            for handle in claim.evidence_ids:
                entry = self._validate_single_handle(
                    handle=handle,
                    claim_index=idx,
                    evidence_map=evidence_map,
                    security_context=security_context,
                    policy=active_policy,
                    active_set=active_set,
                    superseded_set=superseded_set,
                    issues=issues,
                    invalid_ids=invalid_ids,
                    unauthorized_ids=unauthorized_ids,
                    superseded_ids=superseded_ids,
                    unresolvable_ids=unresolvable_ids,
                )
                if entry is None:
                    claim_has_handle_error = True
                else:
                    valid_claim_map[handle] = entry

            aligned = self._aligner.align_claim(
                claim,
                valid_claim_map,
                claim_index=idx,
                min_support_score=active_policy.min_claim_support_score,
            )

            claim_supported = aligned.supported and not claim_has_handle_error

            # Check curated-vs-extracted misrepresentation (ADR-0013).
            if (
                claim.claimed_authority == "curated"
                and aligned.effective_authority is not None
                and aligned.effective_authority != "curated"
            ):
                misrep_indices.append(idx)
                sev = (
                    "error"
                    if active_policy.reject_authority_misrepresentation
                    else "warning"
                )
                issues.append(
                    CitationIssue(
                        code="authority_misrepresentation",
                        severity=sev,
                        message=(
                            f"Claim {idx} claimed 'curated' authority but "
                            f"cited '{aligned.effective_authority}' evidence."
                        ),
                        claim_index=idx,
                    )
                )
                if active_policy.reject_authority_misrepresentation:
                    claim_supported = False

            # Check evidence confidence floor on valid cited entries.
            valid_entries = list(valid_claim_map.values())
            if (
                valid_entries
                and active_policy.min_evidence_confidence > 0.0
                and max(e.confidence_score for e in valid_entries)
                < active_policy.min_evidence_confidence
            ):
                issues.append(
                    CitationIssue(
                        code="low_evidence_confidence",
                        severity=(
                            "error"
                            if active_policy.unsupported_claim_action
                            == "abstain"
                            else "warning"
                        ),
                        message=(
                            f"Claim {idx} relies solely on evidence below "
                            "confidence threshold "
                            f"{active_policy.min_evidence_confidence:.2f}."
                        ),
                        claim_index=idx,
                    )
                )
                claim_supported = False

            # Record alignment/numeric support diagnostics.
            if valid_entries and aligned.numeric_mismatch:
                issues.append(
                    CitationIssue(
                        code="numeric_mismatch",
                        severity=(
                            "error"
                            if active_policy.unsupported_claim_action
                            == "abstain"
                            else "warning"
                        ),
                        message=(
                            f"Claim {idx} contains numbers not found in "
                            "cited evidence."
                        ),
                        claim_index=idx,
                    )
                )
                claim_supported = False
            elif (
                valid_entries
                and aligned.support_score
                < active_policy.min_claim_support_score
            ):
                issues.append(
                    CitationIssue(
                        code="unsupported_claim",
                        severity=(
                            "error"
                            if active_policy.unsupported_claim_action
                            == "abstain"
                            else "warning"
                        ),
                        message=(
                            f"Claim {idx} support score "
                            f"({aligned.support_score:.2f}) is below minimum "
                            f"{active_policy.min_claim_support_score:.2f}."
                        ),
                        claim_index=idx,
                    )
                )
                claim_supported = False

            final_claim = aligned.claim.model_copy(
                update={"verified": claim_supported}
            )
            final_result = aligned.model_copy(
                update={"claim": final_claim, "supported": claim_supported}
            )
            claim_results.append(final_result)
            if claim_supported:
                verified_entries.extend(valid_entries)

        total_claims = len(claim_results)
        supported_claims = sum(1 for r in claim_results if r.supported)
        ratio = (
            round(supported_claims / total_claims, 4)
            if total_claims > 0
            else 0.0
        )

        curated_cnt = sum(
            1 for r in claim_results if r.effective_authority == "curated"
        )
        extracted_cnt = sum(
            1 for r in claim_results if r.effective_authority == "extracted"
        )
        document_cnt = sum(
            1
            for r in claim_results
            if r.effective_authority == "document_evidence"
        )
        mixed_cnt = sum(
            1 for r in claim_results if r.effective_authority == "mixed"
        )

        effective_answer_auth = derive_effective_authority(verified_entries)
        has_invalid = bool(
            invalid_ids
            or unauthorized_ids
            or superseded_ids
            or unresolvable_ids
        )
        passed = not any(issue.severity == "error" for issue in issues)

        return CitationValidationReport(
            passed=passed,
            claim_results=tuple(claim_results),
            issues=tuple(issues),
            invalid_citation_ids=tuple(invalid_ids),
            unauthorized_citation_ids=tuple(unauthorized_ids),
            superseded_citation_ids=tuple(superseded_ids),
            unresolvable_span_ids=tuple(unresolvable_ids),
            authority_misrepresentation_indices=tuple(misrep_indices),
            supported_claim_count=supported_claims,
            total_claim_count=total_claims,
            supported_claim_ratio=ratio,
            curated_claim_count=curated_cnt,
            extracted_claim_count=extracted_cnt,
            document_claim_count=document_cnt,
            mixed_claim_count=mixed_cnt,
            effective_answer_authority=effective_answer_auth,
            has_invalid_citations=has_invalid,
        )

    @staticmethod
    def _validate_single_handle(
        *,
        handle: str,
        claim_index: Optional[int],
        evidence_map: Mapping[str, EvidenceEntry],
        security_context: SecurityContext,
        policy: CitationValidationPolicy,
        active_set: Optional[Set[uuid.UUID]],
        superseded_set: Set[uuid.UUID],
        issues: List[CitationIssue],
        invalid_ids: List[str],
        unauthorized_ids: List[str],
        superseded_ids: List[str],
        unresolvable_ids: List[str],
    ) -> Optional[EvidenceEntry]:
        """Validate existence, ACL, revision, and span for one handle."""
        entry = evidence_map.get(handle)
        if entry is None:
            _append_unique(invalid_ids, handle)
            issues.append(
                CitationIssue(
                    code="unknown_citation_id",
                    severity="error",
                    message=(
                        f"Citation handle '{handle}' was not supplied in "
                        "authorized evidence."
                    ),
                    claim_index=claim_index,
                    evidence_id=handle,
                )
            )
            return None

        ok = True
        if not security_context.can_access_workspace(entry.workspace_id):
            _append_unique(unauthorized_ids, handle)
            issues.append(
                CitationIssue(
                    code="unauthorized_workspace",
                    severity="error",
                    message=(
                        f"Citation '{handle}' belongs to unauthorized "
                        f"workspace '{entry.workspace_id}'."
                    ),
                    claim_index=claim_index,
                    evidence_id=handle,
                )
            )
            ok = False

        denied_domains = [
            dom
            for dom in entry.security_domains
            if not security_context.can_access_domain(dom)
        ]
        if denied_domains:
            _append_unique(unauthorized_ids, handle)
            issues.append(
                CitationIssue(
                    code="unauthorized_security_domain",
                    severity="error",
                    message=(
                        f"Citation '{handle}' requires unauthorized "
                        f"security domain(s): {', '.join(denied_domains)}."
                    ),
                    claim_index=claim_index,
                    evidence_id=handle,
                )
            )
            ok = False

        if policy.enforce_revision_check and entry.document_version_id:
            doc_ver = entry.document_version_id
            is_superseded = (
                active_set is not None and doc_ver not in active_set
            ) or (doc_ver in superseded_set)
            if is_superseded:
                _append_unique(superseded_ids, handle)
                issues.append(
                    CitationIssue(
                        code="superseded_document_revision",
                        severity="error",
                        message=(
                            f"Citation '{handle}' references superseded "
                            f"document version '{doc_ver}'."
                        ),
                        claim_index=claim_index,
                        evidence_id=handle,
                    )
                )
                ok = False

        if policy.enforce_span_check:
            span = resolve_source_span(entry)
            if not span.resolvable:
                _append_unique(unresolvable_ids, handle)
                issues.append(
                    CitationIssue(
                        code="unresolvable_source_span",
                        severity="error",
                        message=(
                            f"Citation '{handle}' lacks resolvable source "
                            "span provenance."
                        ),
                        claim_index=claim_index,
                        evidence_id=handle,
                    )
                )
                ok = False

        return entry if ok else None
