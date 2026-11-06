"""Explain why a mention is linked to an entity (FR13, ADR-0012).

ADR-0012 requires every resolved link to explain its source candidate and
approval path. ``explain_entity_link`` assembles that from stored data:
the candidate that made the link (scores, method, policy and normalizer
versions, who decided and why), all candidates ever generated, merge
redirects from the linked entity to the entity that stands for it now,
and the audit events of the linking decision.
"""

import uuid
from typing import List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.entities.lineage import (
    EntityLineageService,
    EntitySplitError,
    LineageEvent,
)
from rag_foundry.entities.models import Entity, Mention
from rag_foundry.entities.resolution import (
    ResolutionCandidate,
    ResolutionService,
)
from rag_foundry.entities.store import EntityStore
from rag_foundry.stewardship.audit import AuditRecord, AuditTrail

LINKING_DECISIONS = ("approved", "auto_approved")


class EntityLinkExplanation(BaseModel):
    """Why a mention is, or was, linked to an entity."""

    mention: Mention = Field(description="The mention")
    status: str = Field(description="The mention's resolution status")
    linked_entity_id: Optional[uuid.UUID] = Field(
        description="Entity the mention is linked to, if resolved"
    )
    current_entity: Optional[Entity] = Field(
        description="Entity that stands for the link now, after redirects"
    )
    link_candidate: Optional[ResolutionCandidate] = Field(
        description="Most recent approved or auto-approved candidate"
    )
    candidates: List[ResolutionCandidate] = Field(
        description="Every candidate of every run"
    )
    redirects: List[LineageEvent] = Field(
        description="Merges from the linked entity to the current one"
    )
    audit_events: List[AuditRecord] = Field(
        description="Audit events of the linking decision"
    )
    note: Optional[str] = Field(
        default=None, description="Anything unusual about the link"
    )


async def explain_entity_link(
    session: AsyncSession, mention_id: uuid.UUID
) -> EntityLinkExplanation:
    """Explain a mention's entity link.

    Args:
        session: Database session.
        mention_id: Mention to explain.

    Returns:
        The explanation.

    Raises:
        MentionNotFoundError: If the mention does not exist.
    """
    mention = await EntityStore(session).get_mention(mention_id)
    candidates = await ResolutionService(session).list_candidates(
        mention_id, include_history=True
    )
    links = [c for c in candidates if c.decision in LINKING_DECISIONS]
    link = links[-1] if links else None
    lineage = EntityLineageService(session)

    current: Optional[Entity] = None
    redirects: List[LineageEvent] = []
    note: Optional[str] = None
    if mention.resolved_entity_id is not None:
        redirects = await _merge_path(lineage, mention.resolved_entity_id)
        try:
            current = await lineage.current_entity(mention.resolved_entity_id)
        except EntitySplitError:
            end = redirects[-1].successor_id if redirects else (
                mention.resolved_entity_id
            )
            note = (
                f"The linked entity now redirects to entity {end}, which "
                "was split; resolve the mention again"
            )
    elif link is not None:
        linked = await EntityStore(session).get_entity(link.entity_id)
        note = (
            f"The link to entity {link.entity_id} was reset (the entity is "
            f"now {linked.status}); resolve the mention again"
        )

    events = [] if link is None else await AuditTrail(session).list_events(
        event_type="resolution.decision", resource_id=link.id
    )
    return EntityLinkExplanation(
        mention=mention,
        status=mention.resolution_status,
        linked_entity_id=mention.resolved_entity_id,
        current_entity=current,
        link_candidate=link,
        candidates=candidates,
        redirects=redirects,
        audit_events=events,
        note=note,
    )


async def _merge_path(
    lineage: EntityLineageService, entity_id: uuid.UUID
) -> List[LineageEvent]:
    """Collect merge links from an entity to its current survivor."""
    path: List[LineageEvent] = []
    current = entity_id
    seen = {current}
    while True:
        merges = [
            e for e in await lineage.history(current)
            if e.event_type == "merge" and e.predecessor_id == current
        ]
        if not merges or merges[-1].successor_id in seen:
            return path
        path.append(merges[-1])
        current = merges[-1].successor_id
        seen.add(current)
