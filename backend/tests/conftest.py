"""Test fixtures.

These tests deliberately run WITHOUT a live database so the foundation can be
validated on any machine. Database-backed tests arrive in Phase 2 alongside
the real models.
"""

import os

# Assigned, not setdefault: inside Docker Compose these variables are already
# populated with the live database, and setdefault would silently leave them
# pointing at it - making the "database unreachable" test pass against a
# healthy database and prove nothing.
os.environ["ENVIRONMENT"] = "test"
os.environ["POSTGRES_HOST"] = "127.0.0.1"
os.environ["POSTGRES_PORT"] = "1"  # guaranteed-closed port
os.environ["POSTGRES_PASSWORD"] = "test-only"
os.environ["JWT_SECRET_KEY"] = "test-only-signing-key-not-used-for-anything-real"

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
