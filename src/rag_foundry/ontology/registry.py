"""Versioned ontology registry backed by PostgreSQL (ADR-0011).

A release moves through ``draft -> approved -> deprecated``. Terms can only
be added to, or deprecated in, a draft; an approved release never changes
again, and further edits go into a new draft derived from it.

Every edit revalidates the whole release before anything is stored, so a
draft is always internally consistent. Terms must therefore be added in
dependency order: parent classes before subclasses, classes before the
properties that use them, and an inverse property before the property that
names it.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rag_foundry.db.models import (
    OntologyClassRecord,
    OntologyPropertyRecord,
    OntologyReleaseRecord,
)
from rag_foundry.ontology.models import (
    OntologyClass,
    OntologyProperty,
    OntologyRelease,
)

OntologyTerm = Union[OntologyClass, OntologyProperty]


class OntologyRegistryError(Exception):
    """Base class for registry errors."""


class ReleaseNotFoundError(OntologyRegistryError):
    """Raised when a release id is unknown."""


class DuplicateReleaseError(OntologyRegistryError):
    """Raised when an ontology version already exists."""


class ReleaseStateError(OntologyRegistryError):
    """Raised when an operation is not allowed in the release's status."""


class InvalidReleaseError(OntologyRegistryError):
    """Raised when a change would leave the release inconsistent."""


class TermNotFoundError(OntologyRegistryError):
    """Raised when a release does not define the requested IRI."""


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Attach UTC to naive timestamps, which SQLite returns.

    Args:
        value: Timestamp read from the database.

    Returns:
        The timestamp with a timezone, or None.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _class_to_record(cls: OntologyClass) -> OntologyClassRecord:
    """Convert a class model to an ORM record."""
    return OntologyClassRecord(
        uri=cls.uri,
        preferred_labels=dict(cls.preferred_labels),
        parent_class_uris=list(cls.parent_class_uris),
        description=dict(cls.description),
        identity_rules=list(cls.identity_rules),
        status=cls.status,
    )


def _property_to_record(prop: OntologyProperty) -> OntologyPropertyRecord:
    """Convert a property model to an ORM record."""
    return OntologyPropertyRecord(
        uri=prop.uri,
        preferred_labels=dict(prop.preferred_labels),
        description=dict(prop.description),
        property_type=prop.property_type,
        domain_class_uris=list(prop.domain_class_uris),
        range_class_uris=list(prop.range_class_uris),
        datatype=prop.datatype,
        inverse_property_uri=prop.inverse_property_uri,
        temporal=prop.temporal,
        provenance_required=prop.provenance_required,
        constraints=[c.model_dump() for c in prop.constraints],
        status=prop.status,
    )


def _release_fields(record: OntologyReleaseRecord) -> Dict[str, Any]:
    """Collect the model fields of a release record, terms sorted by IRI."""
    return {
        "release_id": record.id,
        "ontology_uri": record.ontology_uri,
        "version": record.version,
        "title": record.title,
        "description": record.description,
        "status": record.status,
        "previous_release_id": record.previous_release_id,
        "created_at": _as_utc(record.created_at),
        "published_at": _as_utc(record.published_at),
        "classes": [
            {
                "uri": c.uri,
                "preferred_labels": c.preferred_labels,
                "parent_class_uris": c.parent_class_uris,
                "description": c.description,
                "identity_rules": c.identity_rules,
                "status": c.status,
            }
            for c in sorted(record.classes, key=lambda c: c.uri)
        ],
        "properties": [
            {
                "uri": p.uri,
                "preferred_labels": p.preferred_labels,
                "description": p.description,
                "property_type": p.property_type,
                "domain_class_uris": p.domain_class_uris,
                "range_class_uris": p.range_class_uris,
                "datatype": p.datatype,
                "inverse_property_uri": p.inverse_property_uri,
                "temporal": p.temporal,
                "provenance_required": p.provenance_required,
                "constraints": p.constraints,
                "status": p.status,
            }
            for p in sorted(record.properties, key=lambda p: p.uri)
        ],
    }


def _build_release(fields: Dict[str, Any]) -> OntologyRelease:
    """Validate release fields, converting failures to registry errors.

    Args:
        fields: Release fields as produced by ``_release_fields``.

    Returns:
        The validated release.

    Raises:
        InvalidReleaseError: If the release is inconsistent.
    """
    try:
        return OntologyRelease.model_validate(fields)
    except ValidationError as exc:
        raise InvalidReleaseError(str(exc)) from exc


class OntologyRegistry:
    """Creates, edits, publishes and looks up ontology releases.

    Methods flush but never commit; the caller owns the transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the registry with an AsyncSession.

        Args:
            session: SQLAlchemy AsyncSession.
        """
        self.session = session

    async def create_draft(
        self,
        ontology_uri: str,
        version: str,
        title: str,
        description: Optional[str] = None,
    ) -> OntologyRelease:
        """Create an empty draft release.

        Args:
            ontology_uri: IRI of the ontology.
            version: Version string, unique per ontology.
            title: Human-readable title.
            description: Optional release description.

        Returns:
            The new draft release.

        Raises:
            DuplicateReleaseError: If the version already exists.
            InvalidReleaseError: If a field is invalid.
        """
        release = _build_release(
            {
                "ontology_uri": ontology_uri,
                "version": version,
                "title": title,
                "description": description,
            }
        )
        await self._ensure_new_version(ontology_uri, version)
        await self._insert_draft(release)
        return release

    async def import_draft(self, release: OntologyRelease) -> OntologyRelease:
        """Store an externally built release, e.g. an import, as a draft.

        Args:
            release: A draft release whose terms are drafts or deprecated.

        Returns:
            The stored release.

        Raises:
            DuplicateReleaseError: If the version already exists.
            InvalidReleaseError: If the release or any term is approved.
        """
        if release.status != "draft":
            raise InvalidReleaseError(
                f"Only drafts can be imported, not {release.status} releases"
            )
        for term in [*release.classes, *release.properties]:
            if term.status == "approved":
                raise InvalidReleaseError(
                    f"Imported term {term.uri} cannot already be approved"
                )
        await self._ensure_new_version(release.ontology_uri, release.version)
        await self._insert_draft(release)
        return release

    async def get_release(self, release_id: uuid.UUID) -> OntologyRelease:
        """Load a release with all of its terms.

        Args:
            release_id: Release id.

        Returns:
            The release.

        Raises:
            ReleaseNotFoundError: If the release does not exist.
        """
        record = await self._load(release_id)
        return _build_release(_release_fields(record))

    async def list_releases(self, ontology_uri: str) -> List[OntologyRelease]:
        """List every release of an ontology, oldest first.

        Args:
            ontology_uri: IRI of the ontology.

        Returns:
            Releases ordered by creation time.
        """
        stmt = (
            self._select_releases()
            .where(OntologyReleaseRecord.ontology_uri == ontology_uri)
            .order_by(OntologyReleaseRecord.created_at)
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [_build_release(_release_fields(r)) for r in records]

    async def latest_approved(
        self, ontology_uri: str
    ) -> Optional[OntologyRelease]:
        """Find the most recently published approved release.

        Args:
            ontology_uri: IRI of the ontology.

        Returns:
            The release, or None if no release is approved.
        """
        stmt = (
            self._select_releases()
            .where(
                OntologyReleaseRecord.ontology_uri == ontology_uri,
                OntologyReleaseRecord.status == "approved",
            )
            .order_by(OntologyReleaseRecord.published_at.desc())
            .limit(1)
        )
        record = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if record is None else _build_release(
            _release_fields(record)
        )

    async def find_term(
        self, release_id: uuid.UUID, uri: str
    ) -> OntologyTerm:
        """Find a class or property in a release by IRI.

        Args:
            release_id: Release id.
            uri: Term IRI.

        Returns:
            The class or property.

        Raises:
            ReleaseNotFoundError: If the release does not exist.
            TermNotFoundError: If the release does not define the IRI.
        """
        release = await self.get_release(release_id)
        term = release.get_class(uri) or release.get_property(uri)
        if term is None:
            raise TermNotFoundError(f"{uri} is not defined in {release_id}")
        return term

    async def add_class(
        self, release_id: uuid.UUID, ontology_class: OntologyClass
    ) -> OntologyRelease:
        """Add a draft class to a draft release.

        Args:
            release_id: Release id.
            ontology_class: Class to add; its status must be ``draft``.

        Returns:
            The updated release.

        Raises:
            ReleaseNotFoundError: If the release does not exist.
            ReleaseStateError: If the release is not a draft.
            InvalidReleaseError: If the class is not a draft or would make
                the release inconsistent.
        """
        record = await self._load_draft(release_id)
        self._require_draft_term(ontology_class)
        fields = _release_fields(record)
        fields["classes"].append(ontology_class.model_dump())
        release = _build_release(fields)
        record.classes.append(_class_to_record(ontology_class))
        await self.session.flush()
        return release

    async def add_property(
        self, release_id: uuid.UUID, ontology_property: OntologyProperty
    ) -> OntologyRelease:
        """Add a draft property to a draft release.

        Args:
            release_id: Release id.
            ontology_property: Property to add; its status must be ``draft``.

        Returns:
            The updated release.

        Raises:
            ReleaseNotFoundError: If the release does not exist.
            ReleaseStateError: If the release is not a draft.
            InvalidReleaseError: If the property is not a draft or would
                make the release inconsistent.
        """
        record = await self._load_draft(release_id)
        self._require_draft_term(ontology_property)
        fields = _release_fields(record)
        fields["properties"].append(ontology_property.model_dump())
        release = _build_release(fields)
        record.properties.append(_property_to_record(ontology_property))
        await self.session.flush()
        return release

    async def deprecate_term(
        self, release_id: uuid.UUID, uri: str
    ) -> OntologyRelease:
        """Mark a class or property of a draft release as deprecated.

        Args:
            release_id: Release id.
            uri: Term IRI.

        Returns:
            The updated release.

        Raises:
            ReleaseNotFoundError: If the release does not exist.
            ReleaseStateError: If the release is not a draft.
            TermNotFoundError: If the release does not define the IRI.
        """
        record = await self._load_draft(release_id)
        terms = [*record.classes, *record.properties]
        term = next((t for t in terms if t.uri == uri), None)
        if term is None:
            raise TermNotFoundError(f"{uri} is not defined in {release_id}")
        term.status = "deprecated"
        await self.session.flush()
        return _build_release(_release_fields(record))

    async def publish(self, release_id: uuid.UUID) -> OntologyRelease:
        """Approve a draft release, making it immutable.

        Draft terms become approved; deprecated terms stay deprecated.

        Args:
            release_id: Release id.

        Returns:
            The approved release.

        Raises:
            ReleaseNotFoundError: If the release does not exist.
            ReleaseStateError: If the release is not a draft.
            InvalidReleaseError: If the release has no classes or is
                inconsistent.
        """
        record = await self._load_draft(release_id)
        _build_release(_release_fields(record))
        if not record.classes:
            raise InvalidReleaseError(
                "Cannot publish a release with no classes"
            )
        for term in [*record.classes, *record.properties]:
            if term.status == "draft":
                term.status = "approved"
        record.status = "approved"
        record.published_at = datetime.now(timezone.utc)
        await self.session.flush()
        return _build_release(_release_fields(record))

    async def deprecate_release(
        self, release_id: uuid.UUID
    ) -> OntologyRelease:
        """Deprecate an approved release.

        Args:
            release_id: Release id.

        Returns:
            The deprecated release.

        Raises:
            ReleaseNotFoundError: If the release does not exist.
            ReleaseStateError: If the release is not approved.
        """
        record = await self._load(release_id)
        if record.status != "approved":
            raise ReleaseStateError(
                f"Only approved releases can be deprecated; {release_id} "
                f"is {record.status}"
            )
        record.status = "deprecated"
        await self.session.flush()
        return _build_release(_release_fields(record))

    async def create_draft_from(
        self,
        release_id: uuid.UUID,
        version: str,
        title: Optional[str] = None,
    ) -> OntologyRelease:
        """Start a new draft that copies a published release's terms.

        Args:
            release_id: Id of the approved or deprecated source release.
            version: Version of the new draft.
            title: Title of the new draft; defaults to the source title.

        Returns:
            The new draft, linked to its source via ``previous_release_id``.

        Raises:
            ReleaseNotFoundError: If the source release does not exist.
            ReleaseStateError: If the source is still a draft.
            DuplicateReleaseError: If the version already exists.
        """
        source = await self._load(release_id)
        if source.status == "draft":
            raise ReleaseStateError(
                f"{release_id} is still a draft; edit it directly"
            )
        await self._ensure_new_version(source.ontology_uri, version)
        fields = _release_fields(source)
        new_id = uuid.uuid4()
        created_at = datetime.now(timezone.utc)
        fields.update(
            release_id=new_id,
            version=version,
            title=title or source.title,
            status="draft",
            previous_release_id=source.id,
            created_at=created_at,
            published_at=None,
        )
        release = _build_release(fields)
        await self._insert_draft(release)
        return release

    async def _insert_draft(self, release: OntologyRelease) -> None:
        """Insert a validated release and its terms as a draft record."""
        self.session.add(
            OntologyReleaseRecord(
                id=release.release_id,
                ontology_uri=release.ontology_uri,
                version=release.version,
                title=release.title,
                description=release.description,
                status="draft",
                previous_release_id=release.previous_release_id,
                created_at=release.created_at,
                classes=[_class_to_record(c) for c in release.classes],
                properties=[
                    _property_to_record(p) for p in release.properties
                ],
            )
        )
        await self.session.flush()

    @staticmethod
    def _select_releases():
        """Build a release query that eagerly loads terms."""
        return select(OntologyReleaseRecord).options(
            selectinload(OntologyReleaseRecord.classes),
            selectinload(OntologyReleaseRecord.properties),
        )

    async def _load(self, release_id: uuid.UUID) -> OntologyReleaseRecord:
        """Load a release record with its terms.

        Raises:
            ReleaseNotFoundError: If the release does not exist.
        """
        stmt = self._select_releases().where(
            OntologyReleaseRecord.id == release_id
        )
        record = (await self.session.execute(stmt)).scalar_one_or_none()
        if record is None:
            raise ReleaseNotFoundError(f"Release {release_id} not found")
        return record

    async def _load_draft(
        self, release_id: uuid.UUID
    ) -> OntologyReleaseRecord:
        """Load a release record that must still be a draft.

        Raises:
            ReleaseNotFoundError: If the release does not exist.
            ReleaseStateError: If the release is not a draft.
        """
        record = await self._load(release_id)
        if record.status != "draft":
            raise ReleaseStateError(
                f"Release {release_id} is {record.status} and immutable"
            )
        return record

    async def _ensure_new_version(
        self, ontology_uri: str, version: str
    ) -> None:
        """Check that an ontology version does not exist yet.

        Raises:
            DuplicateReleaseError: If the version already exists.
        """
        stmt = select(OntologyReleaseRecord.id).where(
            OntologyReleaseRecord.ontology_uri == ontology_uri,
            OntologyReleaseRecord.version == version,
        )
        if (await self.session.execute(stmt)).first() is not None:
            raise DuplicateReleaseError(
                f"{ontology_uri} version {version} already exists"
            )

    @staticmethod
    def _require_draft_term(term: OntologyTerm) -> None:
        """Reject terms that claim a status other than draft.

        Raises:
            InvalidReleaseError: If the term is not a draft.
        """
        if term.status != "draft":
            raise InvalidReleaseError(
                f"New term {term.uri} must be a draft, not {term.status}"
            )
