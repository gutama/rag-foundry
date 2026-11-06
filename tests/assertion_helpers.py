"""Seed data shared by the assertion test modules."""

import uuid

from rag_foundry.assertions import lifecycle as lc
from rag_foundry.db.models import Chunk, Document
from rag_foundry.entities import store as st
from tests.ontology_samples import EX, build_finance_release

ID = "http://id.example.org/entity/"
WS = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
OTHER_WS = uuid.UUID("00000000-0000-4000-8000-0000000000cc")
PROFILE = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
RELEASE = build_finance_release().model_copy(update={"status": "approved"})

SEED_ENTITIES = [
    ("bca", "Bank", WS),
    ("bca-dup", "Bank", WS),
    ("ojk", "Regulator", WS),
    ("budi", "Person", WS),
    ("far", "Bank", OTHER_WS),
]


async def make_chunk(session, workspace=WS):
    """Create a document with one chunk; return the chunk id."""
    document = Document(
        document_id=uuid.uuid4(), workspace_id=workspace, title="Licence",
        mime_type="application/pdf", checksum="0" * 64, parser_name="p",
        parser_version="1", semantic_profile_id=PROFILE,
    )
    session.add(document)
    await session.flush()
    chunk = Chunk(
        document_version_id=document.id, workspace_id=workspace,
        text="PT Bank Central Asia Tbk is licensed by OJK.",
        checksum="1" * 64, chunker_name="c", chunker_version="1",
        semantic_profile_id=PROFILE,
    )
    session.add(chunk)
    await session.flush()
    return chunk.id


async def seed(session):
    """Create the seed entities and two chunks; return ids by name."""
    store = st.EntityStore(session)
    ids = {}
    for name, cls, workspace in SEED_ENTITIES:
        entity = await store.create_entity(
            workspace_id=workspace, semantic_profile_id=PROFILE,
            canonical_uri=ID + name, ontology_class_uri=EX + cls,
            preferred_labels={"en": name},
        )
        ids[name] = entity.id
    ids["chunk"] = await make_chunk(session)
    ids["far-chunk"] = await make_chunk(session, OTHER_WS)
    return ids


async def create_assertion(
    session, ids, subject="bca", prop="legalName", **kwargs
):
    """Create a candidate assertion with sensible defaults."""
    fields = {
        "actor_id": "extractor:1",
        "workspace_id": WS,
        "semantic_profile_id": PROFILE,
        "subject_entity_id": ids[subject],
        "property_uri": EX + prop,
        "origin": "extracted",
        "extraction_method": "llm",
        "confidence": 0.9,
        "source_chunk_ids": [ids["chunk"]],
    }
    if "object" in kwargs:
        fields["object_entity_id"] = ids[kwargs.pop("object")]
    else:
        fields["literal_value"] = kwargs.pop("literal", "PT BCA Tbk")
    fields.update(kwargs)
    return await lc.AssertionStore(session).create_assertion(**fields)
