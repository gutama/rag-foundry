"""TaxonomyBrowserService for navigating SKOS concept trees."""

from typing import List, Optional

from rag_foundry.taxonomy.models import (
    SKOSConceptModel,
    SKOSConceptSchemeModel,
)


class TaxonomyBrowserService:
    """Service for navigating SKOS concept trees and searching concepts."""

    def __init__(self, scheme: SKOSConceptSchemeModel) -> None:
        """Initialize TaxonomyBrowserService.

        Args:
            scheme: SKOSConceptSchemeModel object.
        """
        self.scheme = scheme
        self._concept_map = {c.uri: c for c in scheme.concepts}

    def get_concept_by_uri(self, uri: str) -> Optional[SKOSConceptModel]:
        """Lookup a concept by its URI."""
        return self._concept_map.get(uri)

    def get_root_concepts(self) -> List[SKOSConceptModel]:
        """Retrieve all root concepts (concepts without broader parent URIs)."""
        return [c for c in self.scheme.concepts if not c.broader_uris]

    def get_narrower_concepts(
        self, concept_uri: str
    ) -> List[SKOSConceptModel]:
        """Retrieve direct narrower child concepts for a parent concept URI.

        Args:
            concept_uri: Parent concept URI.

        Returns:
            List of child SKOSConceptModel objects.
        """
        return [
            c for c in self.scheme.concepts if concept_uri in c.broader_uris
        ]

    def search_concepts(self, query: str) -> List[SKOSConceptModel]:
        """Search concepts matching query string against concept labels.

        Args:
            query: Search query text.

        Returns:
            List of matching SKOSConceptModel objects.
        """
        q_lower = query.strip().lower()
        if not q_lower:
            return []

        matched: List[SKOSConceptModel] = []
        for c in self.scheme.concepts:
            all_labels = [c.pref_label] + c.alt_labels + c.hidden_labels
            if any(q_lower in label.lower() for label in all_labels):
                matched.append(c)

        return matched
