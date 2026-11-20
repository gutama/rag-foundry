"""Unit tests for CitationValidationPolicy, report models, and aligner."""

import uuid

import pytest
from pydantic import ValidationError

from rag_foundry.generation.models import (
    AnswerClaim,
    EvidenceEntry,
    KnowledgeAuthority,
)
from rag_foundry.retrieval.models import BoundingBox


def _doc_entry(
    *,
    handle: str = "E1",
    text: str,
    ws_id: uuid.UUID,
    doc_ver_id: uuid.UUID | None = None,
    chunk_id: uuid.UUID | None = None,
    include_ids: bool = True,
) -> EvidenceEntry:
    """Build a DOCUMENT_EVIDENCE entry with optional source IDs."""
    return EvidenceEntry(
        evidence_id=handle,
        authority=KnowledgeAuthority.DOCUMENT_EVIDENCE,
        text=text,
        workspace_id=ws_id,
        security_domain="compliance",
        document_version_id=(
            doc_ver_id or uuid.uuid4() if include_ids else None
        ),
        chunk_id=chunk_id or uuid.uuid4() if include_ids else None,
        section_path=("Compliance", "Retention"),
        page_numbers=(4,),
        bounding_boxes=(BoundingBox(page=4, l=0.1, t=0.2, r=0.8, b=0.35),),
        confidence_score=0.9,
    )


def test_citation_validation_policy_defaults_and_bounds() -> None:
    """CitationValidationPolicy enforces strict defaults and numeric bounds."""
    from rag_foundry.citations.models import CitationValidationPolicy

    policy = CitationValidationPolicy()
    assert policy.reject_invalid_citation_ids is True
    assert policy.require_claim_citations is True
    assert policy.unsupported_claim_action == "abstain"
    assert policy.enforce_revision_check is True
    assert policy.enforce_span_check is True

    with pytest.raises(ValidationError):
        CitationValidationPolicy(min_claim_support_score=1.5)

    with pytest.raises(ValidationError):
        CitationValidationPolicy(
            unsupported_claim_action="ignore"  # type: ignore[arg-type]
        )


def test_citation_aligner_support_scoring_and_synthetic_claims() -> None:
    """Aligner distinguishes grounded claims from synthetic or altered ones."""
    from rag_foundry.citations.aligner import CitationAligner

    ws_id = uuid.uuid4()
    ev1 = _doc_entry(
        handle="E1",
        text=(
            "Financial audit records must be retained for 7 years in "
            "encrypted archival storage."
        ),
        ws_id=ws_id,
    )
    ev_map = {"E1": ev1}
    aligner = CitationAligner()

    # Grounded claim with spelled-out equivalent number ("seven" == "7")
    grounded = AnswerClaim(
        text=(
            "Financial audit records must be retained for seven years "
            "in encrypted storage."
        ),
        evidence_ids=("E1",),
    )
    res_ok = aligner.align_claim(grounded, ev_map, min_support_score=0.35)
    assert res_ok.supported is True
    assert res_ok.numeric_mismatch is False
    assert res_ok.support_score >= 0.70
    assert res_ok.effective_authority == "document_evidence"
    assert res_ok.claim.authority == "document_evidence"
    assert res_ok.claim.support_score == res_ok.support_score

    # Synthetic unsupported claim citing unrelated passage
    synthetic = AnswerClaim(
        text=(
            "Quantum satellites orbit Neptune using cryogenic fusion "
            "propulsion turbines."
        ),
        evidence_ids=("E1",),
    )
    res_bad = aligner.align_claim(synthetic, ev_map, min_support_score=0.35)
    assert res_bad.supported is False
    assert res_bad.support_score < 0.20

    # Numeric distortion ("15 years" instead of "7 years") flagged & penalized
    wrong_num = AnswerClaim(
        text="Financial audit records must be retained for 15 years.",
        evidence_ids=("E1",),
    )
    res_num = aligner.align_claim(wrong_num, ev_map, min_support_score=0.50)
    assert res_num.numeric_mismatch is True
    assert res_num.supported is False
    assert res_num.support_score < res_ok.support_score


def test_citation_aligner_spans_and_effective_authority_derivation() -> None:
    """Aligner resolves spans and derives curated/extracted/mixed authority."""
    from rag_foundry.citations.aligner import (
        CitationAligner,
        resolve_source_span,
    )

    ws_id = uuid.uuid4()
    doc_ver_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    doc_ev = _doc_entry(
        handle="E1",
        text="Board approval is required for quarterly risk exceptions.",
        ws_id=ws_id,
        doc_ver_id=doc_ver_id,
        chunk_id=chunk_id,
    )
    broken_doc = _doc_entry(
        handle="E2",
        text="Orphan excerpt without chunk provenance.",
        ws_id=ws_id,
        include_ids=False,
    )
    curated_ev = EvidenceEntry(
        evidence_id="A1",
        authority=KnowledgeAuthority.CURATED,
        text="Risk exceptions require board approval.",
        workspace_id=ws_id,
        security_domain="compliance",
        assertion_id=uuid.uuid4(),
        assertion_origin="curated",
        assertion_status="approved",
        confidence_score=1.0,
    )
    extracted_with_span = EvidenceEntry(
        evidence_id="A2",
        authority=KnowledgeAuthority.EXTRACTED,
        text="Quarterly exceptions may require committee notification.",
        workspace_id=ws_id,
        security_domain="compliance",
        document_version_id=doc_ver_id,
        chunk_id=chunk_id,
        assertion_id=uuid.uuid4(),
        assertion_origin="extracted",
        assertion_status="candidate",
        confidence_score=0.72,
    )
    extracted_orphan = EvidenceEntry(
        evidence_id="A3",
        authority=KnowledgeAuthority.EXTRACTED,
        text="Unbacked candidate extraction.",
        workspace_id=ws_id,
        security_domain="compliance",
        assertion_id=uuid.uuid4(),
        assertion_origin="extracted",
        assertion_status="candidate",
        confidence_score=0.55,
    )

    span_doc = resolve_source_span(doc_ev)
    assert span_doc.resolvable is True
    assert span_doc.document_version_id == doc_ver_id
    assert span_doc.page_numbers == (4,)
    assert len(span_doc.bounding_boxes) == 1
    assert span_doc.section_path == ("Compliance", "Retention")

    assert resolve_source_span(broken_doc).resolvable is False
    assert resolve_source_span(curated_ev).resolvable is True
    assert resolve_source_span(extracted_with_span).resolvable is True
    assert resolve_source_span(extracted_orphan).resolvable is False

    ev_map = {
        "E1": doc_ev,
        "A1": curated_ev,
        "A2": extracted_with_span,
    }
    aligner = CitationAligner()
    results = aligner.align_claims(
        claims=[
            AnswerClaim(
                text="Risk exceptions require board approval.",
                evidence_ids=("A1",),
            ),
            AnswerClaim(
                text="Quarterly exceptions may require committee notification.",
                evidence_ids=("A2",),
            ),
            AnswerClaim(
                text=(
                    "Board approval is required for quarterly risk "
                    "exceptions."
                ),
                evidence_ids=("A1", "E1"),
            ),
        ],
        evidence_map=ev_map,
    )
    assert [r.effective_authority for r in results] == [
        "curated",
        "extracted",
        "mixed",
    ]
    assert all(r.supported for r in results)
