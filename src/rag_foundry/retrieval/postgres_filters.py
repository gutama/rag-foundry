"""Shared pre-retrieval ACL filters and session utilities for DB retrievers."""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union

from pydantic import ValidationError
from sqlalchemy import Text, cast, literal
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from rag_foundry.db.models import Chunk
from rag_foundry.retrieval.models import BoundingBox, RetrievalQuery

SessionOrFactory = Union[AsyncSession, async_sessionmaker[AsyncSession]]


@asynccontextmanager
async def acquire_session(
    session_or_factory: SessionOrFactory,
) -> AsyncIterator[Tuple[AsyncSession, str]]:
    """Yield an AsyncSession and its SQL dialect name safely under concurrency.

    When a single shared AsyncSession is provided, a per-session asyncio.Lock
    serializes concurrent gather calls safely. When an async_sessionmaker is
    provided, each retrieval opens an independent pooled session.

    Args:
        session_or_factory: Bound AsyncSession or async_sessionmaker factory.

    Yields:
        Tuple of (session, dialect_name).
    """
    if isinstance(session_or_factory, AsyncSession):
        lock = session_or_factory.info.setdefault(
            "_rag_foundry_session_lock", asyncio.Lock()
        )
        async with lock:
            bind = session_or_factory.get_bind()
            dialect_name = bind.dialect.name if bind is not None else "sqlite"
            yield session_or_factory, dialect_name
    else:
        async with session_or_factory() as session:
            bind = session.get_bind()
            dialect_name = bind.dialect.name if bind is not None else "sqlite"
            yield session, dialect_name


def build_chunk_acl_conditions(
    query: RetrievalQuery,
    dialect_name: str,
) -> Optional[List[ColumnElement[bool]]]:
    """Build SQL WHERE predicates enforcing pre-retrieval ACL isolation.

    Returns ``None`` when the filter fails closed (empty allowed security
    domains or an explicit empty ``document_ids`` whitelist). Metadata filters
    enforce exact per-key JSON equality with key presence so PostgreSQL,
    SQLite, and in-memory retrievers match identically.

    Args:
        query: RetrievalQuery specifying workspace, domains, and filters.
        dialect_name: Target SQLAlchemy dialect name (e.g. 'postgresql').

    Returns:
        List of SQLAlchemy boolean expressions, or ``None`` to fail closed.
    """
    filt = query.filter
    if not filt.security_domains:
        return None
    if filt.document_ids is not None and len(filt.document_ids) == 0:
        return None

    conditions: List[ColumnElement[bool]] = [
        Chunk.workspace_id == filt.workspace_id,
        Chunk.security_domain.in_(filt.security_domains),
    ]
    if filt.document_ids is not None:
        conditions.append(Chunk.document_version_id.in_(filt.document_ids))

    if filt.metadata_filters and dialect_name == "postgresql":
        jsonb_col = cast(Chunk.chunk_metadata, postgresql.JSONB)
        for key in sorted(filt.metadata_filters.keys()):
            val_json = json.dumps(filt.metadata_filters[key])
            lhs = jsonb_col.op("->", return_type=postgresql.JSONB)(
                literal(key, type_=Text())
            )
            rhs = cast(literal(val_json, type_=Text()), postgresql.JSONB)
            conditions.append(lhs == rhs)

    return conditions


def _json_exact_equal(actual: Any, expected: Any) -> bool:
    """Compare two JSON-compatible values using PostgreSQL JSONB ``=`` rules."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _json_exact_equal(actual[k], expected[k]) for k in actual
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _json_exact_equal(a, b) for a, b in zip(actual, expected)
        )
    return bool(actual == expected)


def matches_metadata_filters(
    chunk_metadata: Optional[Dict[str, Any]],
    metadata_filters: Dict[str, Any],
) -> bool:
    """Evaluate exact per-key metadata filters matching PostgreSQL JSONB ``=``.

    Args:
        chunk_metadata: Persisted metadata dictionary on a Chunk row.
        metadata_filters: Required key-value pairs from RetrievalFilter.

    Returns:
        True if every required key is present and equals the expected value.
    """
    if not metadata_filters:
        return True
    meta = chunk_metadata or {}
    return all(
        k in meta and _json_exact_equal(meta[k], v)
        for k, v in metadata_filters.items()
    )


def parse_chunk_bounding_boxes(raw_boxes: Any) -> List[BoundingBox]:
    """Convert serialized JSON bounding box dicts into BoundingBox models.

    Args:
        raw_boxes: Persisted JSON list of bounding box dictionaries.

    Returns:
        List of validated BoundingBox instances.
    """
    if not raw_boxes:
        return []
    boxes: List[BoundingBox] = []
    for item in raw_boxes:
        if isinstance(item, BoundingBox):
            boxes.append(item)
        elif isinstance(item, dict):
            try:
                boxes.append(BoundingBox(**item))
            except ValidationError:
                continue
    return boxes
