"""Dialect-aware SQLAlchemy column types for PostgreSQL pgvector and FTS."""

from typing import Any, List, Optional, Sequence

from sqlalchemy import JSON, Text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine, UserDefinedType

DEFAULT_EMBEDDING_DIM = 384


class _PgVectorSQLType(UserDefinedType):
    """PostgreSQL pgvector SQL type compiling to vector(N) or vector."""

    cache_ok = True

    def __init__(self, dim: Optional[int] = None) -> None:
        """Initialize the underlying PostgreSQL vector SQL type.

        Args:
            dim: Optional fixed dimensionality for ``vector(N)`` DDL.
        """
        self.dim = dim

    def get_col_spec(self, **kw: Any) -> str:
        """Return PostgreSQL DDL specification string."""
        if self.dim is not None:
            return f"vector({self.dim})"
        return "vector"


class VectorType(TypeDecorator):
    """Dialect-aware dense vector column type.

    Compiles to PostgreSQL pgvector ``vector(N)`` (or ``vector`` when
    unbounded) on PostgreSQL and stores JSON float lists on SQLite and other
    dialects so unit tests execute without requiring a live PostgreSQL server.
    """

    impl = JSON
    cache_ok = True

    class comparator_factory(TypeDecorator.Comparator):
        """Expose pgvector distance operators on mapped columns."""

        def cosine_distance(self, other: Any) -> Any:
            """Return SQL expression using the pgvector ``<=>`` operator."""
            return self.op("<=>")(other)

    def __init__(self, dim: Optional[int] = None) -> None:
        """Initialize a dialect-aware vector column type.

        Args:
            dim: Optional positive embedding dimensionality.

        Raises:
            ValueError: If ``dim`` is provided and not positive.
        """
        super().__init__()
        if dim is not None and dim <= 0:
            raise ValueError("Vector dimension must be positive.")
        self.dim = dim

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        """Select pgvector SQL type for PostgreSQL or JSON fallback."""
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PgVectorSQLType(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(
        self, value: Optional[Sequence[float]], dialect: Dialect
    ) -> Any:
        """Serialize a sequence of floats for the target SQL dialect."""
        if value is None:
            return None
        floats = [float(v) for v in value]
        if dialect.name == "postgresql":
            return "[" + ",".join(repr(v) for v in floats) + "]"
        return floats

    def process_result_value(
        self, value: Any, dialect: Dialect
    ) -> Optional[List[float]]:
        """Deserialize a stored vector value into a Python list of floats."""
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                inner = stripped[1:-1].strip()
                if not inner:
                    return []
                return [float(part) for part in inner.split(",")]
        return [float(v) for v in value]


class TSVectorType(TypeDecorator):
    """Dialect-aware PostgreSQL Full-Text Search (TSVECTOR) column type.

    Compiles to native ``TSVECTOR`` on PostgreSQL and ``TEXT`` on SQLite and
    other dialects.
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        """Select PostgreSQL TSVECTOR or fallback TEXT type."""
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.TSVECTOR())
        return dialect.type_descriptor(Text())
