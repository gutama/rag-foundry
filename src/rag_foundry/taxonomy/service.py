"""SKOS Taxonomy Service & Entity Resolution Baseline for RAG Foundry."""

import uuid
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_foundry.db.models import TaxonomyConcept


class TaxonomyService:
    """Service for managing SKOS concept schemes and candidate entity resolution."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize TaxonomyService with an AsyncSession.

        Args:
            session: SQLAlchemy AsyncSession.
        """
        self.session = session

    async def create_concept(
        self,
        scheme_id: uuid.UUID,
        uri: str,
        pref_labels: Dict[str, str],
        alt_labels: Optional[Dict[str, List[str]]] = None,
        broader_uris: Optional[List[str]] = None,
        related_uris: Optional[List[str]] = None,
        status: str = "approved",
        version: str = "1.0",
    ) -> TaxonomyConcept:
        """Create and persist a new SKOS TaxonomyConcept.

        Args:
            scheme_id: UUID of concept scheme.
            uri: Unique URI identifier.
            pref_labels: Multilingual preferred labels (lang -> label).
            alt_labels: Multilingual alternative labels (lang -> list of labels).
            broader_uris: URIs of broader concepts.
            related_uris: URIs of related concepts.
            status: Governance status (draft, approved, deprecated).
            version: Version string.

        Returns:
            Persisted TaxonomyConcept instance.
        """
        concept = TaxonomyConcept(
            id=uuid.uuid4(),
            scheme_id=scheme_id,
            uri=uri,
            pref_labels=pref_labels,
            alt_labels=alt_labels or {},
            broader_uris=broader_uris or [],
            related_uris=related_uris or [],
            status=status,
            version=version,
        )
        self.session.add(concept)
        await self.session.flush()
        return concept

    async def get_concept_by_uri(self, uri: str) -> Optional[TaxonomyConcept]:
        """Retrieve a TaxonomyConcept by its unique URI.

        Args:
            uri: Concept URI.

        Returns:
            TaxonomyConcept if found, otherwise None.
        """
        stmt = select(TaxonomyConcept).where(TaxonomyConcept.uri == uri)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_broader_concepts(self, uri: str) -> List[TaxonomyConcept]:
        """Get broader concepts for a given concept URI.

        Args:
            uri: Concept URI.

        Returns:
            List of broader TaxonomyConcept objects.
        """
        concept = await self.get_concept_by_uri(uri)
        if not concept or not concept.broader_uris:
            return []

        stmt = select(TaxonomyConcept).where(
            TaxonomyConcept.uri.in_(concept.broader_uris)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_narrower_concepts(self, uri: str) -> List[TaxonomyConcept]:
        """Get narrower concepts (concepts that list target uri as broader).

        Args:
            uri: Concept URI.

        Returns:
            List of narrower TaxonomyConcept objects.
        """
        stmt = select(TaxonomyConcept)
        result = await self.session.execute(stmt)
        all_concepts = result.scalars().all()

        narrower = [
            concept
            for concept in all_concepts
            if concept.broader_uris and uri in concept.broader_uris
        ]
        return narrower

    async def resolve_candidate_entities(
        self, mention: str, scheme_id: Optional[uuid.UUID] = None
    ) -> List[TaxonomyConcept]:
        """Resolve surface text mention against preferred and alternative labels.

        Args:
            mention: Surface text mention to match.
            scheme_id: Optional scheme UUID filter.

        Returns:
            List of matching TaxonomyConcept candidates.
        """
        stmt = select(TaxonomyConcept)
        if scheme_id:
            stmt = stmt.where(TaxonomyConcept.scheme_id == scheme_id)

        result = await self.session.execute(stmt)
        all_concepts = result.scalars().all()

        mention_lower = mention.strip().lower()
        matches: List[TaxonomyConcept] = []

        for concept in all_concepts:
            # Check pref_labels values
            pref_values = [v.lower() for v in concept.pref_labels.values()]
            if mention_lower in pref_values:
                matches.append(concept)
                continue

            # Check alt_labels values
            alt_match = False
            for alt_list in concept.alt_labels.values():
                if any(alt.lower() == mention_lower for alt in alt_list):
                    alt_match = True
                    break
            if alt_match:
                matches.append(concept)

        return matches
