"""Entity resolution: normalization and candidate generation (ADR-0012).

Resolution follows ARCHITECTURE.md §8.6:

    mention -> normalization -> candidate generation -> ontology class
    constraints -> deterministic identifiers -> similarity and rule
    scoring -> confidence threshold -> automatic match or steward review

``CandidateGenerator`` covers the steps up to scoring; ``ResolutionService``
stores candidates and applies a ``ResolutionPolicy``. Signals, strongest
first:

==================  =====================================================
Signal              Score
==================  =====================================================
identifier          1.0 when mention and entity share a typed identifier
exact_label         0.95 when the normalized text equals a preferred label
exact_alias         0.9 when it equals an alias
similarity          0.85 x the best difflib ratio over labels and aliases
                    (character order or sorted tokens), so a near match
                    never outranks an exact one
==================  =====================================================

A candidate's score is its strongest signal; the breakdown records all
four. Entities are excluded when they are inactive, in another workspace,
of an incompatible ontology class, or hold a *different* value for an
identifier scheme the mention carries, since authoritative identifiers
prove they are different entities. Generation is deterministic: ties are
broken by canonical IRI.

The default policy never links a mention automatically (ADR-0012: automated
resolution may auto-approve only under an explicitly governed policy). An
enabled policy auto-approves only when exactly one candidate reaches its
threshold, judged before the candidate list is truncated, so ties always go
to a steward.
"""

import unicodedata
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.db.models import (
    EntityMentionRecord,
    EntityRecord,
    ResolutionCandidateRecord,
)
from rag_foundry.entities.models import Entity, Mention
from rag_foundry.entities.store import (
    EntityStore,
    MentionNotFoundError,
    as_utc,
    mention_from_record,
)
from rag_foundry.ontology.models import OntologyRelease
from rag_foundry.stewardship.audit import record_audit
from rag_foundry.stewardship.queue_records import (
    CANDIDATE_KIND,
    enqueue,
    settle,
)

NORMALIZER_VERSION = "1"

IDENTIFIER_SCORE = 1.0
EXACT_LABEL_SCORE = 0.95
EXACT_ALIAS_SCORE = 0.9
SIMILARITY_WEIGHT = 0.85

MatchMethod = Literal["identifier", "exact_label", "exact_alias", "similarity"]


def normalize_text(text: str) -> str:
    """Normalize a name for matching.

    Applies NFKC (folding width and ligatures), case folding, removal of
    diacritics, replacement of punctuation and symbols with spaces, and
    whitespace collapsing. Versioned as ``NORMALIZER_VERSION``.

    Args:
        text: Raw text.

    Returns:
        The normalized text, possibly empty.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    characters = []
    for char in unicodedata.normalize("NFKD", folded):
        category = unicodedata.category(char)
        if category == "Mn":
            continue
        characters.append(" " if category[0] in "PSZC" else char)
    return " ".join("".join(characters).split())


def similarity(left: str, right: str) -> float:
    """Compare two normalized names, ignoring token order.

    Args:
        left: Normalized text.
        right: Normalized text.

    Returns:
        The better of the character-order and sorted-token difflib
        ratios, between 0 and 1.
    """
    if not left or not right:
        return 0.0
    direct = SequenceMatcher(None, left, right, autojunk=False).ratio()
    tokens = SequenceMatcher(
        None,
        " ".join(sorted(left.split())),
        " ".join(sorted(right.split())),
        autojunk=False,
    ).ratio()
    return max(direct, tokens)


class CandidateMatch(BaseModel):
    """A scored candidate entity for a mention."""

    entity_id: uuid.UUID = Field(description="Candidate entity id")
    canonical_uri: str = Field(description="Candidate canonical IRI")
    method: MatchMethod = Field(description="Strongest matching signal")
    score: float = Field(ge=0.0, le=1.0, description="Candidate score")
    score_breakdown: Dict[str, float] = Field(
        description="Raw value of every signal"
    )
    matched_text: Optional[str] = Field(
        default=None, description="Label, alias or scheme:value matched"
    )


class CandidateGenerator:
    """Generates ranked candidate entities for mentions."""

    def __init__(
        self,
        release: Optional[OntologyRelease] = None,
        min_similarity: float = 0.8,
        max_candidates: int = 5,
    ) -> None:
        """Configure candidate generation.

        Args:
            release: Pinned ontology release for class compatibility.
                Without one, a class hint only matches the same class.
            min_similarity: Lowest difflib ratio that counts as a match.
            max_candidates: Maximum number of candidates returned.

        Raises:
            ValueError: If a setting is out of range.
        """
        if not 0.0 <= min_similarity <= 1.0:
            raise ValueError("min_similarity must be between 0 and 1")
        if max_candidates < 1:
            raise ValueError("max_candidates must be at least 1")
        self.release = release
        self.min_similarity = min_similarity
        self.max_candidates = max_candidates

    def generate(
        self, mention: Mention, entities: Sequence[Entity]
    ) -> List[CandidateMatch]:
        """Score eligible entities and keep the best ``max_candidates``.

        Args:
            mention: The mention to resolve.
            entities: Entities to consider; ineligible ones are skipped.

        Returns:
            Candidates sorted by score, then canonical IRI, truncated.
        """
        return self.rank(mention, entities)[: self.max_candidates]

    def rank(
        self, mention: Mention, entities: Sequence[Entity]
    ) -> List[CandidateMatch]:
        """Score every eligible entity against a mention.

        Args:
            mention: The mention to resolve.
            entities: Entities to consider; ineligible ones are skipped.

        Returns:
            All candidates sorted by score, then canonical IRI.
        """
        text = normalize_text(mention.surface_text)
        matches = []
        for entity in entities:
            if self._eligible(mention, entity):
                match = self._score(mention, text, entity)
                if match is not None:
                    matches.append(match)
        matches.sort(key=lambda m: (-m.score, m.canonical_uri))
        return matches

    def _eligible(self, mention: Mention, entity: Entity) -> bool:
        """Check workspace, status, class and identifier compatibility."""
        if entity.workspace_id != mention.workspace_id:
            return False
        if entity.status != "active":
            return False
        if not self._class_compatible(
            entity.ontology_class_uri, mention.ontology_class_uri
        ):
            return False
        for scheme, value in mention.identifiers.items():
            held = entity.identifiers.get(scheme)
            if held is not None and held != value:
                return False
        return True

    def _class_compatible(
        self, entity_class: str, expected: Optional[str]
    ) -> bool:
        """Check that an entity class is the expected class or below it."""
        if expected is None:
            return True
        if self.release is None:
            return entity_class == expected
        try:
            return self.release.is_subclass_of(entity_class, expected)
        except KeyError:
            return False

    def _score(
        self, mention: Mention, text: str, entity: Entity
    ) -> Optional[CandidateMatch]:
        """Score one eligible entity; None if no signal fires."""
        shared = sorted(
            scheme
            for scheme, value in mention.identifiers.items()
            if entity.identifiers.get(scheme) == value
        )
        aliases = [a for names in entity.aliases.values() for a in names]
        exact_label = _exact(text, list(entity.preferred_labels.values()))
        exact_alias = _exact(text, aliases)
        best_ratio, best_text = max(
            (
                (similarity(text, normalize_text(name)), name)
                for name in entity.all_labels()
            ),
            default=(0.0, None),
        )

        signals: List[Tuple[float, MatchMethod, Optional[str]]] = []
        if shared:
            scheme = shared[0]
            signals.append(
                (
                    IDENTIFIER_SCORE,
                    "identifier",
                    f"{scheme}:{mention.identifiers[scheme]}",
                )
            )
        if exact_label is not None:
            signals.append((EXACT_LABEL_SCORE, "exact_label", exact_label))
        if exact_alias is not None:
            signals.append((EXACT_ALIAS_SCORE, "exact_alias", exact_alias))
        if best_ratio > 0.0 and best_ratio >= self.min_similarity:
            signals.append(
                (
                    round(SIMILARITY_WEIGHT * best_ratio, 6),
                    "similarity",
                    best_text,
                )
            )
        if not signals:
            return None
        score, method, matched_text = max(signals, key=lambda s: s[0])
        return CandidateMatch(
            entity_id=entity.id,
            canonical_uri=entity.canonical_uri,
            method=method,
            score=score,
            score_breakdown={
                "identifier": 1.0 if shared else 0.0,
                "exact_label": 1.0 if exact_label is not None else 0.0,
                "exact_alias": 1.0 if exact_alias is not None else 0.0,
                "similarity": round(best_ratio, 6),
            },
            matched_text=matched_text,
        )


def _exact(text: str, names: List[str]) -> Optional[str]:
    """Return the first name whose normalized form equals the text."""
    if not text:
        return None
    return next((n for n in names if normalize_text(n) == text), None)


# --- Policies and stored decisions ----------------------------------------

CandidateDecision = Literal[
    "pending", "auto_approved", "approved", "rejected", "superseded"
]


class ResolutionPolicy(BaseModel):
    """A versioned, immutable policy for scoring and auto-approval."""

    model_config = ConfigDict(frozen=True)

    policy_id: str = Field(default="default", description="Policy name")
    version: str = Field(default="1", description="Policy version")
    auto_approve: bool = Field(
        default=False, description="Link single matches automatically"
    )
    auto_approve_threshold: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Lowest auto-link score"
    )
    min_similarity: float = Field(
        default=0.8, ge=0.0, le=1.0, description="Lowest similarity ratio"
    )
    max_candidates: int = Field(
        default=5, ge=1, description="Candidates stored per run"
    )

    @field_validator("policy_id", "version")
    @classmethod
    def _check_not_blank(cls, value: str) -> str:
        """Reject blank names and versions."""
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value

    @property
    def key(self) -> str:
        """Identify the policy and version, e.g. ``default@1``."""
        return f"{self.policy_id}@{self.version}"


DEFAULT_POLICY = ResolutionPolicy()
RE_RESOLUTION_ACTOR = "system:re-resolution"


class ResolutionCandidate(BaseModel):
    """A stored candidate with the context needed to explain it."""

    id: uuid.UUID = Field(description="Candidate id")
    mention_id: uuid.UUID = Field(description="Mention being resolved")
    entity_id: uuid.UUID = Field(description="Candidate entity")
    workspace_id: uuid.UUID = Field(description="Workspace")
    run_number: int = Field(description="Resolution run, from 1")
    rank: int = Field(description="Rank within the run, from 1")
    score: float = Field(description="Candidate score")
    method: MatchMethod = Field(description="Strongest signal")
    score_breakdown: Dict[str, float] = Field(description="All signals")
    matched_text: Optional[str] = Field(description="Text matched")
    policy_id: str = Field(description="Policy used")
    policy_version: str = Field(description="Policy version used")
    normalizer_version: str = Field(description="Normalizer version used")
    ontology_release_id: Optional[uuid.UUID] = Field(
        description="Ontology release used for class checks"
    )
    decision: CandidateDecision = Field(description="Decision so far")
    decided_by: Optional[str] = Field(description="Actor or policy")
    decided_at: Optional[datetime] = Field(description="Decision time")
    decision_reason: Optional[str] = Field(description="Stated reason")
    created_at: datetime = Field(description="Creation time")


class ResolutionOutcome(BaseModel):
    """The result of one resolution run."""

    mention: Mention = Field(description="The mention after the run")
    candidates: List[ResolutionCandidate] = Field(
        description="Candidates stored by this run, by rank"
    )
    auto_approved: bool = Field(description="True if the policy linked it")


class ResolutionError(Exception):
    """Base class for resolution errors."""


class CandidateNotFoundError(ResolutionError):
    """Raised when a candidate id is unknown."""


class ResolutionStateError(ResolutionError):
    """Raised when an operation does not fit the current state."""


def _candidate_from_record(
    record: ResolutionCandidateRecord,
) -> ResolutionCandidate:
    """Convert a candidate record to a model."""
    return ResolutionCandidate(
        id=record.id,
        mention_id=record.mention_id,
        entity_id=record.entity_id,
        workspace_id=record.workspace_id,
        run_number=record.run_number,
        rank=record.rank,
        score=record.score,
        method=record.method,
        score_breakdown=record.score_breakdown,
        matched_text=record.matched_text,
        policy_id=record.policy_id,
        policy_version=record.policy_version,
        normalizer_version=record.normalizer_version,
        ontology_release_id=record.ontology_release_id,
        decision=record.decision,
        decided_by=record.decided_by,
        decided_at=(
            None if record.decided_at is None else as_utc(record.decided_at)
        ),
        decision_reason=record.decision_reason,
        created_at=as_utc(record.created_at),
    )


def _require_actor(actor_id: str) -> str:
    """Reject blank actor ids.

    Raises:
        ValueError: If the actor id is blank.
    """
    if not actor_id.strip():
        raise ValueError("Decisions must name the actor who made them")
    return actor_id


class ResolutionService:
    """Resolves mentions into stored candidates and records decisions.

    Methods flush but never commit; the caller owns the transaction.
    """

    def __init__(
        self,
        session: AsyncSession,
        release: Optional[OntologyRelease] = None,
    ) -> None:
        """Initialize the service.

        Args:
            session: SQLAlchemy AsyncSession.
            release: Pinned ontology release for class compatibility.
        """
        self.session = session
        self.release = release

    async def resolve(
        self,
        mention_id: uuid.UUID,
        policy: ResolutionPolicy = DEFAULT_POLICY,
    ) -> ResolutionOutcome:
        """Generate, store and decide candidates for a mention.

        Pending candidates of earlier runs are superseded. The mention
        becomes ``resolved`` if the policy auto-approves, ``candidate`` if
        candidates await review, and ``unresolved`` otherwise.

        Args:
            mention_id: Mention to resolve.
            policy: Scoring and auto-approval policy.

        Returns:
            The run's outcome.

        Raises:
            MentionNotFoundError: If the mention does not exist.
            ResolutionStateError: If the mention is already resolved.
        """
        record = await self._mention_record(mention_id)
        if record.resolution_status == "resolved":
            raise ResolutionStateError(
                f"Mention {mention_id} is already resolved"
            )
        mention = mention_from_record(record)
        now = datetime.now(timezone.utc)
        await self._supersede_pending(mention_id, now)
        run_number = await self._next_run_number(mention_id)

        entities = await EntityStore(self.session).list_entities(
            mention.workspace_id
        )
        generator = CandidateGenerator(
            release=self.release,
            min_similarity=policy.min_similarity,
            max_candidates=policy.max_candidates,
        )
        ranked = generator.rank(mention, entities)
        winner = self._auto_winner(ranked, policy)
        kept = ranked[: policy.max_candidates]

        records = []
        for rank, match in enumerate(kept, start=1):
            decision, decided_by, decided_at = "pending", None, None
            if winner is not None:
                decision = "auto_approved" if match is winner else "superseded"
                decided_by, decided_at = f"policy:{policy.key}", now
            records.append(
                ResolutionCandidateRecord(
                    mention_id=mention_id,
                    entity_id=match.entity_id,
                    workspace_id=mention.workspace_id,
                    run_number=run_number,
                    rank=rank,
                    score=match.score,
                    method=match.method,
                    score_breakdown=dict(match.score_breakdown),
                    matched_text=match.matched_text,
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    normalizer_version=NORMALIZER_VERSION,
                    ontology_release_id=(
                        None if self.release is None
                        else self.release.release_id
                    ),
                    decision=decision,
                    decided_by=decided_by,
                    decided_at=decided_at,
                    created_at=now,
                )
            )
        self.session.add_all(records)

        if winner is not None:
            record.resolution_status = "resolved"
            record.resolved_entity_id = winner.entity_id
        else:
            record.resolution_status = "candidate" if kept else "unresolved"
        await self.session.flush()
        for candidate in records:
            if candidate.decision == "auto_approved":
                await self._audit_decision(candidate, candidate.decided_by,
                                           None)
            if candidate.decision == "pending":
                await enqueue(
                    self.session, CANDIDATE_KIND, candidate.id,
                    mention.workspace_id, mention.semantic_profile_id,
                    f"Candidate {candidate.rank} for mention {mention_id}: "
                    f"{candidate.method} {candidate.score:.3f}",
                )
        await self.session.flush()
        return ResolutionOutcome(
            mention=mention_from_record(record),
            candidates=[_candidate_from_record(r) for r in records],
            auto_approved=winner is not None,
        )

    async def approve_candidate(
        self,
        candidate_id: uuid.UUID,
        actor_id: str,
        reason: Optional[str] = None,
    ) -> ResolutionCandidate:
        """Approve a pending candidate and link its mention.

        The run's other pending candidates are superseded.

        Args:
            candidate_id: Candidate to approve.
            actor_id: Steward making the decision.
            reason: Why the candidate is right.

        Returns:
            The approved candidate.

        Raises:
            ValueError: If the actor id is blank.
            CandidateNotFoundError: If the candidate does not exist.
            ResolutionStateError: If the candidate is not pending, or its
                entity is no longer active.
        """
        _require_actor(actor_id)
        candidate = await self._pending_record(candidate_id)
        entity = await self.session.get(EntityRecord, candidate.entity_id)
        if entity is None or entity.status != "active":
            raise ResolutionStateError(
                f"Entity {candidate.entity_id} is no longer active; "
                "resolve the mention again"
            )
        now = datetime.now(timezone.utc)
        self._decide(candidate, "approved", actor_id, reason, now)
        await self._audit_decision(candidate, actor_id, reason)
        await settle(self.session, CANDIDATE_KIND, candidate.id,
                     "approved", actor_id, reason)
        for other in await self._pending_records(candidate.mention_id):
            if other.id != candidate.id:
                self._decide(other, "superseded", actor_id, None, now)
                await settle(self.session, CANDIDATE_KIND, other.id,
                             "closed", actor_id,
                             "Another candidate was approved")
        mention = await self._mention_record(candidate.mention_id)
        mention.resolution_status = "resolved"
        mention.resolved_entity_id = candidate.entity_id
        await self.session.flush()
        return _candidate_from_record(candidate)

    async def reject_candidate(
        self,
        candidate_id: uuid.UUID,
        actor_id: str,
        reason: Optional[str] = None,
    ) -> ResolutionCandidate:
        """Reject a pending candidate.

        When no pending candidate remains, the mention becomes unresolved.

        Args:
            candidate_id: Candidate to reject.
            actor_id: Steward making the decision.
            reason: Why the candidate is wrong.

        Returns:
            The rejected candidate.

        Raises:
            ValueError: If the actor id is blank.
            CandidateNotFoundError: If the candidate does not exist.
            ResolutionStateError: If the candidate is not pending.
        """
        _require_actor(actor_id)
        candidate = await self._pending_record(candidate_id)
        self._decide(
            candidate, "rejected", actor_id, reason,
            datetime.now(timezone.utc),
        )
        await self._audit_decision(candidate, actor_id, reason)
        await settle(self.session, CANDIDATE_KIND, candidate.id,
                     "rejected", actor_id, reason)
        await self.session.flush()
        if not await self._pending_records(candidate.mention_id):
            mention = await self._mention_record(candidate.mention_id)
            mention.resolution_status = "unresolved"
            await self.session.flush()
        return _candidate_from_record(candidate)

    async def get_candidate(
        self, candidate_id: uuid.UUID
    ) -> ResolutionCandidate:
        """Load a candidate.

        Raises:
            CandidateNotFoundError: If the candidate does not exist.
        """
        return _candidate_from_record(
            await self._candidate_record(candidate_id)
        )

    async def list_candidates(
        self, mention_id: uuid.UUID, include_history: bool = False
    ) -> List[ResolutionCandidate]:
        """List a mention's candidates, ordered by run and rank.

        Args:
            mention_id: Mention id.
            include_history: Include candidates of earlier runs.

        Returns:
            Candidates of the latest run, or of every run.
        """
        stmt = (
            select(ResolutionCandidateRecord)
            .where(ResolutionCandidateRecord.mention_id == mention_id)
            .order_by(
                ResolutionCandidateRecord.run_number,
                ResolutionCandidateRecord.rank,
            )
        )
        if not include_history:
            latest = await self._next_run_number(mention_id) - 1
            stmt = stmt.where(
                ResolutionCandidateRecord.run_number == latest
            )
        records = (await self.session.execute(stmt)).scalars().all()
        return [_candidate_from_record(r) for r in records]

    # --- Helpers ----------------------------------------------------------

    @staticmethod
    def _auto_winner(
        ranked: List[CandidateMatch], policy: ResolutionPolicy
    ) -> Optional[CandidateMatch]:
        """Pick the single candidate at the threshold, if exactly one."""
        if not policy.auto_approve:
            return None
        qualifying = [
            m for m in ranked if m.score >= policy.auto_approve_threshold
        ]
        return qualifying[0] if len(qualifying) == 1 else None

    async def _audit_decision(
        self,
        record: ResolutionCandidateRecord,
        actor_id: str,
        reason: Optional[str],
    ) -> None:
        """Record a candidate decision in the audit trail."""
        await record_audit(
            self.session, "resolution.decision", actor_id,
            "resolution_candidate", record.id,
            {
                "mention_id": record.mention_id,
                "entity_id": record.entity_id,
                "decision": record.decision,
                "reason": reason,
                "score": record.score,
                "method": record.method,
                "policy": f"{record.policy_id}@{record.policy_version}",
            },
        )

    @staticmethod
    def _decide(
        record: ResolutionCandidateRecord,
        decision: str,
        actor_id: str,
        reason: Optional[str],
        when: datetime,
    ) -> None:
        """Record a decision on a candidate."""
        record.decision = decision
        record.decided_by = actor_id
        record.decision_reason = reason
        record.decided_at = when

    async def _mention_record(
        self, mention_id: uuid.UUID
    ) -> EntityMentionRecord:
        """Load a mention record.

        Raises:
            MentionNotFoundError: If the mention does not exist.
        """
        record = await self.session.get(EntityMentionRecord, mention_id)
        if record is None:
            raise MentionNotFoundError(f"Mention {mention_id} not found")
        return record

    async def _candidate_record(
        self, candidate_id: uuid.UUID
    ) -> ResolutionCandidateRecord:
        """Load a candidate record.

        Raises:
            CandidateNotFoundError: If the candidate does not exist.
        """
        record = await self.session.get(
            ResolutionCandidateRecord, candidate_id
        )
        if record is None:
            raise CandidateNotFoundError(
                f"Candidate {candidate_id} not found"
            )
        return record

    async def _pending_record(
        self, candidate_id: uuid.UUID
    ) -> ResolutionCandidateRecord:
        """Load a candidate record that must still be pending.

        Raises:
            CandidateNotFoundError: If the candidate does not exist.
            ResolutionStateError: If it is already decided.
        """
        record = await self._candidate_record(candidate_id)
        if record.decision != "pending":
            raise ResolutionStateError(
                f"Candidate {candidate_id} is already {record.decision}"
            )
        return record

    async def _pending_records(
        self, mention_id: uuid.UUID
    ) -> List[ResolutionCandidateRecord]:
        """List a mention's pending candidate records."""
        stmt = select(ResolutionCandidateRecord).where(
            ResolutionCandidateRecord.mention_id == mention_id,
            ResolutionCandidateRecord.decision == "pending",
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def _supersede_pending(
        self, mention_id: uuid.UUID, when: datetime
    ) -> None:
        """Supersede pending candidates before a new run."""
        for record in await self._pending_records(mention_id):
            self._decide(record, "superseded", RE_RESOLUTION_ACTOR,
                         None, when)
            await settle(self.session, CANDIDATE_KIND, record.id, "closed",
                         RE_RESOLUTION_ACTOR,
                         "Superseded by a new resolution run")

    async def _next_run_number(self, mention_id: uuid.UUID) -> int:
        """Return the number of the next resolution run for a mention."""
        stmt = select(
            func.max(ResolutionCandidateRecord.run_number)
        ).where(ResolutionCandidateRecord.mention_id == mention_id)
        latest = (await self.session.execute(stmt)).scalar_one_or_none()
        return (latest or 0) + 1
