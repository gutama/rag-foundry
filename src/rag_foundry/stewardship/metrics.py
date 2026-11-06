"""Ontology and entity quality metrics (ARCHITECTURE.md §19.3).

``compute_semantic_metrics`` reports, for one workspace:

- **duplicate entity rate**: active entities of the same class that share a
  normalized preferred label form clusters (transitively); each cluster
  contributes ``size - 1`` redundant entities, divided by active entities;
- **unresolved mention rate**: mentions not resolved (pending review or
  without candidates) divided by all mentions;
- **assertion provenance coverage**: live assertions (candidate, validated,
  approved) that cite evidence which all resolves in the workspace,
  divided by live assertions;
- **ontology constraint pass rate**: assertions whose latest validation has
  no ontology finding (evidence and confidence findings do not count),
  divided by assertions that have been validated;
- **invalid assertion rejection rate**: assertions whose latest validation
  failed and that are kept out of approved knowledge, divided by all
  assertions whose latest validation failed.

Each rate comes with its numerator and denominator, and is ``None`` when
the denominator is zero.
"""

import uuid
from typing import Dict, List, Optional, Tuple, get_args

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.db.models import (
    AssertionRecord,
    AssertionValidationRecord,
    Chunk,
    EntityMentionRecord,
)
from rag_foundry.entities.resolution import normalize_text
from rag_foundry.entities.store import EntityStore
from rag_foundry.ontology.constraints import ViolationRule

LIVE_STATUSES = ("candidate", "validated", "approved")
ONTOLOGY_RULES = frozenset(get_args(ViolationRule))


class SemanticMetrics(BaseModel):
    """Semantic quality metrics of one workspace."""

    workspace_id: uuid.UUID = Field(description="Workspace measured")
    active_entities: int = Field(description="Active entities")
    duplicate_entities: int = Field(description="Redundant active entities")
    duplicate_entity_rate: Optional[float] = Field(description="Rate")
    mentions: int = Field(description="All mentions")
    unresolved_mentions: int = Field(description="Mentions not resolved")
    unresolved_mention_rate: Optional[float] = Field(description="Rate")
    live_assertions: int = Field(description="Live assertions")
    assertions_with_provenance: int = Field(
        description="Live assertions with resolvable evidence"
    )
    assertion_provenance_coverage: Optional[float] = Field(
        description="Rate"
    )
    validated_assertions: int = Field(
        description="Assertions with at least one validation report"
    )
    constraint_passes: int = Field(
        description="Latest reports without ontology findings"
    )
    ontology_constraint_pass_rate: Optional[float] = Field(
        description="Rate"
    )
    failed_assertions: int = Field(
        description="Assertions whose latest validation failed"
    )
    rejected_failures: int = Field(
        description="Failed assertions kept out of approved knowledge"
    )
    invalid_assertion_rejection_rate: Optional[float] = Field(
        description="Rate"
    )


def _rate(numerator: int, denominator: int) -> Optional[float]:
    """Divide, or return None when there is nothing to measure."""
    return None if denominator == 0 else numerator / denominator


async def compute_semantic_metrics(
    session: AsyncSession, workspace_id: uuid.UUID
) -> SemanticMetrics:
    """Compute the §19.3 metrics for a workspace.

    Args:
        session: Database session.
        workspace_id: Workspace to measure.

    Returns:
        The metrics.
    """
    active, duplicates = await _duplicates(session, workspace_id)
    mentions, unresolved = await _mentions(session, workspace_id)
    assertions = (
        await session.execute(
            select(AssertionRecord).where(
                AssertionRecord.workspace_id == workspace_id
            )
        )
    ).scalars().all()
    live = [a for a in assertions if a.status in LIVE_STATUSES]
    covered = await _with_provenance(session, workspace_id, live)
    latest = await _latest_reports(session, [a.id for a in assertions])
    passes = sum(
        1 for report in latest.values()
        if not any(
            f["severity"] == "error" and f["rule"] in ONTOLOGY_RULES
            for f in report.findings
        )
    )
    statuses = {a.id: a.status for a in assertions}
    failed = [aid for aid, report in latest.items() if not report.valid]
    kept_out = sum(1 for aid in failed if statuses[aid] != "approved")
    return SemanticMetrics(
        workspace_id=workspace_id,
        active_entities=active,
        duplicate_entities=duplicates,
        duplicate_entity_rate=_rate(duplicates, active),
        mentions=mentions,
        unresolved_mentions=unresolved,
        unresolved_mention_rate=_rate(unresolved, mentions),
        live_assertions=len(live),
        assertions_with_provenance=covered,
        assertion_provenance_coverage=_rate(covered, len(live)),
        validated_assertions=len(latest),
        constraint_passes=passes,
        ontology_constraint_pass_rate=_rate(passes, len(latest)),
        failed_assertions=len(failed),
        rejected_failures=kept_out,
        invalid_assertion_rejection_rate=_rate(kept_out, len(failed)),
    )


async def _duplicates(
    session: AsyncSession, workspace_id: uuid.UUID
) -> Tuple[int, int]:
    """Count active entities and redundant ones in duplicate clusters."""
    entities = await EntityStore(session).list_entities(workspace_id)
    parent = {e.id: e.id for e in entities}

    def find(node: uuid.UUID) -> uuid.UUID:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    first_with_key: Dict[Tuple[str, str], uuid.UUID] = {}
    for entity in entities:
        for label in entity.preferred_labels.values():
            key = (entity.ontology_class_uri, normalize_text(label))
            if not key[1]:
                continue
            other = first_with_key.setdefault(key, entity.id)
            parent[find(entity.id)] = find(other)
    clusters = len({find(e.id) for e in entities})
    return len(entities), len(entities) - clusters


async def _mentions(
    session: AsyncSession, workspace_id: uuid.UUID
) -> Tuple[int, int]:
    """Count mentions and those not resolved."""
    statuses = (
        await session.execute(
            select(EntityMentionRecord.resolution_status).where(
                EntityMentionRecord.workspace_id == workspace_id
            )
        )
    ).scalars().all()
    return len(statuses), sum(1 for s in statuses if s != "resolved")


async def _with_provenance(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    assertions: List[AssertionRecord],
) -> int:
    """Count assertions citing evidence that all resolves."""
    cited = {c for a in assertions for c in a.source_chunk_ids}
    found = set()
    if cited:
        found = {
            str(c) for c in (
                await session.execute(
                    select(Chunk.id).where(
                        Chunk.id.in_([uuid.UUID(c) for c in cited]),
                        Chunk.workspace_id == workspace_id,
                    )
                )
            ).scalars().all()
        }
    return sum(
        1 for a in assertions
        if a.source_chunk_ids and set(a.source_chunk_ids) <= found
    )


async def _latest_reports(
    session: AsyncSession, assertion_ids: List[uuid.UUID]
) -> Dict[uuid.UUID, AssertionValidationRecord]:
    """Return each assertion's most recent validation report."""
    if not assertion_ids:
        return {}
    ranked = (
        select(
            AssertionValidationRecord.id,
            func.row_number()
            .over(
                partition_by=AssertionValidationRecord.assertion_id,
                order_by=(
                    AssertionValidationRecord.created_at.desc(),
                    AssertionValidationRecord.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(AssertionValidationRecord.assertion_id.in_(assertion_ids))
        .subquery()
    )
    reports = (
        await session.execute(
            select(AssertionValidationRecord).join(
                ranked,
                (ranked.c.id == AssertionValidationRecord.id)
                & (ranked.c.position == 1),
            )
        )
    ).scalars().all()
    return {report.assertion_id: report for report in reports}
