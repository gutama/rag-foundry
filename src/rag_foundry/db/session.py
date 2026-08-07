"""Async database session management for SQLAlchemy 2.0."""

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from rag_foundry.core.config import Settings


def create_async_engine_from_config(url: Optional[str] = None) -> AsyncEngine:
    """Create an AsyncEngine instance.

    Args:
        url: Optional database URL. If omitted, uses Settings().postgres_dsn.

    Returns:
        AsyncEngine configured for async database execution.
    """
    if url is None:
        settings = Settings()
        url = settings.postgres_dsn
    return create_async_engine(url, echo=False)


def get_sessionmaker(url: Optional[str] = None) -> async_sessionmaker[AsyncSession]:
    """Get a configured async_sessionmaker factory.

    Args:
        url: Optional database URL.

    Returns:
        async_sessionmaker for producing AsyncSession instances.
    """
    engine = create_async_engine_from_config(url)
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


@asynccontextmanager
async def get_async_session(url: Optional[str] = None) -> AsyncIterator[AsyncSession]:
    """Async context manager providing a transactional AsyncSession.

    Args:
        url: Optional database URL.

    Yields:
        AsyncSession for executing database queries.
    """
    session_factory = get_sessionmaker(url)
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
