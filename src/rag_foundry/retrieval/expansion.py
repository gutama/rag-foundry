"""Taxonomy, ontology, and entity query expansion services (ADR-0016)."""

import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from rag_foundry.retrieval.models import RetrievalQuery
from rag_foundry.retrieval.ontology_expansion import (
    EntityQueryExpander,
    ExpansionPolicy,
    OntologyQueryExpander,
    SemanticExpansionTerm,
    SemanticExpansionTrace,
    finalize_expansion_terms,
    format_expanded_lexical_query,
    label_matches_query,
)
from rag_foundry.retrieval.security import (
    SecurityAuthorizationError,
    SecurityContext,
)
from rag_foundry.taxonomy.models import SKOSConceptSchemeModel
from rag_foundry.taxonomy.query_expander import TaxonomyQueryExpander


class TaxonomyExpansionBridge:
    """Connects SKOS taxonomy concept schemes to retrieval query pipelines."""

    def __init__(self, scheme: Optional[SKOSConceptSchemeModel] = None) -> None:
        """Initialize TaxonomyExpansionBridge.

        Args:
            scheme: Optional SKOSConceptSchemeModel containing domain taxonomy
                concepts.
        """
        self.scheme = scheme
        self.expander = TaxonomyQueryExpander(scheme) if scheme else None

    def expand_retrieval_query(
        self, query: RetrievalQuery
    ) -> Tuple[RetrievalQuery, Dict[str, Any]]:
        """Expand a retrieval query with taxonomy synonyms and hierarchy.

        Args:
            query: RetrievalQuery input specification.

        Returns:
            Tuple of (Expanded RetrievalQuery, Diagnostic Trace Dictionary).
        """
        if not query.enable_expansion or not self.expander:
            return query, {
                "expansion_applied": False,
                "reason": (
                    "disabled" if not query.enable_expansion else "no_scheme"
                ),
            }

        result = self.expander.expand_query(query.query_text)

        if len(result.expanded_terms) > 1:
            term_weights = {
                t.term.lower(): t.weight
                for t in result.expanded_terms
                if t.relationship != "original"
            }
            expanded_query = query.model_copy(
                update={
                    "query_text": result.expanded_lexical_query,
                    "original_query_text": query.query_text,
                    "expanded_term_weights": term_weights,
                }
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


class SemanticQueryExpansionService:
    """Unified governed expansion composing SKOS, ontology, and entity stores.

    Authorizes caller ``SecurityContext`` before consulting any semantic store,
    enforces shared ``ExpansionPolicy`` depth/budget bounds, preserves the
    original query for exact-term lexical protection, and emits complete
    semantic provenance traces.
    """

    def __init__(
        self,
        taxonomy_scheme: Optional[SKOSConceptSchemeModel] = None,
        ontology_expander: Optional[OntologyQueryExpander] = None,
        entity_expander: Optional[EntityQueryExpander] = None,
        policy: Optional[ExpansionPolicy] = None,
        semantic_profile_id: Optional[uuid.UUID] = None,
        release_ids: Optional[List[uuid.UUID]] = None,
    ) -> None:
        """Initialize SemanticQueryExpansionService.

        Args:
            taxonomy_scheme: Optional SKOSConceptSchemeModel for SKOS terms.
            ontology_expander: Optional approved-ontology expander.
            entity_expander: Optional workspace-scoped entity expander.
            policy: Shared ExpansionPolicy bounding depth, relations, budget.
            semantic_profile_id: Optional semantic profile UUID for entities.
            release_ids: Optional approved ontology release UUID whitelist.
        """
        self.taxonomy_scheme = taxonomy_scheme
        self.ontology_expander = ontology_expander
        self.entity_expander = entity_expander
        self.policy = policy or ExpansionPolicy()
        self.semantic_profile_id = semantic_profile_id
        self.release_ids = (
            list(release_ids) if release_ids is not None else None
        )

    @staticmethod
    def _authorize_caller(
        workspace_id: uuid.UUID,
        security_context: Optional[SecurityContext],
    ) -> Optional[str]:
        """Authorize caller before touching any semantic vocabulary store.

        Args:
            workspace_id: Target query workspace UUID.
            security_context: Optional caller SecurityContext.

        Returns:
            None when allowed, or a fail-closed reason string when the caller
            has zero allowed security domains.

        Raises:
            SecurityAuthorizationError: If workspace access is denied.
        """
        if security_context is None:
            return None
        if not security_context.can_access_workspace(workspace_id):
            raise SecurityAuthorizationError(
                f"Unauthorized workspace access: user "
                f"'{security_context.user_id}' is not authorized for "
                f"workspace '{workspace_id}'."
            )
        if not security_context.allowed_security_domains:
            return "no_allowed_security_domains"
        return None

    def _collect_skos_candidates(
        self,
        query_text: str,
        policy: ExpansionPolicy,
    ) -> List[SemanticExpansionTerm]:
        """Collect SKOS taxonomy candidates with concept URI provenance."""
        if self.taxonomy_scheme is None:
            return []
        query_lower = query_text.strip().lower()
        if not query_lower:
            return []

        enabled = set(policy.enabled_relations)
        concept_by_uri = {c.uri: c for c in self.taxonomy_scheme.concepts}
        children_by_uri: Dict[str, List[str]] = {}
        for concept in sorted(
            self.taxonomy_scheme.concepts, key=lambda c: c.uri
        ):
            for broader_uri in sorted(concept.broader_uris):
                children_by_uri.setdefault(broader_uri, []).append(concept.uri)

        candidates: List[SemanticExpansionTerm] = []
        for concept in sorted(
            self.taxonomy_scheme.concepts, key=lambda c: c.uri
        ):
            all_labels = [concept.pref_label] + list(concept.alt_labels)
            matched = [
                lbl
                for lbl in all_labels
                if label_matches_query(lbl, query_lower)
            ]
            if not matched:
                continue
            matched_lower = {lbl.lower() for lbl in matched}

            if (
                "skos_prefLabel" in enabled
                and concept.pref_label.lower() not in matched_lower
            ):
                candidates.append(
                    SemanticExpansionTerm(
                        term=concept.pref_label,
                        weight=policy.weight_for(
                            "skos_prefLabel", hop_depth=0
                        ),
                        relationship="skos_prefLabel",
                        source_type="skos_concept",
                        source_uri=concept.uri,
                        hop_depth=0,
                    )
                )

            if "skos_altLabel" in enabled:
                for alt in concept.alt_labels:
                    if alt.lower() not in matched_lower:
                        candidates.append(
                            SemanticExpansionTerm(
                                term=alt,
                                weight=policy.weight_for(
                                    "skos_altLabel", hop_depth=0
                                ),
                                relationship="skos_altLabel",
                                source_type="skos_concept",
                                source_uri=concept.uri,
                                hop_depth=0,
                            )
                        )

            if policy.max_depth >= 1 and "skos_broader" in enabled:
                for b_uri in sorted(concept.broader_uris):
                    b_concept = concept_by_uri.get(b_uri)
                    if b_concept is not None:
                        candidates.append(
                            SemanticExpansionTerm(
                                term=b_concept.pref_label,
                                weight=policy.weight_for(
                                    "skos_broader", hop_depth=1
                                ),
                                relationship="skos_broader",
                                source_type="skos_concept",
                                source_uri=b_concept.uri,
                                hop_depth=1,
                            )
                        )

            if policy.max_depth >= 1 and "skos_narrower" in enabled:
                for n_uri in sorted(children_by_uri.get(concept.uri, [])):
                    n_concept = concept_by_uri.get(n_uri)
                    if n_concept is not None:
                        candidates.append(
                            SemanticExpansionTerm(
                                term=n_concept.pref_label,
                                weight=policy.weight_for(
                                    "skos_narrower", hop_depth=1
                                ),
                                relationship="skos_narrower",
                                source_type="skos_concept",
                                source_uri=n_concept.uri,
                                hop_depth=1,
                            )
                        )

        return candidates

    async def expand_retrieval_query(
        self,
        query: RetrievalQuery,
        security_context: Optional[SecurityContext] = None,
        *,
        policy: Optional[ExpansionPolicy] = None,
        semantic_profile_id: Optional[uuid.UUID] = None,
        release_ids: Optional[List[uuid.UUID]] = None,
    ) -> Tuple[RetrievalQuery, Dict[str, Any]]:
        """Expand a retrieval query across SKOS, ontology, and entity stores.

        Args:
            query: Input RetrievalQuery specification.
            security_context: Optional caller SecurityContext checked before
                consulting any semantic store.
            policy: Optional per-call ExpansionPolicy override.
            semantic_profile_id: Optional semantic profile UUID override.
            release_ids: Optional approved ontology release UUID override.

        Returns:
            Tuple of (Expanded RetrievalQuery, Provenance Metrics Dictionary).

        Raises:
            SecurityAuthorizationError: If caller is unauthorized for the
                query workspace.
        """
        start = time.perf_counter()
        active_policy = policy or self.policy

        if not query.enable_expansion:
            return query, self._skipped_trace(
                query.query_text, start, reason="disabled"
            )

        deny_reason = self._authorize_caller(
            query.filter.workspace_id, security_context
        )
        if deny_reason is not None:
            return query, self._skipped_trace(
                query.query_text, start, reason=deny_reason
            )

        sources_consulted: List[str] = []
        candidates: List[SemanticExpansionTerm] = []

        if self.taxonomy_scheme is not None:
            sources_consulted.append("skos")
            candidates.extend(
                self._collect_skos_candidates(query.query_text, active_policy)
            )

        effective_releases = (
            release_ids if release_ids is not None else self.release_ids
        )
        if self.ontology_expander is not None:
            sources_consulted.append("ontology")
            onto_terms, _ = (
                await self.ontology_expander.collect_ontology_candidates(
                    query_text=query.query_text,
                    policy=active_policy,
                    release_ids=effective_releases,
                )
            )
            candidates.extend(onto_terms)

        effective_profile = (
            semantic_profile_id
            if semantic_profile_id is not None
            else self.semantic_profile_id
        )
        if self.entity_expander is not None:
            sources_consulted.append("entity")
            ent_terms, _ = await self.entity_expander.collect_entity_candidates(
                query_text=query.query_text,
                workspace_id=query.filter.workspace_id,
                semantic_profile_id=effective_profile,
                security_context=security_context,
                policy=active_policy,
            )
            candidates.extend(ent_terms)

        if not sources_consulted:
            return query, self._skipped_trace(
                query.query_text, start, reason="no_semantic_sources"
            )

        terms = finalize_expansion_terms(
            query.query_text, candidates, active_policy
        )
        expanded_lexical = format_expanded_lexical_query(
            query.query_text, terms
        )
        duration_ms = round((time.perf_counter() - start) * 1000.0, 3)

        surviving_releases = sorted(
            {str(t.release_id) for t in terms if t.release_id is not None}
        )
        trace = SemanticExpansionTrace(
            expansion_applied=len(terms) > 1,
            original_query=query.query_text,
            expanded_query=expanded_lexical,
            expanded_term_count=len(terms),
            terms=terms,
            sources_consulted=sources_consulted,
            release_ids=surviving_releases,
            duration_ms=duration_ms,
        )

        if len(terms) > 1:
            term_weights = {
                t.term.lower(): t.weight
                for t in terms
                if t.relationship != "original"
            }
            expanded_query = query.model_copy(
                update={
                    "query_text": expanded_lexical,
                    "original_query_text": query.query_text,
                    "expanded_term_weights": term_weights,
                }
            )
            return expanded_query, trace.to_metrics_dict()

        return query, trace.to_metrics_dict()

    @staticmethod
    def _skipped_trace(
        query_text: str,
        start_perf: float,
        *,
        reason: str,
    ) -> Dict[str, Any]:
        """Build a provenance trace when expansion is skipped or denied."""
        duration_ms = round((time.perf_counter() - start_perf) * 1000.0, 3)
        trace = SemanticExpansionTrace(
            expansion_applied=False,
            original_query=query_text,
            expanded_query=query_text,
            expanded_term_count=1,
            terms=[
                SemanticExpansionTerm(
                    term=query_text.strip() or query_text,
                    weight=1.0,
                    relationship="original",
                    source_type="original",
                    hop_depth=0,
                )
            ],
            sources_consulted=[],
            release_ids=[],
            duration_ms=duration_ms,
            reason=reason,
        )
        return trace.to_metrics_dict()
