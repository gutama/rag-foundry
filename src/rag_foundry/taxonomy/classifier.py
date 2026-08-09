"""SemanticClassifier for document and chunk concept assignment."""

import uuid
from typing import List, Optional

from pydantic import BaseModel, Field

from rag_foundry.taxonomy.models import SKOSConceptSchemeModel


class ClassificationAssignment(BaseModel):
    """Container for a concept assignment to text."""

    concept_uri: str = Field(description="Assigned SKOS concept URI")
    pref_label: str = Field(description="Preferred label of assigned concept")
    confidence_score: float = Field(
        description="Classification confidence score (0.0 - 1.0)"
    )
    matched_mention: str = Field(description="Text surface mention matched")
    is_deprecated: bool = Field(
        default=False, description="True if assigned concept is deprecated"
    )


class ClassificationResult(BaseModel):
    """Result of semantic classification run."""

    document_id: Optional[uuid.UUID] = Field(
        default=None, description="Optional document UUID"
    )
    assignments: List[ClassificationAssignment] = Field(
        default_factory=list, description="List of concept assignments"
    )
    taxonomy_version: str = Field(
        description="Version string of taxonomy scheme used"
    )
    deprecated_concepts_flagged: List[str] = Field(
        default_factory=list,
        description="List of deprecated concept URIs flagged",
    )


class SemanticClassifier:
    """Classifier matching text against SKOS concept schemes with audit."""

    def __init__(self, scheme: SKOSConceptSchemeModel) -> None:
        """Initialize SemanticClassifier.

        Args:
            scheme: SKOSConceptSchemeModel object.
        """
        self.scheme = scheme

    def classify_text(
        self, text: str, document_id: Optional[uuid.UUID] = None
    ) -> ClassificationResult:
        """Classify text against SKOS concept scheme.

        Args:
            text: Text content to analyze.
            document_id: Optional document UUID.

        Returns:
            ClassificationResult container.
        """
        txt_lower = text.lower()
        assignments: List[ClassificationAssignment] = []
        deprecated_flagged: List[str] = []

        for concept in self.scheme.concepts:
            # Check pref_label exact match
            pref_matched = concept.pref_label.lower() in txt_lower
            matched_label = None
            score = 0.0

            if pref_matched:
                matched_label = concept.pref_label
                score = 1.0
            else:
                for alt in concept.alt_labels:
                    if alt.lower() in txt_lower:
                        matched_label = alt
                        score = 0.85
                        break

            if matched_label:
                assignment = ClassificationAssignment(
                    concept_uri=concept.uri,
                    pref_label=concept.pref_label,
                    confidence_score=score,
                    matched_mention=matched_label,
                    is_deprecated=concept.is_deprecated,
                )
                assignments.append(assignment)

                if concept.is_deprecated:
                    if concept.uri not in deprecated_flagged:
                        deprecated_flagged.append(concept.uri)

        return ClassificationResult(
            document_id=document_id,
            assignments=assignments,
            taxonomy_version=self.scheme.version,
            deprecated_concepts_flagged=deprecated_flagged,
        )
