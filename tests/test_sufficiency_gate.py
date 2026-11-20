"""Unit tests for SufficiencyGate warnings, stripping, and abstention."""

import uuid

from rag_foundry.citations.models import CitationValidationPolicy
from rag_foundry.citations.validator import CitationValidator
from rag_foundry.generation.models import (
    AnswerClaim,
    EvidenceEntry,
    KnowledgeAuthority,
    ParsedAnswerPayload,
)
from rag_foundry.retrieval.models import AbstentionResult
from rag_foundry.retrieval.security import SecurityContext


def _sec_ctx(ws_id: uuid.UUID) -> SecurityContext:
    """Create a default authorized SecurityContext."""
    return SecurityContext(
        user_id="analyst-1",
        allowed_workspaces=[ws_id],
        allowed_security_domains=["public"],
    )


def _doc_ev(
    ws_id: uuid.UUID,
    *,
    handle: str = "E1",
    text: str = "Audit records must be kept for 7 years.",
) -> EvidenceEntry:
    """Create a valid document EvidenceEntry."""
    return EvidenceEntry(
        evidence_id=handle,
        authority=KnowledgeAuthority.DOCUMENT_EVIDENCE,
        text=text,
        workspace_id=ws_id,
        security_domain="public",
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        page_numbers=(1,),
        confidence_score=0.92,
    )


def _extracted_ev(
    ws_id: uuid.UUID,
    *,
    handle: str = "A1",
    text: str = "Draft extraction suggests 5-year archive.",
) -> EvidenceEntry:
    """Create a valid extracted-candidate EvidenceEntry."""
    return EvidenceEntry(
        evidence_id=handle,
        authority=KnowledgeAuthority.EXTRACTED,
        text=text,
        workspace_id=ws_id,
        security_domain="public",
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        assertion_id=uuid.uuid4(),
        assertion_origin="extracted",
        assertion_status="candidate",
        confidence_score=0.75,
    )


def test_gate_propagates_retrieval_parse_and_invalid_citations() -> None:
    """Gate abstains on retrieval abstention, parse failure, or bad IDs."""
    from rag_foundry.citations.sufficiency import SufficiencyGate

    ws_id = uuid.uuid4()
    gate = SufficiencyGate()

    # 1. Retrieval abstention propagates directly
    ret_abstain = gate.evaluate(
        payload=None,
        report=None,
        evidence_map={},
        retrieval_abstention=AbstentionResult(
            abstained=True,
            reason="Highest score 0.12 below threshold 0.50.",
            threshold=0.5,
            highest_score=0.12,
        ),
    )
    assert ret_abstain.abstained is True
    assert ret_abstain.sufficient_evidence is False
    assert "0.12" in (ret_abstain.abstention_reason or "")

    # 2. Parse error fails closed with abstention
    parse_abstain = gate.evaluate(
        payload=None,
        report=None,
        evidence_map={},
        parse_error="Model output is not valid JSON.",
    )
    assert parse_abstain.abstained is True
    assert parse_abstain.sufficient_evidence is False
    assert "JSON" in (parse_abstain.abstention_reason or "")

    # 3. Fabricated citation IDs trigger fail-closed abstention
    ev1 = _doc_ev(ws_id)
    bad_payload = ParsedAnswerPayload(
        answer="Records kept 7 years [E1] and reviewed daily [E99].",
        claims=(
            AnswerClaim(
                text="Audit records must be kept for 7 years.",
                evidence_ids=("E1", "E99"),
            ),
        ),
    )
    bad_report = CitationValidator().validate(
        payload=bad_payload,
        evidence_map={"E1": ev1},
        security_context=_sec_ctx(ws_id),
    )
    bad_ans = gate.evaluate(
        payload=bad_payload,
        report=bad_report,
        evidence_map={"E1": ev1},
    )
    assert bad_ans.abstained is True
    assert bad_ans.sufficient_evidence is False
    assert bad_ans.claims == ()
    assert bad_ans.citations == ()
    assert "E99" in (bad_ans.abstention_reason or "")


def test_sufficiency_gate_unsupported_claim_actions() -> None:
    """Gate enforces abstain, strip_and_warn, and warn action modes."""
    from rag_foundry.citations.sufficiency import SufficiencyGate

    ws_id = uuid.uuid4()
    ev1 = _doc_ev(ws_id)
    ev_map = {"E1": ev1}

    # One supported claim + one unsupported synthetic claim (ratio = 0.5)
    payload = ParsedAnswerPayload(
        answer=(
            "Audit records must be kept for 7 years [E1]. "
            "Quantum satellites patrol Neptune [E1]."
        ),
        claims=(
            AnswerClaim(
                text="Audit records must be kept for 7 years.",
                evidence_ids=("E1",),
            ),
            AnswerClaim(
                text="Quantum satellites patrol Neptune.",
                evidence_ids=("E1",),
            ),
        ),
    )

    gate = SufficiencyGate()

    # Mode 1: abstain (default)
    pol_abstain = CitationValidationPolicy(
        min_supported_claim_ratio=0.75,
        unsupported_claim_action="abstain",
    )
    rep_abstain = CitationValidator().validate(
        payload=payload,
        evidence_map=ev_map,
        security_context=_sec_ctx(ws_id),
        policy=pol_abstain,
    )
    ans_abstain = gate.evaluate(
        payload=payload,
        report=rep_abstain,
        evidence_map=ev_map,
        policy=pol_abstain,
    )
    assert ans_abstain.abstained is True
    assert ans_abstain.sufficient_evidence is False
    assert ans_abstain.claims == ()

    # Mode 2: strip_and_warn removes unsupported claim & adds limitation
    pol_strip = CitationValidationPolicy(
        min_supported_claim_ratio=0.50,
        unsupported_claim_action="strip_and_warn",
    )
    rep_strip = CitationValidator().validate(
        payload=payload,
        evidence_map=ev_map,
        security_context=_sec_ctx(ws_id),
        policy=pol_strip,
    )
    ans_strip = gate.evaluate(
        payload=payload,
        report=rep_strip,
        evidence_map=ev_map,
        policy=pol_strip,
    )
    assert ans_strip.abstained is False
    assert ans_strip.sufficient_evidence is True
    assert len(ans_strip.claims) == 1
    assert ans_strip.claims[0].verified is True
    assert "Neptune" not in ans_strip.answer
    assert "7 years" in ans_strip.answer
    assert len(ans_strip.citations) == 1
    assert any("removed" in lim.lower() for lim in ans_strip.limitations)

    # Mode 3: warn keeps claims with verified=False and marks low ratio
    pol_warn = CitationValidationPolicy(
        min_supported_claim_ratio=0.75,
        unsupported_claim_action="warn",
    )
    rep_warn = CitationValidator().validate(
        payload=payload,
        evidence_map=ev_map,
        security_context=_sec_ctx(ws_id),
        policy=pol_warn,
    )
    ans_warn = gate.evaluate(
        payload=payload,
        report=rep_warn,
        evidence_map=ev_map,
        policy=pol_warn,
    )
    assert ans_warn.abstained is False
    assert ans_warn.sufficient_evidence is False
    assert len(ans_warn.claims) == 2
    assert ans_warn.claims[0].verified is True
    assert ans_warn.claims[1].verified is False
    assert any("unsupported" in lim.lower() for lim in ans_warn.limitations)


def test_sufficiency_gate_extracted_only_policy_and_disclosures() -> None:
    """Gate blocks extracted-only when disallowed and discloses candidates."""
    from rag_foundry.citations.sufficiency import SufficiencyGate

    ws_id = uuid.uuid4()
    ext_ev = _extracted_ev(ws_id)
    ev_map = {"A1": ext_ev}

    payload = ParsedAnswerPayload(
        answer="Draft extraction suggests 5-year archive [A1].",
        claims=(
            AnswerClaim(
                text="Draft extraction suggests 5-year archive.",
                evidence_ids=("A1",),
            ),
        ),
    )

    gate = SufficiencyGate()

    # Disallowing extracted-only answers triggers abstention
    strict_pol = CitationValidationPolicy(allow_extracted_only_answers=False)
    rep = CitationValidator().validate(
        payload=payload,
        evidence_map=ev_map,
        security_context=_sec_ctx(ws_id),
        policy=strict_pol,
    )
    blocked = gate.evaluate(
        payload=payload,
        report=rep,
        evidence_map=ev_map,
        policy=strict_pol,
        qa_mode="curated_knowledge",
    )
    assert blocked.abstained is True
    assert blocked.sufficient_evidence is False
    assert "extracted" in (blocked.abstention_reason or "").lower()

    # Allowing extracted-only answers requires explicit ADR-0013 disclosure
    permissive_pol = CitationValidationPolicy(
        allow_extracted_only_answers=True,
        disclose_extracted_knowledge=True,
    )
    allowed = gate.evaluate(
        payload=payload,
        report=rep,
        evidence_map=ev_map,
        policy=permissive_pol,
        qa_mode="curated_knowledge",
    )
    assert allowed.abstained is False
    assert allowed.sufficient_evidence is True
    assert allowed.claims[0].authority == "extracted"
    assert any(
        "unapproved extracted" in lim.lower() for lim in allowed.limitations
    )
    assert any(
        "no steward-curated" in lim.lower() for lim in allowed.limitations
    )
