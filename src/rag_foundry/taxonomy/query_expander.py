"""Taxonomy-driven query expansion service for hybrid retrieval (ADR-0016)."""

import time
from typing import List

from pydantic import BaseModel, Field

from rag_foundry.taxonomy.models import SKOSConceptSchemeModel


class ExpandedQueryTerm(BaseModel):
    """Term container with decay weight and expansion relationship."""

    term: str = Field(description="Expanded search term")
    weight: float = Field(description="Relevance weight (0.0 - 1.0)")
    relationship: str = Field(
        description="Relationship (original, prefLabel, altLabel, broader)"
    )


class ExpandedQueryResult(BaseModel):
    """Result container for taxonomy query expansion."""

    original_query: str = Field(description="Original search query string")
    expanded_terms: List[ExpandedQueryTerm] = Field(
        default_factory=list, description="List of expanded weighted terms"
    )
    expanded_lexical_query: str = Field(
        description="Formatted OR-separated lexical query"
    )
    execution_time_ms: float = Field(
        description="Query expansion execution duration in milliseconds"
    )


class TaxonomyQueryExpander:
    """Expands search queries using SKOS taxonomy concepts (ADR-0016)."""

    def __init__(self, scheme: SKOSConceptSchemeModel) -> None:
        """Initialize TaxonomyQueryExpander.

        Args:
            scheme: SKOSConceptSchemeModel object.
        """
        self.scheme = scheme
        self._concept_by_uri = {c.uri: c for c in scheme.concepts}

    def expand_query(
        self,
        query: str,
        broader_decay: float = 0.7,
        narrower_decay: float = 0.5,
    ) -> ExpandedQueryResult:
        """Expand query with concept synonyms, broader, and narrower terms.

        Args:
            query: Input search query string.
            broader_decay: Decay weight multiplier for broader concepts.
            narrower_decay: Decay weight multiplier for narrower concepts.

        Returns:
            ExpandedQueryResult container.
        """
        start_time = time.time()
        q_lower = query.lower()

        expanded_terms: List[ExpandedQueryTerm] = [
            ExpandedQueryTerm(
                term=query, weight=1.0, relationship="original"
            )
        ]
        seen_terms = {query.lower()}

        for concept in self.scheme.concepts:
            all_labels = [concept.pref_label] + concept.alt_labels
            if any(lbl.lower() in q_lower for lbl in all_labels):
                # Add prefLabel if not already seen
                if concept.pref_label.lower() not in seen_terms:
                    expanded_terms.append(
                        ExpandedQueryTerm(
                            term=concept.pref_label,
                            weight=0.9,
                            relationship="prefLabel",
                        )
                    )
                    seen_terms.add(concept.pref_label.lower())

                # Add altLabels
                for alt in concept.alt_labels:
                    if alt.lower() not in seen_terms:
                        expanded_terms.append(
                            ExpandedQueryTerm(
                                term=alt,
                                weight=0.85,
                                relationship="altLabel",
                            )
                        )
                        seen_terms.add(alt.lower())

                # Add broader concepts
                for b_uri in concept.broader_uris:
                    b_concept = self._concept_by_uri.get(b_uri)
                    if b_concept and (
                        b_concept.pref_label.lower() not in seen_terms
                    ):
                        expanded_terms.append(
                            ExpandedQueryTerm(
                                term=b_concept.pref_label,
                                weight=broader_decay,
                                relationship="broader",
                            )
                        )
                        seen_terms.add(b_concept.pref_label.lower())

                # Add narrower concepts
                for n_concept in self.scheme.concepts:
                    if (
                        concept.uri in n_concept.broader_uris
                        and n_concept.pref_label.lower() not in seen_terms
                    ):
                        expanded_terms.append(
                            ExpandedQueryTerm(
                                term=n_concept.pref_label,
                                weight=narrower_decay,
                                relationship="narrower",
                            )
                        )
                        seen_terms.add(n_concept.pref_label.lower())

        duration_ms = round((time.time() - start_time) * 1000.0, 3)
        lexical_query = " OR ".join([f'"{t.term}"' for t in expanded_terms])

        return ExpandedQueryResult(
            original_query=query,
            expanded_terms=expanded_terms,
            expanded_lexical_query=lexical_query,
            execution_time_ms=duration_ms,
        )
