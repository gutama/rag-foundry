"""SKOS taxonomy importers and exporters (ADR-0010)."""

import csv
import io
from typing import Any, Dict, List

from rag_foundry.taxonomy.models import (
    SKOSConceptModel,
    SKOSConceptSchemeModel,
)


class SKOSImporter:
    """Importer for SKOS concept schemes from CSV, JSON-LD, and Turtle."""

    def import_csv(
        self, csv_content: str, scheme_id: str, scheme_uri: str
    ) -> SKOSConceptSchemeModel:
        """Import SKOS concept scheme from CSV text content.

        Args:
            csv_content: Raw CSV string.
            scheme_id: Scheme ID string.
            scheme_uri: Scheme URI string.

        Returns:
            SKOSConceptSchemeModel object.
        """
        reader = csv.DictReader(io.StringIO(csv_content.strip()))
        concepts: List[SKOSConceptModel] = []

        for row in reader:
            uri = row.get("uri", "").strip()
            pref_label = row.get("prefLabel", "").strip()
            if not uri or not pref_label:
                continue

            alt_str = row.get("altLabels", "")
            alt_labels = [
                a.strip() for a in alt_str.split(";") if a.strip()
            ]

            broader_str = row.get("broaderURIs", "")
            broader_uris = [
                b.strip() for b in broader_str.split(";") if b.strip()
            ]

            is_dep_str = str(row.get("isDeprecated", "false")).lower()
            is_deprecated = is_dep_str == "true"

            concept = SKOSConceptModel(
                scheme_uri=scheme_uri,
                uri=uri,
                pref_label=pref_label,
                alt_labels=alt_labels,
                broader_uris=broader_uris,
                is_deprecated=is_deprecated,
            )
            concepts.append(concept)

        return SKOSConceptSchemeModel(
            scheme_id=scheme_id,
            uri=scheme_uri,
            title=scheme_id,
            concepts=concepts,
        )

    def import_jsonld(
        self, data: Dict[str, Any], scheme_id: str, scheme_uri: str
    ) -> SKOSConceptSchemeModel:
        """Import SKOS concept scheme from JSON-LD dictionary.

        Args:
            data: JSON-LD dict structure containing `@graph`.
            scheme_id: Scheme ID string.
            scheme_uri: Scheme URI string.

        Returns:
            SKOSConceptSchemeModel object.
        """
        graph = data.get("@graph", [])
        concepts: List[SKOSConceptModel] = []

        for item in graph:
            uri = item.get("@id", "").strip()
            pref_label = item.get("prefLabel", "")
            if not uri or not pref_label:
                continue

            alt = item.get("altLabel", [])
            alt_labels = alt if isinstance(alt, list) else [str(alt)]

            broader = item.get("broader", [])
            broader_uris = (
                broader if isinstance(broader, list) else [str(broader)]
            )

            concept = SKOSConceptModel(
                scheme_uri=scheme_uri,
                uri=uri,
                pref_label=str(pref_label),
                alt_labels=[str(a) for a in alt_labels],
                broader_uris=[str(b) for b in broader_uris],
            )
            concepts.append(concept)

        return SKOSConceptSchemeModel(
            scheme_id=scheme_id,
            uri=scheme_uri,
            title=scheme_id,
            concepts=concepts,
        )


class SKOSExporter:
    """Exporter for SKOS concept schemes to CSV, JSON-LD, and Turtle."""

    def export_csv(self, scheme: SKOSConceptSchemeModel) -> str:
        """Export SKOS concept scheme to CSV string.

        Args:
            scheme: SKOSConceptSchemeModel object.

        Returns:
            CSV formatted string.
        """
        output = io.StringIO()
        fieldnames = [
            "uri",
            "prefLabel",
            "altLabels",
            "broaderURIs",
            "isDeprecated",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for c in scheme.concepts:
            writer.writerow(
                {
                    "uri": c.uri,
                    "prefLabel": c.pref_label,
                    "altLabels": ";".join(c.alt_labels),
                    "broaderURIs": ";".join(c.broader_uris),
                    "isDeprecated": str(c.is_deprecated).lower(),
                }
            )

        return output.getvalue()

    def export_jsonld(self, scheme: SKOSConceptSchemeModel) -> Dict[str, Any]:
        """Export SKOS concept scheme to JSON-LD dictionary.

        Args:
            scheme: SKOSConceptSchemeModel object.

        Returns:
            JSON-LD dictionary.
        """
        graph: List[Dict[str, Any]] = []

        for c in scheme.concepts:
            graph.append(
                {
                    "@id": c.uri,
                    "@type": "skos:Concept",
                    "prefLabel": c.pref_label,
                    "altLabel": c.alt_labels,
                    "broader": c.broader_uris,
                }
            )

        return {
            "@context": {
                "skos": "http://www.w3.org/2004/02/skos/core#",
                "prefLabel": "skos:prefLabel",
                "altLabel": "skos:altLabel",
                "broader": "skos:broader",
            },
            "@graph": graph,
        }
