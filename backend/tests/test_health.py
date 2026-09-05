"""Phase 1 foundation checks."""

from httpx import AsyncClient


async def test_liveness_does_not_require_database(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "not_checked"


async def test_readiness_reports_503_when_database_unreachable(
    client: AsyncClient,
) -> None:
    """A dead database must surface as 'not ready', not as a 500 or a hang."""
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"


async def test_error_response_does_not_leak_internals(client: AsyncClient) -> None:
    """SECURITY_SPEC.md Section 5: no stack traces, SQL, or paths in errors."""
    response = await client.get("/api/v1/health/ready")

    raw = response.text.lower()
    for leak in ("traceback", "asyncpg", "sqlalchemy", "connect call failed", "password"):
        assert leak not in raw, f"error response leaked {leak!r}"
