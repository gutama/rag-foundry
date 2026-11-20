"""Mode-specific grounded QA and decomposition prompt builders."""

from typing import Optional, Tuple

from rag_foundry.generation.formatter import (
    CURATED_TAG,
    DOCUMENT_TAG,
    EXTRACTED_TAG,
    FormattedEvidenceContext,
)
from rag_foundry.generation.models import QAMode
from rag_foundry.model_gateway.models import ChatMessage

_SCHEMA_INSTRUCTIONS = (
    "Return ONLY a single valid JSON object with this exact schema:\n"
    "{\n"
    '  "answer": "Concise grounded answer referencing handles like [E1].",\n'
    '  "claims": [\n'
    "    {\n"
    '      "text": "Single factual claim supported by cited handles.",\n'
    '      "evidence_ids": ["E1", "A1"],\n'
    '      "concept_uris": [],\n'
    '      "entity_ids": [],\n'
    '      "authority": "curated|extracted|document_evidence|mixed"\n'
    "    }\n"
    "  ],\n"
    '  "limitations": ["Explicit caveats or missing evidence, if any."],\n'
    '  "sufficient_evidence": true\n'
    "}"
)

_CORE_GROUNDING_RULES = (
    "You are RAG Foundry, an authoritative institutional document intelligence "
    "assistant.\n"
    "STRICT GROUNDING RULES:\n"
    "1. Use ONLY the authorized evidence handles supplied in the context "
    "(e.g., E1, E2, A1, A2). NEVER fabricate or cite handles not present.\n"
    "2. Every factual claim MUST list the exact evidence_ids supporting it.\n"
    f"3. Respect authority labels: {CURATED_TAG} entries are steward-approved "
    f"institutional facts; {DOCUMENT_TAG} entries are source passages; "
    f"{EXTRACTED_TAG} entries are unverified automated candidates.\n"
    f"4. NEVER present {EXTRACTED_TAG} statements as curated institutional "
    "truth; explicitly note candidate status in limitations.\n"
    "5. If supplied evidence is insufficient or contradictory, set "
    '"sufficient_evidence": false, explain what is missing in "limitations", '
    "and abstain rather than speculating."
)

_MODE_GUIDANCE = {
    "standard": (
        "QA MODE: STANDARD.\n"
        "Answer the question directly from the authorized document excerpts "
        "and any approved assertions provided."
    ),
    "curated_knowledge": (
        "QA MODE: CURATED KNOWLEDGE.\n"
        f"Prioritize {CURATED_TAG} institutional assertions as authoritative. "
        f"Keep {EXTRACTED_TAG} candidates visibly segregated and explicitly "
        "state in limitations if curated facts are missing or if a claim "
        "relies on candidate extractions."
    ),
    "decomposed": (
        "QA MODE: DECOMPOSED SYNTHESIS.\n"
        "Synthesize a coherent, unified answer across the sub-question "
        "findings below while citing ONLY the deduplicated authorized "
        "evidence handles present in the merged context."
    ),
}


def build_qa_messages(
    question: str,
    context: FormattedEvidenceContext,
    *,
    mode: QAMode = "standard",
    sub_answers_summary: Optional[str] = None,
) -> Tuple[ChatMessage, ChatMessage]:
    """Build system and user ChatMessages for a grounded QA invocation.

    Args:
        question: User's institutional question.
        context: Budgeted, authority-labeled FormattedEvidenceContext.
        mode: Active QA mode (``standard``, ``curated_knowledge``, or
            ``decomposed``).
        sub_answers_summary: Optional formatted summary of sub-question
            findings used during ``decomposed`` synthesis.

    Returns:
        Tuple of ``(system_message, user_message)``.
    """
    system_prompt = (
        f"{_CORE_GROUNDING_RULES}\n\n"
        f"{_MODE_GUIDANCE[mode]}\n\n"
        f"{_SCHEMA_INSTRUCTIONS}"
    )

    user_parts = [f"Question:\n{question.strip()}"]
    if sub_answers_summary:
        user_parts.append(
            f"Sub-Question Findings:\n{sub_answers_summary.strip()}"
        )
    user_parts.append(f"Authorized Evidence Context:\n{context.context_text}")

    return (
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content="\n\n".join(user_parts)),
    )


def build_decomposition_messages(
    question: str,
    *,
    max_sub_questions: int = 4,
) -> Tuple[ChatMessage, ChatMessage]:
    """Build ChatMessages asking a model to decompose a complex question.

    Args:
        question: Multi-part or comparative user question.
        max_sub_questions: Maximum number of focused sub-questions allowed.

    Returns:
        Tuple of ``(system_message, user_message)``.
    """
    system_prompt = (
        "You decompose complex institutional questions into independent, "
        "focused sub-questions for document retrieval.\n"
        f"Produce at most {max_sub_questions} concise sub-questions.\n"
        "Return ONLY a valid JSON object with schema:\n"
        '{"sub_questions": ["Sub-question 1?", "Sub-question 2?"]}'
    )
    user_prompt = f"Complex Question:\n{question.strip()}"
    return (
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_prompt),
    )
