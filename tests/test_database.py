"""Tests for database engine connection and async session context manager."""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_get_async_session_context_manager():
    """Test async session context manager executes queries and cleans up."""
    from rag_foundry.db.session import get_async_session

    async with get_async_session("sqlite+aiosqlite:///:memory:") as session:
        assert isinstance(session, AsyncSession)
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.asyncio
async def test_create_async_engine_and_sessionmaker():
    """Test creating an async engine and session factory."""
    from rag_foundry.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker("sqlite+aiosqlite:///:memory:")
    async with sessionmaker() as session:
        result = await session.execute(text("SELECT 42"))
        assert result.scalar() == 42
