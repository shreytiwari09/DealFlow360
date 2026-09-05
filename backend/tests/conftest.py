"""Test fixtures.

Two kinds of test live here:

* Pure tests (state machines, risk arithmetic) that touch nothing external.
* Database tests that run against the real PostgreSQL schema, because the
  point of them is to prove the *database* rejects bad data. Asserting that
  against SQLite or a mock would prove nothing about production behaviour.

Every database test runs inside a transaction that is rolled back afterwards,
so the suite leaves no residue and can be run repeatedly against the
development database.
"""

import os
from collections.abc import AsyncGenerator

# Secrets have no in-code default, so tests must supply their own before
# app.core.config is imported. setdefault, not assignment: inside Docker
# Compose the real values are already present and should win.
os.environ.setdefault("POSTGRES_PASSWORD", "test-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-signing-key-not-used-for-anything")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.main import app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A session whose writes are always rolled back.

    `join_transaction_mode="create_savepoint"` is what makes this work: the
    session's own commits become savepoint releases nested inside the outer
    transaction, so a test may call `commit()` or trigger and recover from an
    IntegrityError, and the outer rollback still undoes everything.
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
