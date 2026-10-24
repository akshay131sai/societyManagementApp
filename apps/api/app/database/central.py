"""Central database engine and session factory.

One engine for the whole process, created at startup and disposed at shutdown.
A connection is never created per request — the pool hands one out.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_central_engine() -> AsyncEngine:
    """Process-wide central engine, created lazily on first use."""
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.central_dsn_async,
            pool_size=settings.CENTRAL_POOL_SIZE,
            max_overflow=settings.CENTRAL_POOL_MAX_OVERFLOW,
            pool_recycle=settings.POOL_RECYCLE_SECONDS,
            pool_timeout=settings.POOL_TIMEOUT_SECONDS,
            pool_pre_ping=True,
            echo=False,
            future=True,
        )
        _sessionmaker = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _engine


def get_central_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        get_central_engine()
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def central_session() -> AsyncIterator[AsyncSession]:
    """Standalone central session for scripts, workers and provisioning.

    Commits on success, rolls back on exception. Request handlers use the
    ``get_central_session`` FastAPI dependency instead.
    """
    factory = get_central_sessionmaker()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_central_engine() -> None:
    """Close the pool. Called on application shutdown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
