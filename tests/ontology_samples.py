"""Sample ontology releases shared by the ontology test modules."""

import uuid
from datetime import datetime, timezone

from rag_foundry.ontology.models import (
    OntologyClass,
    OntologyProperty,
    OntologyRelease,
    PropertyConstraint,
)

ONTO = "http://example.org/finance"
EX = ONTO + "#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def _cls(name, parents=(), **kwargs):
    """Build a class in the finance namespace."""
    return OntologyClass(
        uri=EX + name,
        preferred_labels=kwargs.pop("labels", {"en": name}),
        parent_class_uris=[EX + p for p in parents],
        **kwargs,
    )


def build_finance_release() -> OntologyRelease:
    """Build a small finance ontology exercising every supported feature.

    Covers multilingual labels, descriptions, identity rules, multiple
    inheritance, a deprecated class, object and data properties, an
    inverse, union domains and ranges, temporal and provenance flags, and
    both constraint kinds on several datatypes.
    """
    classes = [
        _cls("Agent", labels={"en": "Agent", "id": "Agen"}),
        _cls("Organization", ["Agent"], labels={
            "en": "Organization", "id": "Organisasi"}),
        _cls(
            "Bank",
            ["Organization"],
            labels={"en": "Bank", "id": "Bank"},
            description={"en": "A licensed deposit-taking institution"},
            identity_rules=[
                "same national bank code",
                "same legal name and jurisdiction",
            ],
        ),
        _cls("Person", ["Agent"], labels={"en": "Person", "id": "Orang"}),
        _cls("Regulator", ["Organization"]),
        _cls("SavingsAndLoan", ["Bank"], status="deprecated"),
    ]
    properties = [
        OntologyProperty(
            uri=EX + "employedBy",
            preferred_labels={"en": "employed by"},
            property_type="object",
            domain_class_uris=[EX + "Person"],
            range_class_uris=[EX + "Organization"],
        ),
        OntologyProperty(
            uri=EX + "employs",
            preferred_labels={"en": "employs", "id": "mempekerjakan"},
            property_type="object",
            domain_class_uris=[EX + "Organization"],
            range_class_uris=[EX + "Person"],
            inverse_property_uri=EX + "employedBy",
            temporal=True,
        ),
        OntologyProperty(
            uri=EX + "supervises",
            preferred_labels={"en": "supervises"},
            description={"en": "Prudential supervision relationship"},
            property_type="object",
            domain_class_uris=[EX + "Regulator"],
            range_class_uris=[EX + "Bank", EX + "Person"],
        ),
        OntologyProperty(
            uri=EX + "licensedBy",
            preferred_labels={"en": "licensed by"},
            property_type="object",
            domain_class_uris=[EX + "Bank"],
            range_class_uris=[EX + "Regulator"],
            constraints=[
                PropertyConstraint(
                    kind="allowed_values",
                    allowed_values=[EX + "ojk", EX + "bankIndonesia"],
                )
            ],
        ),
        OntologyProperty(
            uri=EX + "legalName",
            preferred_labels={"en": "legal name"},
            property_type="data",
            domain_class_uris=[EX + "Organization", EX + "Person"],
            datatype=XSD + "string",
            constraints=[PropertyConstraint(kind="cardinality", max_count=1)],
        ),
        OntologyProperty(
            uri=EX + "licenceStatus",
            preferred_labels={"en": "licence status"},
            property_type="data",
            domain_class_uris=[EX + "Bank"],
            datatype=XSD + "string",
            temporal=True,
            constraints=[
                PropertyConstraint(kind="cardinality", max_count=1),
                PropertyConstraint(
                    kind="allowed_values",
                    allowed_values=["active", "suspended", "revoked"],
                ),
            ],
        ),
        OntologyProperty(
            uri=EX + "foundedOn",
            preferred_labels={"en": "founded on"},
            property_type="data",
            domain_class_uris=[EX + "Organization"],
            datatype=XSD + "date",
            constraints=[
                PropertyConstraint(
                    kind="cardinality", min_count=1, max_count=1
                )
            ],
        ),
        OntologyProperty(
            uri=EX + "riskTier",
            preferred_labels={"en": "risk tier"},
            property_type="data",
            domain_class_uris=[EX + "Bank"],
            datatype=XSD + "integer",
            provenance_required=False,
            constraints=[
                PropertyConstraint(
                    kind="allowed_values", allowed_values=["1", "2", "3"]
                )
            ],
        ),
        OntologyProperty(
            uri=EX + "isSystemic",
            preferred_labels={"en": "is systemic"},
            property_type="data",
            domain_class_uris=[EX + "Bank"],
            datatype=XSD + "boolean",
            status="deprecated",
        ),
    ]
    return OntologyRelease(
        release_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        ontology_uri=ONTO,
        version="1.0.0",
        title="Finance Ontology",
        description="Sample ontology for tests",
        created_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        classes=classes,
        properties=properties,
    )
