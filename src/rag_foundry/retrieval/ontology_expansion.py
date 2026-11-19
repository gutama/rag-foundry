"""Governed ontology and entity query expansion with provenance (ADR-0016)."""

import re
import time
import uuid
from collections import deque
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from rag_foundry.db.models import (
    OntologyClassRecord,
    OntologyPropertyRecord,
    OntologyReleaseRecord,
)
from rag_foundry.retrieval.postgres_filters import (
    SessionOrFactory,
    acquire_session,
)

DEFAULT_ENABLED_RELATIONS: Tuple[str, ...] = (
    "preferred_label",
    "entity_alias",
    "entity_redirect",
    "ontology_parent",
    "ontology_child",
    "ontology_property",
    "ontology_inverse",
)

DEFAULT_RELATION_WEIGHTS: Dict[str, float] = {
    "original": 1.0,
    "preferred_label": 0.9,
    "entity_alias": 0.85,
    "entity_redirect": 0.85,
    "ontology_parent": 0.7,
    "ontology_child": 0.65,
    "ontology_property": 0.75,
    "ontology_inverse": 0.7,
    "skos_prefLabel": 0.9,
    "skos_altLabel": 0.85,
    "skos_broader": 0.7,
    "skos_narrower": 0.55,
}


class ExpansionPolicy(BaseModel):
    """Bounded, deterministic configuration for semantic query expansion."""

    enabled_relations: List[str] = Field(
        default_factory=lambda: list(DEFAULT_ENABLED_RELATIONS),
        description="Semantic relationship kinds permitted during expansion.",
    )
    max_depth: int = Field(
        default=1,
        ge=0,
        le=5,
        description="Maximum traversal hops across class hierarchies.",
    )
    max_expanded_terms: int = Field(
        default=12,
        ge=0,
        le=100,
        description="Maximum additional terms appended beyond original query.",
    )
    relation_weights: Dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_RELATION_WEIGHTS),
        description="Base relevance decay weights per relationship kind.",
    )
    depth_decay: float = Field(
        default=0.8,
        gt=0.0,
        le=1.0,
        description="Multiplicative decay factor applied per hierarchy hop.",
    )
    languages: Optional[List[str]] = Field(
        default=None,
        description="Optional language tag whitelist (None = all languages).",
    )

    @field_validator("relation_weights")
    @classmethod
    def validate_relation_weights(
        cls, value: Dict[str, float]
    ) -> Dict[str, float]:
        """Ensure every configured relation weight lies within (0.0, 1.0]."""
        for rel, weight in value.items():
            if weight <= 0.0 or weight > 1.0:
                raise ValueError(
                    f"Weight for relation '{rel}' must be in (0.0, 1.0]."
                )
        return value

    def weight_for(self, relationship: str, hop_depth: int = 1) -> float:
        """Compute decayed weight for a relationship at a given hop depth.

        Args:
            relationship: Relationship type key.
            hop_depth: Zero- or one-based traversal depth.

        Returns:
            Rounded weight in (0.0, 1.0].
        """
        base = self.relation_weights.get(
            relationship,
            DEFAULT_RELATION_WEIGHTS.get(relationship, 0.5),
        )
        exponent = max(0, hop_depth - 1)
        decayed = base * (self.depth_decay ** exponent)
        return round(min(1.0, max(0.01, decayed)), 4)


class SemanticExpansionTerm(BaseModel):
    """Single original or expanded query term with full semantic provenance."""

    term: str = Field(min_length=1, description="Surface query term.")
    weight: float = Field(gt=0.0, le=1.0, description="Expansion weight.")
    relationship: str = Field(description="Expansion relationship kind.")
    source_type: str = Field(
        description=(
            "Semantic source category (original, ontology_class, "
            "ontology_property, entity, skos_concept)."
        )
    )
    source_uri: Optional[str] = Field(
        default=None, description="Canonical URI of the semantic source."
    )
    release_id: Optional[uuid.UUID] = Field(
        default=None, description="Approved ontology release UUID if any."
    )
    entity_id: Optional[uuid.UUID] = Field(
        default=None, description="Active entity UUID if expanded from entity."
    )
    hop_depth: int = Field(
        default=0, ge=0, description="Graph traversal hop depth."
    )


class SemanticExpansionTrace(BaseModel):
    """Structured provenance record emitted into RetrievalResult metrics."""

    expansion_applied: bool = Field(
        default=False, description="True if one or more terms were added."
    )
    original_query: str = Field(description="Unmodified original query text.")
    expanded_query: str = Field(description="Formatted lexical query string.")
    expanded_term_count: int = Field(
        default=1, ge=1, description="Total terms including original query."
    )
    terms: List[SemanticExpansionTerm] = Field(
        default_factory=list, description="Ordered original + expanded terms."
    )
    sources_consulted: List[str] = Field(
        default_factory=list, description="Semantic stores consulted."
    )
    release_ids: List[str] = Field(
        default_factory=list, description="Approved ontology release IDs used."
    )
    duration_ms: float = Field(
        default=0.0, description="Expansion latency in milliseconds."
    )
    reason: Optional[str] = Field(
        default=None, description="Diagnostic note when expansion is skipped."
    )

    def to_metrics_dict(self) -> Dict[str, Any]:
        """Serialize trace to RetrievalResult.execution_metrics format.

        Returns:
            JSON-serializable dictionary backward-compatible with
            TaxonomyExpansionBridge traces and enriched with source URIs.
        """
        payload: Dict[str, Any] = {
            "expansion_applied": self.expansion_applied,
            "original_query": self.original_query,
            "expanded_query": self.expanded_query,
            "expanded_term_count": self.expanded_term_count,
            "expanded_terms": [
                {
                    "term": item.term,
                    "weight": item.weight,
                    "relationship": item.relationship,
                    "source_type": item.source_type,
                    "source_uri": item.source_uri,
                    "release_id": (
                        str(item.release_id)
                        if item.release_id is not None
                        else None
                    ),
                    "entity_id": (
                        str(item.entity_id)
                        if item.entity_id is not None
                        else None
                    ),
                    "hop_depth": item.hop_depth,
                }
                for item in self.terms
            ],
            "sources_consulted": list(self.sources_consulted),
            "release_ids": list(self.release_ids),
            "duration_ms": self.duration_ms,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


def label_matches_query(label: str, query_lower: str) -> bool:
    """Return True if a semantic label matches as a whole word/phrase.

    Args:
        label: Candidate semantic label.
        query_lower: Lowercased query string.

    Returns:
        True when ``label`` occurs on token boundaries in ``query_lower``.
    """
    cleaned = label.strip().lower()
    if not cleaned:
        return False
    pattern = rf"(?<!\w){re.escape(cleaned)}(?!\w)"
    return re.search(pattern, query_lower) is not None


def select_labels(
    label_map: Dict[str, str], languages: Optional[List[str]]
) -> List[str]:
    """Extract deterministically ordered non-empty labels from a language map.

    Args:
        label_map: Mapping of language tag to label string.
        languages: Optional allowed language tags.

    Returns:
        List of cleaned non-empty labels in sorted language order.
    """
    allowed = set(languages) if languages is not None else None
    labels: List[str] = []
    for lang in sorted(label_map.keys()):
        if allowed is not None and lang not in allowed:
            continue
        val = (label_map[lang] or "").strip()
        if val:
            labels.append(val)
    return labels


def format_expanded_lexical_query(
    original_query: str,
    expanded_terms: List[SemanticExpansionTerm],
) -> str:
    """Format original + expanded terms into a safe OR lexical query.

    Args:
        original_query: Unmodified user query text.
        expanded_terms: Full list of terms (original first).

    Returns:
        Formatted lexical query string preserving the original query.
    """
    if len(expanded_terms) <= 1:
        return original_query

    parts: List[str] = []
    for item in expanded_terms:
        clean = item.term.replace('"', "").strip()
        if clean:
            parts.append(f'"{clean}"')
    return " OR ".join(parts) if parts else original_query


def finalize_expansion_terms(
    original_query: str,
    candidates: Iterable[SemanticExpansionTerm],
    policy: ExpansionPolicy,
) -> List[SemanticExpansionTerm]:
    """Deduplicate, deterministically sort, and budget expansion candidates.

    Args:
        original_query: Original user search query.
        candidates: Candidate SemanticExpansionTerm instances.
        policy: Active ExpansionPolicy specifying term budget.

    Returns:
        Ordered list starting with the original query term followed by up to
        ``policy.max_expanded_terms`` unique highest-weight expanded terms.
    """
    orig_clean = original_query.strip()
    orig_key = orig_clean.lower()

    best_by_key: Dict[str, SemanticExpansionTerm] = {}
    for cand in candidates:
        term_clean = cand.term.strip()
        if not term_clean:
            continue
        key = term_clean.lower()
        if key == orig_key:
            continue

        existing = best_by_key.get(key)
        if existing is None or _candidate_rank_key(cand) < _candidate_rank_key(
            existing
        ):
            best_by_key[key] = cand.model_copy(update={"term": term_clean})

    ordered_added = sorted(best_by_key.values(), key=_candidate_rank_key)
    budgeted = ordered_added[: policy.max_expanded_terms]

    original_term = SemanticExpansionTerm(
        term=orig_clean,
        weight=1.0,
        relationship="original",
        source_type="original",
        hop_depth=0,
    )
    return [original_term] + budgeted


def _candidate_rank_key(
    term: SemanticExpansionTerm,
) -> Tuple[float, int, str, str, str]:
    """Deterministic sort key preferring higher weight, then shallower hops."""
    return (
        -term.weight,
        term.hop_depth,
        term.term.lower(),
        term.relationship,
        term.source_uri or "",
    )


class OntologyQueryExpander:
    """Expands queries from approved ontology releases with full provenance.

    Reads only ``approved`` ``OntologyReleaseRecord`` rows and ``active`` class
    and property records; draft and deprecated releases/terms are strictly
    ignored.
    """

    def __init__(
        self,
        session_or_factory: SessionOrFactory,
        policy: Optional[ExpansionPolicy] = None,
        release_ids: Optional[List[uuid.UUID]] = None,
    ) -> None:
        """Initialize OntologyQueryExpander.

        Args:
            session_or_factory: AsyncSession or async_sessionmaker factory.
            policy: Optional default ExpansionPolicy.
            release_ids: Optional list of approved OntologyReleaseRecord UUIDs
                to pin expansion to.
        """
        self.session_or_factory = session_or_factory
        self.policy = policy or ExpansionPolicy()
        self.release_ids = (
            list(release_ids) if release_ids is not None else None
        )

    async def expand_query(
        self,
        query_text: str,
        *,
        release_ids: Optional[List[uuid.UUID]] = None,
        policy: Optional[ExpansionPolicy] = None,
    ) -> SemanticExpansionTrace:
        """Expand a search query using approved ontology classes and properties.

        Args:
            query_text: Original query string.
            release_ids: Optional per-call approved release UUID filter.
            policy: Optional per-call ExpansionPolicy override.

        Returns:
            SemanticExpansionTrace containing ordered terms and source URIs.
        """
        start = time.perf_counter()
        active_policy = policy or self.policy
        pinned_ids = (
            release_ids if release_ids is not None else self.release_ids
        )

        candidates, used_releases = await self.collect_ontology_candidates(
            query_text=query_text,
            policy=active_policy,
            release_ids=pinned_ids,
        )
        terms = finalize_expansion_terms(
            query_text, candidates, active_policy
        )
        expanded_query = format_expanded_lexical_query(query_text, terms)
        duration_ms = round((time.perf_counter() - start) * 1000.0, 3)

        return SemanticExpansionTrace(
            expansion_applied=len(terms) > 1,
            original_query=query_text,
            expanded_query=expanded_query,
            expanded_term_count=len(terms),
            terms=terms,
            sources_consulted=["ontology"],
            release_ids=sorted(used_releases),
            duration_ms=duration_ms,
        )

    async def collect_ontology_candidates(
        self,
        query_text: str,
        policy: ExpansionPolicy,
        release_ids: Optional[List[uuid.UUID]] = None,
    ) -> Tuple[List[SemanticExpansionTerm], Set[str]]:
        """Collect candidate terms from approved ontology releases.

        Args:
            query_text: Input search query string.
            policy: ExpansionPolicy governing enabled relations and depth.
            release_ids: Optional approved release UUID whitelist.

        Returns:
            Tuple of (candidate SemanticExpansionTerm list, release ID strings).
        """
        query_lower = query_text.strip().lower()
        if not query_lower:
            return [], set()

        if release_ids is not None and len(release_ids) == 0:
            return [], set()

        stmt = (
            select(OntologyReleaseRecord)
            .where(OntologyReleaseRecord.status == "approved")
            .options(
                selectinload(OntologyReleaseRecord.classes),
                selectinload(OntologyReleaseRecord.properties),
            )
            .order_by(
                OntologyReleaseRecord.ontology_uri.asc(),
                OntologyReleaseRecord.version.asc(),
                OntologyReleaseRecord.id.asc(),
            )
        )
        if release_ids is not None:
            stmt = stmt.where(OntologyReleaseRecord.id.in_(release_ids))

        async with acquire_session(self.session_or_factory) as (session, _):
            result = await session.execute(stmt)
            releases = list(result.scalars().all())

        candidates: List[SemanticExpansionTerm] = []
        used_releases: Set[str] = set()
        enabled = set(policy.enabled_relations)

        for release in releases:
            rel_candidates = self._expand_release(
                release, query_lower, policy, enabled
            )
            if rel_candidates:
                candidates.extend(rel_candidates)
                used_releases.add(str(release.id))

        return candidates, used_releases

    def _expand_release(
        self,
        release: OntologyReleaseRecord,
        query_lower: str,
        policy: ExpansionPolicy,
        enabled: Set[str],
    ) -> List[SemanticExpansionTerm]:
        """Expand matching active classes and properties in one release."""
        active_classes: Dict[str, OntologyClassRecord] = {
            cls.uri: cls
            for cls in sorted(release.classes, key=lambda c: c.uri)
            if cls.status == "active"
        }
        children_by_parent: Dict[str, List[str]] = {}
        for cls_uri, cls in active_classes.items():
            for parent_uri in sorted(cls.parent_class_uris or []):
                if parent_uri in active_classes:
                    children_by_parent.setdefault(parent_uri, []).append(
                        cls_uri
                    )

        active_props: Dict[str, OntologyPropertyRecord] = {
            prop.uri: prop
            for prop in sorted(release.properties, key=lambda p: p.uri)
            if prop.status == "active"
        }
        inverses_by_uri: Dict[str, List[str]] = {}
        for prop_uri, prop in active_props.items():
            inv_uri = prop.inverse_property_uri
            if inv_uri and inv_uri in active_props:
                inverses_by_uri.setdefault(prop_uri, []).append(inv_uri)
                inverses_by_uri.setdefault(inv_uri, []).append(prop_uri)

        candidates: List[SemanticExpansionTerm] = []

        # 1. Match active classes and traverse bounded parent/child hierarchy
        for cls_uri, cls in active_classes.items():
            all_labels = select_labels(cls.preferred_labels or {}, None)
            matched_labels = [
                lbl
                for lbl in all_labels
                if label_matches_query(lbl, query_lower)
            ]
            if not matched_labels:
                continue
            matched_lower = {lbl.lower() for lbl in matched_labels}

            if "preferred_label" in enabled:
                for lbl in select_labels(
                    cls.preferred_labels or {}, policy.languages
                ):
                    if lbl.lower() not in matched_lower:
                        candidates.append(
                            SemanticExpansionTerm(
                                term=lbl,
                                weight=policy.weight_for(
                                    "preferred_label", hop_depth=0
                                ),
                                relationship="preferred_label",
                                source_type="ontology_class",
                                source_uri=cls_uri,
                                release_id=release.id,
                                hop_depth=0,
                            )
                        )

            if policy.max_depth >= 1 and "ontology_parent" in enabled:
                candidates.extend(
                    self._traverse_classes(
                        start_uri=cls_uri,
                        neighbor_fn=lambda u: sorted(
                            active_classes[u].parent_class_uris or []
                        ),
                        active_classes=active_classes,
                        release_id=release.id,
                        relationship="ontology_parent",
                        policy=policy,
                    )
                )

            if policy.max_depth >= 1 and "ontology_child" in enabled:
                candidates.extend(
                    self._traverse_classes(
                        start_uri=cls_uri,
                        neighbor_fn=lambda u: sorted(
                            children_by_parent.get(u, [])
                        ),
                        active_classes=active_classes,
                        release_id=release.id,
                        relationship="ontology_child",
                        policy=policy,
                    )
                )

        # 2. Match active properties and their active inverse properties
        for prop_uri, prop in active_props.items():
            all_labels = select_labels(prop.preferred_labels or {}, None)
            matched_labels = [
                lbl
                for lbl in all_labels
                if label_matches_query(lbl, query_lower)
            ]
            if not matched_labels:
                continue
            matched_lower = {lbl.lower() for lbl in matched_labels}

            if "ontology_property" in enabled:
                for lbl in select_labels(
                    prop.preferred_labels or {}, policy.languages
                ):
                    if lbl.lower() not in matched_lower:
                        candidates.append(
                            SemanticExpansionTerm(
                                term=lbl,
                                weight=policy.weight_for(
                                    "ontology_property", hop_depth=0
                                ),
                                relationship="ontology_property",
                                source_type="ontology_property",
                                source_uri=prop_uri,
                                release_id=release.id,
                                hop_depth=0,
                            )
                        )

            if "ontology_inverse" in enabled:
                for inv_uri in sorted(set(inverses_by_uri.get(prop_uri, []))):
                    inv_prop = active_props[inv_uri]
                    for lbl in select_labels(
                        inv_prop.preferred_labels or {}, policy.languages
                    ):
                        candidates.append(
                            SemanticExpansionTerm(
                                term=lbl,
                                weight=policy.weight_for(
                                    "ontology_inverse", hop_depth=1
                                ),
                                relationship="ontology_inverse",
                                source_type="ontology_property",
                                source_uri=inv_uri,
                                release_id=release.id,
                                hop_depth=1,
                            )
                        )

        return candidates

    @staticmethod
    def _traverse_classes(
        start_uri: str,
        neighbor_fn: Any,
        active_classes: Dict[str, OntologyClassRecord],
        release_id: uuid.UUID,
        relationship: str,
        policy: ExpansionPolicy,
    ) -> List[SemanticExpansionTerm]:
        """Bounded breadth-first traversal over active ontology classes."""
        visited: Set[str] = {start_uri}
        queue: deque[Tuple[str, int]] = deque([(start_uri, 0)])
        collected: List[SemanticExpansionTerm] = []

        while queue:
            current_uri, depth = queue.popleft()
            if depth >= policy.max_depth:
                continue
            next_depth = depth + 1
            for neighbor_uri in neighbor_fn(current_uri):
                if (
                    neighbor_uri in visited
                    or neighbor_uri not in active_classes
                ):
                    continue
                visited.add(neighbor_uri)
                neighbor = active_classes[neighbor_uri]
                weight = policy.weight_for(relationship, hop_depth=next_depth)
                for lbl in select_labels(
                    neighbor.preferred_labels or {}, policy.languages
                ):
                    collected.append(
                        SemanticExpansionTerm(
                            term=lbl,
                            weight=weight,
                            relationship=relationship,
                            source_type="ontology_class",
                            source_uri=neighbor_uri,
                            release_id=release_id,
                            hop_depth=next_depth,
                        )
                    )
                queue.append((neighbor_uri, next_depth))

        return collected
