"""Unit tests for structured generation models and strict JSON parser."""

import json
import uuid

import pytest
from pydantic import ValidationError

from rag_foundry.retrieval.models import BoundingBox


def test_evidence_entry_and_knowledge_authority_validation() -> None:
    """EvidenceEntry validates provenance, authority, and confidence bounds."""
    from rag_foundry.generation.models import (
        EvidenceEntry,
        KnowledgeAuthority,
    )

    ws_id = uuid.uuid4()
    doc_ver_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    entity_id = uuid.uuid4()

    entry = EvidenceEntry(
        evidence_id="E1",
        authority=KnowledgeAuthority.DOCUMENT_EVIDENCE,
        text="Retention period for financial records is seven years.",
        workspace_id=ws_id,
        security_domain="finance",
        document_version_id=doc_ver_id,
        document_title="Retention Policy v2",
        chunk_id=chunk_id,
        section_path=("Compliance", "Retention"),
        page_numbers=(3,),
        bounding_boxes=(BoundingBox(page=3, l=0.1, t=0.2, r=0.8, b=0.3),),
        entity_ids=(entity_id,),
        concept_uris=("https://example.org/tax/retention",),
        confidence_score=0.92,
    )
    assert entry.evidence_id == "E1"
    assert entry.authority == KnowledgeAuthority.DOCUMENT_EVIDENCE
    assert entry.authority.value == "document_evidence"
    assert entry.security_domains == ("finance",)
    assert entry.page_numbers == (3,)
    assert len(entry.bounding_boxes) == 1

    # Curated assertion entry
    curated = EvidenceEntry(
        evidence_id="A1",
        authority=KnowledgeAuthority.CURATED,
        text="Acme Policy mandates 7-year retention.",
        workspace_id=ws_id,
        security_domain="general",
        assertion_id=uuid.uuid4(),
        assertion_origin="curated",
        assertion_status="approved",
        confidence_score=1.0,
    )
    assert curated.authority == KnowledgeAuthority.CURATED
    assert curated.assertion_status == "approved"

    # Extracted candidate entry
    extracted = EvidenceEntry(
        evidence_id="A2",
        authority=KnowledgeAuthority.EXTRACTED,
        text="Draft policy suggests 5-year archive.",
        workspace_id=ws_id,
        security_domain="general",
        assertion_id=uuid.uuid4(),
        assertion_origin="extracted",
        assertion_status="candidate",
        confidence_score=0.65,
    )
    assert extracted.authority == KnowledgeAuthority.EXTRACTED

    # Invalid authority or out-of-range confidence fails validation
    with pytest.raises(ValidationError):
        EvidenceEntry(
            evidence_id="E2",
            authority="rumor",  # type: ignore[arg-type]
            text="Invalid.",
            workspace_id=ws_id,
            security_domain="general",
        )

    with pytest.raises(ValidationError):
        EvidenceEntry(
            evidence_id="E3",
            authority=KnowledgeAuthority.DOCUMENT_EVIDENCE,
            text="Bad confidence.",
            workspace_id=ws_id,
            security_domain="general",
            confidence_score=1.5,
        )


def test_answer_claim_and_grounded_answer_contract() -> None:
    """AnswerClaim and GroundedAnswer enforce ARCHITECTURE.md §15.2 fields."""
    from rag_foundry.generation.models import (
        AnswerClaim,
        EvidenceEntry,
        GroundedAnswer,
        KnowledgeAuthority,
    )

    ws_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    entity_id = uuid.uuid4()

    ev = EvidenceEntry(
        evidence_id="E1",
        authority=KnowledgeAuthority.DOCUMENT_EVIDENCE,
        text="All audit logs are retained for 7 years.",
        workspace_id=ws_id,
        security_domain="compliance",
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        page_numbers=(1,),
        confidence_score=0.88,
    )
    claim = AnswerClaim(
        text="Audit logs are retained for 7 years.",
        evidence_ids=("E1",),
        concept_uris=("https://example.org/tax/audit-log",),
        entity_ids=(entity_id,),
        authority="document_evidence",
        support_score=0.91,
        verified=True,
    )
    answer = GroundedAnswer(
        answer="Audit logs are retained for 7 years [E1].",
        claims=(claim,),
        citations=(ev,),
        limitations=(),
        sufficient_evidence=True,
        abstained=False,
        qa_mode="standard",
        semantic_profile_id=profile_id,
        model_profile_id="balanced-local",
        model_profile_version="1.0.0",
    )

    assert answer.sufficient_evidence is True
    assert answer.abstained is False
    assert answer.abstention_reason is None
    assert answer.claims[0].verified is True
    assert answer.citations[0].evidence_id == "E1"
    dumped = json.loads(answer.model_dump_json())
    assert dumped["qa_mode"] == "standard"
    assert dumped["semantic_profile_id"] == str(profile_id)


def test_parse_model_answer_raw_fenced_and_defaults() -> None:
    """Strict parser handles raw JSON, fenced JSON, and default fields."""
    from rag_foundry.generation.parser import parse_model_answer

    ent_id = str(uuid.uuid4())
    raw_json = json.dumps(
        {
            "answer": "Records must be kept for seven years [E1].",
            "claims": [
                {
                    "text": "Records must be kept for seven years.",
                    "evidence_ids": ["[E1]", "E1", " A1 "],
                    "concept_uris": ["https://example.org/tax/records"],
                    "entity_ids": [ent_id],
                    "authority": "curated",
                }
            ],
            "limitations": ["Applies to regulated records only."],
            "sufficient_evidence": True,
        }
    )

    parsed = parse_model_answer(raw_json)
    assert parsed.answer == "Records must be kept for seven years [E1]."
    assert len(parsed.claims) == 1
    assert parsed.claims[0].evidence_ids == ("E1", "A1")
    assert parsed.claims[0].claimed_authority == "curated"
    assert str(parsed.claims[0].entity_ids[0]) == ent_id
    assert parsed.limitations == ("Applies to regulated records only.",)
    assert parsed.sufficient_evidence is True

    # Markdown fenced JSON with minimal fields uses deterministic defaults
    fenced = 'Here is the answer:\n```json\n{"answer": "Short summary."}\n```'
    parsed_fenced = parse_model_answer(fenced)
    assert parsed_fenced.answer == "Short summary."
    assert parsed_fenced.claims == ()
    assert parsed_fenced.limitations == ()
    assert parsed_fenced.sufficient_evidence is True

    # Plain ``` fence without language tag
    plain_fenced = (
        '```\n{"answer": "Plain fence.", "sufficient_evidence": false}\n```'
    )
    parsed_plain = parse_model_answer(plain_fenced)
    assert parsed_plain.answer == "Plain fence."
    assert parsed_plain.sufficient_evidence is False


@pytest.mark.parametrize(
    "bad_output",
    [
        "",
        "   \n  ",
        "Not JSON at all.",
        "[1, 2, 3]",
        "{}",
        '{"answer": "   "}',
        '{"answer": 123}',
        '{"answer": "ok", "claims": "not-a-list"}',
        '{"answer": "ok", "claims": [{"evidence_ids": ["E1"]}]}',
        '{"answer": "ok", "claims": [{"text": "x", "evidence_ids": "E1"}]}',
        (
            '{"answer": "ok", '
            '"claims": [{"text": "x", "entity_ids": ["bad-uuid"]}]}'
        ),
        '{"answer": "ok", "claims": [{"text": "x", "authority": "bogus"}]}',
        '{"answer": "ok", "limitations": "should-be-list"}',
        '{"answer": "ok", "sufficient_evidence": "yes"}',
    ],
)
def test_parse_model_answer_fails_closed_on_invalid_payloads(
    bad_output: str,
) -> None:
    """Malformed or schema-invalid outputs raise AnswerParseError."""
    from rag_foundry.generation.parser import (
        AnswerParseError,
        parse_model_answer,
    )

    with pytest.raises(AnswerParseError):
        parse_model_answer(bad_output)
