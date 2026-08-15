"""Taxonomy-driven query expansion bridge for retrieval pipelines (ADR-0016)."""

from typing import Any, Dict, Optional, Tuple

from rag_foundry.retrieval.models import RetrievalQuery
from rag_foundry.taxonomy.models import SKOSConceptSchemeModel
from rag_foundry.taxonomy.query_expander import TaxonomyQueryExpander


class TaxonomyExpansionBridge:
    """Connects SKOS taxonomy concept schemes to retrieval query pipelines."""

    def __init__(self, scheme: Optional[SKOSConceptSchemeModel] = None) -> None:
        """Initialize TaxonomyExpansionBridge.

        Args:
            scheme: Optional SKOSConceptSchemeModel containing domain taxonomy concepts.
        """
        self.scheme = scheme
        self.expander = TaxonomyQueryExpander(scheme) if scheme else None

    def expand_retrieval_query(
        self, query: RetrievalQuery
    ) -> Tuple[RetrievalQuery, Dict[str, Any]]:
        """Expand a retrieval query with taxonomy concept synonyms and hierarchy.

        Args:
            query: RetrievalQuery input specification.

        Returns:
            Tuple of (Expanded RetrievalQuery, Diagnostic Trace Dictionary).
        """
        if not query.enable_expansion or not self.expander:
            return query, {
                "expansion_applied": False,
                "reason": "disabled" if not query.enable_expansion else "no_scheme",
            }

        result = self.expander.expand_query(query.query_text)

        # Check if terms were expanded beyond original query
        if len(result.expanded_terms) > 1:
            expanded_query = query.model_copy(
                update={"query_text": result.expanded_lexical_query}
            )
            trace = {
                "expansion_applied": True,
                "original_query": query.query_text,
                "expanded_query": result.expanded_lexical_query,
                "expanded_term_count": len(result.expanded_terms),
                "expanded_terms": [
                    {
                        "term": t.term,
                        "weight": t.weight,
                        "relationship": t.relationship,
                    }
                    for t in result.expanded_terms
                ],
                "duration_ms": result.execution_time_ms,
            }
            return expanded_query, trace

        return query, {
            "expansion_applied": False,
            "expanded_term_count": 1,
            "duration_ms": result.execution_time_ms,
        }
