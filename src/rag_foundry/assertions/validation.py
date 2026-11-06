"""Assertion validation against a pinned ontology release (ADR-0014).

Validation checks, in order:

1. **Entities.** Subject and object follow merge redirects (the assertion is
   re-pointed and the redirect noted); they must be active and in the
   assertion's workspace. A split entity has no single successor, so it is
   an error.
2. **Evidence.** Every cited chunk must exist in the assertion's workspace.
   At least one chunk is required for extracted assertions, and for
   curated ones when the property sets ``provenance_required``.
3. **Ontology constraints.** Terms, domain, range, value kind, datatype and
   allowed values (``ConstraintValidator``), plus ``max_count`` counted over
   the subject's other validated and approved assertions.
4. **Confidence.** At least the policy minimum.

Each run stores a report pinned to the release and policy versions. A
candidate becomes ``validated`` or ``invalid``; a validated assertion that
fails re-validation becomes ``invalid``. An approved assertion keeps its
status: a failed revalidation flags it for steward review (ADR-0014 never
withdraws approval silently) and a passing one clears the flag. Only
approved releases are accepted, so constraints always come from a
published version.

After a merge, ``revalidate_for_entity`` re-points every live assertion
naming the merged entity to its survivor.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.assertions.lifecycle import (
    AssertionStateError,
    AssertionStore,
    require_actor,
)
from rag_foundry.db.models import (
    AssertionRecord,
    AssertionValidationRecord,
    Chunk,
    EntityRecord,
)
from rag_foundry.entities.lineage import EntityLineageService, EntitySplitError
from rag_foundry.entities.store import as_utc
from rag_foundry.ontology.constraints import ConstraintValidator, Statement
from rag_foundry.ontology.models import OntologyRelease
from rag_foundry.stewardship.queue_records import (
    ASSERTION_KIND,
    enqueue,
    settle,
)

VALIDATOR_ACTOR = "system:validator"
COUNTED_STATUSES = ("validated", "approved")
VALIDATABLE_STATUSES = ("candidate", "validated", "approved")


class AssertionPolicy(BaseModel):
    """A versioned, immutable policy for assertion validation."""

    model_config = ConfigDict(frozen=True)

    policy_id: str = Field(default="default", min_length=1)
    version: str = Field(default="1", min_length=1)
    min_confidence: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Lowest confidence"
    )


DEFAULT_ASSERTION_POLICY = AssertionPolicy()


class ValidationFinding(BaseModel):
    """One observation of a validation run."""

    rule: str = Field(description="Check that produced the finding")
    severity: Literal["error", "info"] = Field(description="Impact")
    message: str = Field(description="Explanation")


class AssertionValidationReport(BaseModel):
    """The stored outcome of one validation run."""

    id: uuid.UUID = Field(description="Report id")
    assertion_id: uuid.UUID = Field(description="Assertion validated")
    ontology_release_id: uuid.UUID = Field(description="Pinned release")
    ontology_version: str = Field(description="Its version")
    policy_id: str = Field(description="Policy used")
    policy_version: str = Field(description="Its version")
    valid: bool = Field(description="True if no error was found")
    findings: List[ValidationFinding] = Field(description="Findings")
    actor_id: str = Field(description="Who ran the validation")
    created_at: datetime = Field(description="When")


def _report_from_record(
    record: AssertionValidationRecord,
) -> AssertionValidationReport:
    """Convert a validation record to a model."""
    return AssertionValidationReport(
        id=record.id,
        assertion_id=record.assertion_id,
        ontology_release_id=record.ontology_release_id,
        ontology_version=record.ontology_version,
        policy_id=record.policy_id,
        policy_version=record.policy_version,
        valid=record.valid,
        findings=[ValidationFinding(**f) for f in record.findings],
        actor_id=record.actor_id,
        created_at=as_utc(record.created_at),
    )


class AssertionValidator:
    """Validates assertions and records the reports."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the validator.

        Args:
            session: SQLAlchemy AsyncSession.
        """
        self.session = session
        self._store = AssertionStore(session)
        self._lineage = EntityLineageService(session)

    async def validate(
        self,
        assertion_id: uuid.UUID,
        release: OntologyRelease,
        policy: AssertionPolicy = DEFAULT_ASSERTION_POLICY,
        actor_id: str = VALIDATOR_ACTOR,
    ) -> AssertionValidationReport:
        """Validate an assertion and record the outcome.

        Args:
            assertion_id: Assertion to validate.
            release: Approved ontology release to validate against.
            policy: Validation policy.
            actor_id: Who runs the validation.

        Returns:
            The stored report.

        Raises:
            ValueError: If the release is not approved or the actor blank.
            AssertionNotFoundError: If the assertion does not exist.
            AssertionStateError: If the assertion is invalid, rejected or
                superseded.
        """
        require_actor(actor_id)
        if release.status != "approved":
            raise ValueError(
                "Assertions are validated against approved releases only"
            )
        record = await self._store.load_record(assertion_id)
        if record.status not in VALIDATABLE_STATUSES:
            raise AssertionStateError(
                f"Assertion {assertion_id} is {record.status} and cannot be "
                "validated"
            )
        findings = await self.check(record, release, policy)
        report = await self._save_report(
            record, release, policy, findings, actor_id
        )
        summary = self._summary(report)
        if record.status == "candidate":
            target = "validated" if report.valid else "invalid"
            await self._store.apply_transition(
                record, target, actor_id, summary
            )
        elif record.status == "validated" and not report.valid:
            await self._store.apply_transition(
                record, "invalid", actor_id, summary
            )
        elif record.status == "approved":
            record.requires_review = not report.valid
            record.review_reason = None if report.valid else summary
            if report.valid:
                await settle(self.session, ASSERTION_KIND, record.id,
                             "closed", actor_id, "Revalidation passed")
            else:
                await enqueue(
                    self.session, ASSERTION_KIND, record.id,
                    record.workspace_id, record.semantic_profile_id, summary,
                )
            await self.session.flush()
        return report

    async def revalidate_for_entity(
        self,
        entity_id: uuid.UUID,
        release: OntologyRelease,
        policy: AssertionPolicy = DEFAULT_ASSERTION_POLICY,
        actor_id: str = VALIDATOR_ACTOR,
    ) -> List[AssertionValidationReport]:
        """Revalidate every live assertion naming an entity.

        Run after a merge to re-point assertions to the survivor.

        Args:
            entity_id: Entity named as subject or object.
            release: Approved ontology release.
            policy: Validation policy.
            actor_id: Who runs the validation.

        Returns:
            One report per revalidated assertion, oldest assertion first.
        """
        stmt = (
            select(AssertionRecord.id)
            .where(
                or_(
                    AssertionRecord.subject_entity_id == entity_id,
                    AssertionRecord.object_entity_id == entity_id,
                ),
                AssertionRecord.status.in_(VALIDATABLE_STATUSES),
            )
            .order_by(AssertionRecord.created_at, AssertionRecord.id)
        )
        assertion_ids = (await self.session.execute(stmt)).scalars().all()
        return [
            await self.validate(assertion_id, release, policy, actor_id)
            for assertion_id in assertion_ids
        ]

    async def check(
        self,
        record: AssertionRecord,
        release: OntologyRelease,
        policy: AssertionPolicy,
    ) -> List[ValidationFinding]:
        """Run every check on a loaded record, re-pointing redirects.

        Args:
            record: The assertion record (may be updated by redirects).
            release: Approved ontology release.
            policy: Validation policy.

        Returns:
            Findings in the order the checks ran.
        """
        findings: List[ValidationFinding] = []
        subject = await self._resolve(record, "subject_entity_id", findings)
        target = None
        if record.object_entity_id is not None:
            target = await self._resolve(record, "object_entity_id", findings)
        await self._check_evidence(record, release, findings)
        if subject is not None and (
            record.object_entity_id is None or target is not None
        ):
            await self._check_ontology(
                record, release, subject, target, findings
            )
        if record.confidence < policy.min_confidence:
            findings.append(
                ValidationFinding(
                    rule="low_confidence",
                    severity="error",
                    message=(
                        f"Confidence {record.confidence} is below the "
                        f"policy minimum {policy.min_confidence}"
                    ),
                )
            )
        await self.session.flush()
        return findings

    async def list_reports(
        self, assertion_id: uuid.UUID
    ) -> List[AssertionValidationReport]:
        """List an assertion's validation reports, oldest first."""
        stmt = (
            select(AssertionValidationRecord)
            .where(AssertionValidationRecord.assertion_id == assertion_id)
            .order_by(
                AssertionValidationRecord.created_at,
                AssertionValidationRecord.id,
            )
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [_report_from_record(r) for r in records]

    async def latest_report(
        self, assertion_id: uuid.UUID
    ) -> Optional[AssertionValidationReport]:
        """Return an assertion's most recent report, if any."""
        stmt = (
            select(AssertionValidationRecord)
            .where(AssertionValidationRecord.assertion_id == assertion_id)
            .order_by(
                AssertionValidationRecord.created_at.desc(),
                AssertionValidationRecord.id.desc(),
            )
            .limit(1)
        )
        record = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if record is None else _report_from_record(record)

    # --- Checks -----------------------------------------------------------

    async def _resolve(
        self,
        record: AssertionRecord,
        field: str,
        findings: List[ValidationFinding],
    ) -> Optional[EntityRecord]:
        """Follow redirects for one entity reference and check it."""
        entity_id = getattr(record, field)
        role = "subject" if field == "subject_entity_id" else "object"
        try:
            current = await self._lineage.current_entity(entity_id)
        except EntitySplitError:
            findings.append(
                ValidationFinding(
                    rule="entity_split",
                    severity="error",
                    message=(
                        f"The {role} entity {entity_id} was split; the "
                        "assertion must name one of its successors"
                    ),
                )
            )
            return None
        if current.id != entity_id:
            setattr(record, field, current.id)
            findings.append(
                ValidationFinding(
                    rule="entity_redirected",
                    severity="info",
                    message=(
                        f"The {role} entity {entity_id} was merged into "
                        f"{current.id}; the assertion now points there"
                    ),
                )
            )
        if current.status != "active":
            findings.append(
                ValidationFinding(
                    rule="entity_inactive",
                    severity="error",
                    message=f"The {role} entity {current.id} is "
                    f"{current.status}",
                )
            )
        if current.workspace_id != record.workspace_id:
            findings.append(
                ValidationFinding(
                    rule="entity_workspace",
                    severity="error",
                    message=(
                        f"The {role} entity {current.id} belongs to another "
                        "workspace"
                    ),
                )
            )
        return await self.session.get(EntityRecord, current.id)

    async def _check_evidence(
        self,
        record: AssertionRecord,
        release: OntologyRelease,
        findings: List[ValidationFinding],
    ) -> None:
        """Check that evidence exists, resolves and shares the workspace."""
        prop = release.get_property(record.property_uri)
        required = record.origin == "extracted" or (
            prop is None or prop.provenance_required
        )
        chunk_ids = [uuid.UUID(c) for c in record.source_chunk_ids]
        if not chunk_ids:
            if required:
                findings.append(
                    ValidationFinding(
                        rule="missing_evidence",
                        severity="error",
                        message="The assertion cites no evidence chunk",
                    )
                )
            return
        stmt = select(Chunk.id, Chunk.workspace_id).where(
            Chunk.id.in_(chunk_ids)
        )
        found = dict((await self.session.execute(stmt)).all())
        missing = [c for c in chunk_ids if c not in found]
        if missing:
            findings.append(
                ValidationFinding(
                    rule="unknown_evidence",
                    severity="error",
                    message=f"Evidence chunks not found: {missing}",
                )
            )
        foreign = [
            c for c, ws in found.items() if ws != record.workspace_id
        ]
        if foreign:
            findings.append(
                ValidationFinding(
                    rule="evidence_workspace",
                    severity="error",
                    message=(
                        f"Evidence chunks from another workspace: {foreign}"
                    ),
                )
            )

    async def _check_ontology(
        self,
        record: AssertionRecord,
        release: OntologyRelease,
        subject: EntityRecord,
        target: Optional[EntityRecord],
        findings: List[ValidationFinding],
    ) -> None:
        """Check ontology constraints, including maxCount."""
        validator = ConstraintValidator(release)
        statement = Statement(
            subject=str(subject.id),
            subject_class_uri=subject.ontology_class_uri,
            property_uri=record.property_uri,
            object_uri=None if target is None else target.canonical_uri,
            object_class_uri=(
                None if target is None else target.ontology_class_uri
            ),
            literal=record.literal_value,
        )
        violations = validator.check_statement(statement)
        others = await self._count_others(record)
        violations += [
            v
            for v in validator.check_cardinality(
                str(subject.id), subject.ontology_class_uri,
                record.property_uri, others + 1,
            )
            if v.rule == "max_count"
        ]
        findings.extend(
            ValidationFinding(rule=v.rule, severity="error", message=v.message)
            for v in violations
        )

    async def _count_others(self, record: AssertionRecord) -> int:
        """Count the subject's other counted assertions for the property."""
        stmt = select(func.count()).select_from(AssertionRecord).where(
            AssertionRecord.id != record.id,
            AssertionRecord.workspace_id == record.workspace_id,
            AssertionRecord.subject_entity_id == record.subject_entity_id,
            AssertionRecord.property_uri == record.property_uri,
            AssertionRecord.status.in_(COUNTED_STATUSES),
        )
        return (await self.session.execute(stmt)).scalar_one()

    # --- Helpers ----------------------------------------------------------

    async def _save_report(
        self,
        record: AssertionRecord,
        release: OntologyRelease,
        policy: AssertionPolicy,
        findings: List[ValidationFinding],
        actor_id: str,
    ) -> AssertionValidationReport:
        """Store a report and pin the assertion to the release."""
        valid = not any(f.severity == "error" for f in findings)
        report = AssertionValidationRecord(
            assertion=record,
            ontology_release_id=release.release_id,
            ontology_version=release.version,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            valid=valid,
            findings=[f.model_dump() for f in findings],
            actor_id=actor_id,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(report)
        record.ontology_release_id = release.release_id
        record.updated_at = report.created_at
        await self.session.flush()
        return _report_from_record(report)

    @staticmethod
    def _summary(report: AssertionValidationReport) -> str:
        """Summarize a report for the transition log."""
        errors = [f.rule for f in report.findings if f.severity == "error"]
        if not errors:
            return f"Validated against ontology {report.ontology_version}"
        return f"Failed checks: {', '.join(errors)}"
