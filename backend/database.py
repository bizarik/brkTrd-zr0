"""Database configuration and session management"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from config import settings

# Database setup
engine_kwargs = {
    "echo": settings.debug,
}

# Add SQLite-specific settings only for SQLite
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    # Ensure SQLite database directory exists
    import os
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if db_dir:  # Only create directory if there is one
        os.makedirs(db_dir, exist_ok=True)
else:
    # Add pooling parameters for PostgreSQL and other databases
    engine_kwargs.update({
        "pool_size": 20,
        "max_overflow": 40,
        "pool_pre_ping": True,
        "pool_recycle": 3600
    })

engine = create_async_engine(
    settings.database_url,
    **engine_kwargs
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


# Dependency to get database session
async def get_db():
    """Get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
