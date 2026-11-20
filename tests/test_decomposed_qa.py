"""Unit tests for QueryDecomposer and decomposed multi-step QA mode."""

import json
import uuid
from typing import Sequence

import pytest

from rag_foundry.generation.pipeline import (
    GroundedQAPipeline,
    GroundedQARequest,
)
from rag_foundry.model_gateway.adapters import MockDeterministicChatAdapter
from rag_foundry.model_gateway.gateway import ModelGateway
from rag_foundry.model_gateway.models import (
    ChatMessage,
    ModelProfile,
    ModelProfilePolicyError,
)
from rag_foundry.model_gateway.registry import InMemoryModelProfileRegistry
from rag_foundry.retrieval.lexical import LexicalRecord, LexicalRetriever
from rag_foundry.retrieval.pipeline import RetrievalPipeline
from rag_foundry.retrieval.security import SecurityContext


@pytest.mark.asyncio
async def test_query_decomposer_llm_bounds_fallback_and_policy() -> None:
    """QueryDecomposer handles LLM JSON, bounds, fallback, and policy check."""
    from rag_foundry.generation.decomposer import (
        QueryDecomposer,
        deterministic_split_question,
    )

    # Deterministic splitter handles multi-question and conjunction prompts
    parts_q = deterministic_split_question(
        "What is the retention period? How are archives encrypted?",
        max_sub_questions=4,
    )
    assert len(parts_q) == 2
    assert "retention period" in parts_q[0].lower()
    assert "encrypted" in parts_q[1].lower()

    parts_conj = deterministic_split_question(
        "What is the retention policy and how are backup keys rotated?",
        max_sub_questions=2,
    )
    assert len(parts_conj) == 2

    # LLM-assisted decomposition respects max_sub_questions cap
    llm_adapter = MockDeterministicChatAdapter(
        responder=lambda _p, _m, _j: json.dumps(
            {
                "sub_questions": [
                    "What is the retention period?",
                    "What encryption algorithm is required?",
                    "Who approves overrides?",
                    "What is the retention period?",
                ]
            }
        )
    )
    registry = InMemoryModelProfileRegistry(
        profiles=[
            ModelProfile(
                profile_id="decomp-local",
                version="1.0.0",
                task="query_decomposition",
                provider="mock",
                model_name="mock-decomp",
                status="approved",
            ),
            ModelProfile(
                profile_id="decomp-draft",
                version="0.1.0",
                task="query_decomposition",
                provider="mock",
                model_name="mock-draft",
                status="draft",
            ),
        ]
    )
    gw = ModelGateway(registry=registry, adapters={"mock": llm_adapter})
    decomposer = QueryDecomposer(model_gateway=gw)

    res = await decomposer.decompose(
        "Compare retention, encryption, and override rules.",
        max_sub_questions=2,
        profile_id="decomp-local",
    )
    assert res.method == "llm"
    assert res.model_profile_id == "decomp-local"
    assert len(res.sub_questions) == 2
    assert res.sub_questions[0] == "What is the retention period?"

    # Malformed LLM output gracefully falls back to deterministic splitter
    bad_gw = ModelGateway(
        registry=registry,
        adapters={
            "mock": MockDeterministicChatAdapter(
                responder=lambda _p, _m, _j: "not valid json"
            )
        },
    )
    fb_res = await QueryDecomposer(model_gateway=bad_gw).decompose(
        "What is the retention period? What encryption standard applies?",
        max_sub_questions=3,
        profile_id="decomp-local",
    )
    assert fb_res.method == "deterministic_fallback"
    assert len(fb_res.sub_questions) == 2

    # Unapproved decomposition profile fails closed (never silently falls back)
    with pytest.raises(ModelProfilePolicyError):
        await decomposer.decompose(
            "Test question?",
            profile_id="decomp-draft",
        )


@pytest.mark.asyncio
async def test_decomposed_qa_mode_end_to_end_merge_and_revalidation() -> None:
    """Decomposed QA runs sub-queries, deduplicates evidence, re-validates."""
    ws_id = uuid.uuid4()
    doc_a = uuid.uuid4()
    doc_b = uuid.uuid4()
    chunk_ret = uuid.uuid4()
    chunk_enc = uuid.uuid4()

    lex = LexicalRetriever()
    await lex.index_records(
        [
            LexicalRecord(
                chunk_id=chunk_ret,
                document_version_id=doc_a,
                workspace_id=ws_id,
                text="Financial records retention period is 7 years.",
                section_path=["Retention"],
                page_numbers=[2],
                security_domain="compliance",
            ),
            LexicalRecord(
                chunk_id=chunk_enc,
                document_version_id=doc_b,
                workspace_id=ws_id,
                text="Backup archives require AES-256 encryption standard.",
                section_path=["Encryption"],
                page_numbers=[6],
                security_domain="compliance",
            ),
            LexicalRecord(
                chunk_id=uuid.uuid4(),
                document_version_id=uuid.uuid4(),
                workspace_id=ws_id,
                text="Restricted secret encryption keys are stored offline.",
                section_path=["Secrets"],
                page_numbers=[1],
                security_domain="restricted",
            ),
        ]
    )
    retrieval = RetrievalPipeline(lexical_retriever=lex)

    def smart_responder(
        prof: ModelProfile, msgs: Sequence[ChatMessage], _jm: bool
    ) -> str:
        if prof.task == "query_decomposition":
            return json.dumps(
                {
                    "sub_questions": [
                        "What is the financial records retention period?",
                        "What encryption standard do backup archives require?",
                    ]
                }
            )
        user_msg = msgs[-1].content
        if "Sub-Question Findings:" in user_msg:
            return json.dumps(
                {
                    "answer": (
                        "Financial records retention period is 7 years [E1], "
                        "and backup archives require AES-256 encryption "
                        "standard [E2]."
                    ),
                    "claims": [
                        {
                            "text": (
                                "Financial records retention period is "
                                "7 years."
                            ),
                            "evidence_ids": ["E1"],
                        },
                        {
                            "text": (
                                "Backup archives require AES-256 encryption "
                                "standard."
                            ),
                            "evidence_ids": ["E2"],
                        },
                    ],
                    "limitations": [],
                    "sufficient_evidence": True,
                }
            )
        if "retention" in user_msg.lower():
            return json.dumps(
                {
                    "answer": (
                        "Financial records retention period is 7 years [E1]."
                    ),
                    "claims": [
                        {
                            "text": (
                                "Financial records retention period is "
                                "7 years."
                            ),
                            "evidence_ids": ["E1"],
                        }
                    ],
                    "limitations": [],
                    "sufficient_evidence": True,
                }
            )
        return json.dumps(
            {
                "answer": "Backup archives require AES-256 encryption [E1].",
                "claims": [
                    {
                        "text": (
                            "Backup archives require AES-256 encryption "
                            "standard."
                        ),
                        "evidence_ids": ["E1"],
                    }
                ],
                "limitations": [],
                "sufficient_evidence": True,
            }
        )

    registry = InMemoryModelProfileRegistry(
        profiles=[
            ModelProfile(
                profile_id="qa-local",
                version="1.0.0",
                task="chat_generation",
                provider="mock",
                model_name="mock-qa",
                status="approved",
            ),
            ModelProfile(
                profile_id="decomp-local",
                version="1.0.0",
                task="query_decomposition",
                provider="mock",
                model_name="mock-decomp",
                status="approved",
            ),
        ]
    )
    gw = ModelGateway(
        registry=registry,
        adapters={
            "mock": MockDeterministicChatAdapter(responder=smart_responder)
        },
    )
    qa = GroundedQAPipeline(retrieval_pipeline=retrieval, model_gateway=gw)

    sec_ctx = SecurityContext(
        user_id="compliance-analyst",
        allowed_workspaces=[ws_id],
        allowed_security_domains=["compliance"],
    )
    ans = await qa.answer(
        GroundedQARequest(
            question=(
                "What is the retention period and encryption standard for "
                "backup archives?"
            ),
            workspace_id=ws_id,
            model_profile_id="qa-local",
            decomposition_profile_id="decomp-local",
            qa_mode="decomposed",
            max_sub_questions=3,
            enable_dense=False,
            enable_expansion=False,
        ),
        security_context=sec_ctx,
    )

    assert ans.abstained is False
    assert ans.sufficient_evidence is True
    assert ans.qa_mode == "decomposed"
    assert len(ans.claims) == 2
    assert all(c.verified for c in ans.claims)
    assert len(ans.citations) == 2
    assert {c.chunk_id for c in ans.citations} == {chunk_ret, chunk_enc}
    # Restricted chunk never leaked into merged citations
    assert all(c.security_domain == "compliance" for c in ans.citations)

    decomp_trace = ans.execution_metrics["decomposition"]
    assert decomp_trace["method"] == "llm"
    assert len(decomp_trace["sub_questions"]) == 2
    assert len(decomp_trace["sub_question_traces"]) == 2
    assert decomp_trace["merged_evidence_count"] == 2

    # Final synthesis fabricating [E99] still fails closed during re-validation
    def hallucinating_synth(
        prof: ModelProfile, msgs: Sequence[ChatMessage], _jm: bool
    ) -> str:
        if "Sub-Question Findings:" in msgs[-1].content:
            return json.dumps(
                {
                    "answer": "Fabricated synthesis [E99].",
                    "claims": [
                        {
                            "text": "Financial records retention is 7 years.",
                            "evidence_ids": ["E99"],
                        }
                    ],
                    "sufficient_evidence": True,
                }
            )
        return smart_responder(prof, msgs, _jm)

    bad_gw = ModelGateway(
        registry=registry,
        adapters={
            "mock": MockDeterministicChatAdapter(responder=hallucinating_synth)
        },
    )
    bad_qa = GroundedQAPipeline(
        retrieval_pipeline=retrieval, model_gateway=bad_gw
    )
    bad_ans = await bad_qa.answer(
        GroundedQARequest(
            question="Retention period? Encryption standard?",
            workspace_id=ws_id,
            model_profile_id="qa-local",
            qa_mode="decomposed",
            enable_dense=False,
            enable_expansion=False,
        ),
        security_context=sec_ctx,
    )
    assert bad_ans.abstained is True
    assert bad_ans.sufficient_evidence is False
    assert "E99" in (bad_ans.abstention_reason or "")
