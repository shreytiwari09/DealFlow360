"""Foundation checks for the health endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_session
from app.main import app


async def test_liveness_does_not_require_database(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "not_checked"


async def test_readiness_reports_ok_against_the_real_database(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"


class _FailingSession:
    """A stand-in session that fails the way a real one does.

    The failure has to happen on `execute`, not while the dependency is being
    resolved. `SessionLocal()` does not open a connection eagerly - asyncpg
    connects on first use - so a genuinely unreachable database raises inside
    the endpoint's try/except, where it becomes a 503. Raising earlier would
    escape to the global handler as a 500 and the test would be asserting
    against a situation that cannot occur.
    """

    async def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


@pytest.fixture
def broken_database():
    """Point the session dependency at a session whose queries fail.

    Overriding the dependency beats pointing configuration at a dead port: it
    exercises the endpoint's real error path without depending on
    process-wide environment state, and it runs instantly instead of waiting
    for a TCP timeout.
    """

    async def _failing_session():
        yield _FailingSession()

    app.dependency_overrides[get_session] = _failing_session
    yield
    app.dependency_overrides.clear()


async def test_readiness_reports_503_when_database_unreachable(
    client: AsyncClient, broken_database: None
) -> None:
    """A dead database must surface as 'not ready', not as a 500 or a hang."""
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"


async def test_error_response_does_not_leak_internals(
    client: AsyncClient, broken_database: None
) -> None:
    """SECURITY_SPEC.md Section 5: no stack traces, SQL, or paths in errors."""
    response = await client.get("/api/v1/health/ready")

    raw = response.text.lower()
    for leak in ("traceback", "asyncpg", "sqlalchemy", "connection refused", "password"):
        assert leak not in raw, f"error response leaked {leak!r}"
