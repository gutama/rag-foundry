"""Unit tests for fail-closed CitationValidator (ADR-0020 & ADR-0013)."""

import uuid

from rag_foundry.citations.models import CitationValidationPolicy
from rag_foundry.generation.models import (
    AnswerClaim,
    EvidenceEntry,
    KnowledgeAuthority,
    ParsedAnswerPayload,
)
from rag_foundry.retrieval.security import SecurityContext


def _ctx(
    ws_id: uuid.UUID,
    domains: list[str] | None = None,
) -> SecurityContext:
    """Create a sample SecurityContext."""
    return SecurityContext(
        user_id="analyst-1",
        allowed_workspaces=[ws_id],
        allowed_security_domains=["public"] if domains is None else domains,
    )


def _doc_ev(
    *,
    handle: str = "E1",
    text: str,
    ws_id: uuid.UUID,
    domain: str = "public",
    domains: tuple[str, ...] = (),
    doc_ver_id: uuid.UUID | None = None,
    chunk_id: uuid.UUID | None = None,
    include_ids: bool = True,
    confidence: float = 0.9,
) -> EvidenceEntry:
    """Build a document EvidenceEntry."""
    return EvidenceEntry(
        evidence_id=handle,
        authority=KnowledgeAuthority.DOCUMENT_EVIDENCE,
        text=text,
        workspace_id=ws_id,
        security_domain=domain,
        security_domains=domains,
        document_version_id=(
            doc_ver_id or uuid.uuid4() if include_ids else None
        ),
        chunk_id=chunk_id or uuid.uuid4() if include_ids else None,
        page_numbers=(1,),
        confidence_score=confidence,
    )


def test_validator_passes_valid_authorized_grounded_claims() -> None:
    """Valid authorized, active-revision, aligned claims pass cleanly."""
    from rag_foundry.citations.validator import CitationValidator

    ws_id = uuid.uuid4()
    active_doc = uuid.uuid4()
    ev1 = _doc_ev(
        handle="E1",
        text="Quarterly compliance audits must be archived for 7 years.",
        ws_id=ws_id,
        domain="public",
        doc_ver_id=active_doc,
    )
    payload = ParsedAnswerPayload(
        answer="Quarterly compliance audits are archived for 7 years [E1].",
        claims=(
            AnswerClaim(
                text=(
                    "Quarterly compliance audits must be archived for 7 years."
                ),
                evidence_ids=("E1",),
            ),
        ),
        sufficient_evidence=True,
    )

    validator = CitationValidator()
    report = validator.validate(
        payload=payload,
        evidence_map={"E1": ev1},
        security_context=_ctx(ws_id, ["public"]),
        active_document_version_ids={active_doc},
    )

    assert report.passed is True
    assert report.has_invalid_citations is False
    assert report.supported_claim_count == 1
    assert report.total_claim_count == 1
    assert report.supported_claim_ratio == 1.0
    assert report.claim_results[0].claim.verified is True
    assert report.effective_answer_authority == "document_evidence"


def test_validator_rejects_fabricated_claim_and_inline_citation_ids() -> None:
    """Unknown citation IDs in claims or inline answer text fail closed."""
    from rag_foundry.citations.validator import CitationValidator

    ws_id = uuid.uuid4()
    ev1 = _doc_ev(
        handle="E1",
        text="Retention policy mandates 7-year archival.",
        ws_id=ws_id,
    )
    payload = ParsedAnswerPayload(
        answer="Retention is 7 years [E1] and audited monthly [E99].",
        claims=(
            AnswerClaim(
                text="Retention policy mandates 7-year archival.",
                evidence_ids=("E1", "E42"),
            ),
        ),
    )

    report = CitationValidator().validate(
        payload=payload,
        evidence_map={"E1": ev1},
        security_context=_ctx(ws_id),
    )
    assert report.passed is False
    assert report.has_invalid_citations is True
    assert "E42" in report.invalid_citation_ids
    assert "E99" in report.invalid_citation_ids
    assert any(i.code == "unknown_citation_id" for i in report.issues)


def test_validator_rejects_unauthorized_workspace_and_domains() -> None:
    """Citations failing workspace or multi-domain ACL checks are rejected."""
    from rag_foundry.citations.validator import CitationValidator

    ws_allowed = uuid.uuid4()
    ws_other = uuid.uuid4()

    wrong_ws = _doc_ev(
        handle="E1",
        text="Confidential board budget.",
        ws_id=ws_other,
        domain="public",
    )
    restricted_dom = _doc_ev(
        handle="E2",
        text="Restricted risk annex.",
        ws_id=ws_allowed,
        domain="public",
        domains=("public", "restricted"),
    )

    payload = ParsedAnswerPayload(
        answer="Budget [E1] and annex [E2].",
        claims=(
            AnswerClaim(
                text="Confidential board budget.", evidence_ids=("E1",)
            ),
            AnswerClaim(text="Restricted risk annex.", evidence_ids=("E2",)),
        ),
    )

    report = CitationValidator().validate(
        payload=payload,
        evidence_map={"E1": wrong_ws, "E2": restricted_dom},
        security_context=_ctx(ws_allowed, ["public"]),
    )
    assert report.passed is False
    assert report.has_invalid_citations is True
    assert set(report.unauthorized_citation_ids) == {"E1", "E2"}
    codes = {issue.code for issue in report.issues}
    assert "unauthorized_workspace" in codes
    assert "unauthorized_security_domain" in codes


def test_validator_rejects_superseded_and_unresolvable_spans() -> None:
    """Superseded document versions and broken spans fail closed."""
    from rag_foundry.citations.validator import CitationValidator

    ws_id = uuid.uuid4()
    active_ver = uuid.uuid4()
    old_ver = uuid.uuid4()

    old_ev = _doc_ev(
        handle="E1",
        text="Legacy retention was 3 years.",
        ws_id=ws_id,
        doc_ver_id=old_ver,
    )
    broken_ev = _doc_ev(
        handle="E2",
        text="Orphan excerpt without chunk ID.",
        ws_id=ws_id,
        include_ids=False,
    )

    payload = ParsedAnswerPayload(
        answer="Legacy rule [E1] and orphan [E2].",
        claims=(
            AnswerClaim(
                text="Legacy retention was 3 years.", evidence_ids=("E1",)
            ),
            AnswerClaim(
                text="Orphan excerpt without chunk ID.", evidence_ids=("E2",)
            ),
        ),
    )

    # Active allowlist rejects old_ver; span check rejects broken_ev
    report = CitationValidator().validate(
        payload=payload,
        evidence_map={"E1": old_ev, "E2": broken_ev},
        security_context=_ctx(ws_id),
        active_document_version_ids={active_ver},
    )
    assert report.passed is False
    assert "E1" in report.superseded_citation_ids
    assert "E2" in report.unresolvable_span_ids

    # Explicit superseded denylist also rejects old_ver
    report_deny = CitationValidator().validate(
        payload=ParsedAnswerPayload(
            answer="Legacy rule [E1].",
            claims=(
                AnswerClaim(
                    text="Legacy retention was 3 years.", evidence_ids=("E1",)
                ),
            ),
        ),
        evidence_map={"E1": old_ev},
        security_context=_ctx(ws_id),
        superseded_document_version_ids={old_ver},
    )
    assert report_deny.passed is False
    assert "E1" in report_deny.superseded_citation_ids


def test_validator_catches_curated_misrepresentation_and_low_conf() -> None:
    """Claiming curated authority from extracted-only candidates is rejected."""
    from rag_foundry.citations.validator import CitationValidator

    ws_id = uuid.uuid4()
    doc_ver_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    extracted_ev = EvidenceEntry(
        evidence_id="A1",
        authority=KnowledgeAuthority.EXTRACTED,
        text="Draft extraction suggests 5-year archive.",
        workspace_id=ws_id,
        security_domain="public",
        document_version_id=doc_ver_id,
        chunk_id=chunk_id,
        assertion_id=uuid.uuid4(),
        assertion_origin="extracted",
        assertion_status="candidate",
        confidence_score=0.40,
    )

    payload = ParsedAnswerPayload(
        answer="Official curated rule is 5-year archive [A1].",
        claims=(
            AnswerClaim(
                text="Draft extraction suggests 5-year archive.",
                evidence_ids=("A1",),
                claimed_authority="curated",
            ),
            AnswerClaim(
                text="Uncited factual claim without evidence.",
                evidence_ids=(),
            ),
        ),
    )

    policy = CitationValidationPolicy(
        min_evidence_confidence=0.60,
        reject_authority_misrepresentation=True,
    )
    report = CitationValidator().validate(
        payload=payload,
        evidence_map={"A1": extracted_ev},
        security_context=_ctx(ws_id),
        policy=policy,
    )
    assert report.passed is False
    assert report.authority_misrepresentation_indices == (0,)
    assert report.claim_results[0].claim.verified is False
    assert report.claim_results[1].claim.verified is False
    codes = {issue.code for issue in report.issues}
    assert "authority_misrepresentation" in codes
    assert "low_evidence_confidence" in codes
    assert "missing_claim_citation" in codes
