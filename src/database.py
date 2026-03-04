"""Database connection and session management.

T008: Setup SQLAlchemy async engine in src/database.py
DoD: async with get_session() 可取得 AsyncSession；連線 Supabase 成功
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


# Create async engine with connection pooling
engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,  # Log SQL in development
    pool_pre_ping=True,  # Verify connections before use
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,  # Wait up to 30s for a connection
    connect_args={
        "timeout": 30,  # Connection timeout
        "server_settings": {"application_name": "japanese-learning-bot"},
    },
)

# Session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session.

    Usage:
        async with get_session() as session:
            result = await session.execute(query)

    Yields:
        AsyncSession: Database session that auto-commits on success
                      and rolls back on exception.
    """
    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """Initialize database tables.

    Creates all tables defined in models if they don't exist.
    For production, use Alembic migrations instead.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections.

    Should be called on application shutdown.
    """
    await engine.dispose()
