"""Async SQLAlchemy database engine and session.

Use this module instead of database.py when running with PostgreSQL.
Falls back to sync SQLite when DATABASE_URL starts with 'sqlite'.
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import DATABASE_URL
from ..models.orm import Base

# Detect if using async-capable database
_is_sqlite = DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    # Sync SQLite engine (current behavior)
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def get_sync_session() -> Session:
        return SessionLocal()

    def init_models():
        Base.metadata.create_all(bind=engine)
else:
    # Async PostgreSQL engine
    # Convert postgres:// to postgresql+asyncpg://
    async_url = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://").replace("postgresql://", "postgresql+asyncpg://")
    sync_url = DATABASE_URL.replace("postgres://", "postgresql://")

    async_engine = create_async_engine(async_url, echo=False, pool_size=10, max_overflow=20)
    AsyncSessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)

    # Also create sync engine for migrations and startup
    engine = create_engine(sync_url, echo=False)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def get_sync_session() -> Session:
        return SessionLocal()

    def init_models():
        Base.metadata.create_all(bind=engine)

    async def get_async_session() -> AsyncSession:
        async with AsyncSessionLocal() as session:
            yield session
