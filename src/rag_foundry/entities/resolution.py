"""Entity resolution: normalization and candidate generation (ADR-0012).

Resolution follows ARCHITECTURE.md §8.6:

    mention -> normalization -> candidate generation -> ontology class
    constraints -> deterministic identifiers -> similarity and rule
    scoring -> confidence threshold -> automatic match or steward review

This module covers the steps up to scoring. Signals, strongest first:

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
"""

import unicodedata
import uuid
from difflib import SequenceMatcher
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from rag_foundry.entities.models import Entity, Mention
from rag_foundry.ontology.models import OntologyRelease

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
        """Score eligible entities against a mention.

        Args:
            mention: The mention to resolve.
            entities: Entities to consider; ineligible ones are skipped.

        Returns:
            Candidates sorted by score, then canonical IRI, truncated to
            ``max_candidates``.
        """
        text = normalize_text(mention.surface_text)
        matches = []
        for entity in entities:
            if self._eligible(mention, entity):
                match = self._score(mention, text, entity)
                if match is not None:
                    matches.append(match)
        matches.sort(key=lambda m: (-m.score, m.canonical_uri))
        return matches[: self.max_candidates]

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
