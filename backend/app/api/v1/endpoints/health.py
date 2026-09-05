"""Health endpoints.

SECURITY_SPEC.md Section 2 requires a health-check endpoint so local dev
"just works" and so Docker Compose can gate service startup ordering.
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import SessionDep
from app.core.config import settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness: the process is up and serving. Does not touch the database."""
    return HealthResponse(
        status="ok",
        environment=settings.ENVIRONMENT,
        database="not_checked",
    )


@router.get("/health/ready", response_model=HealthResponse)
async def readiness(session: SessionDep) -> JSONResponse:
    """Readiness: the process is up AND the database answers.

    Returns 503 rather than 500 when the database is unreachable, so an
    orchestrator can distinguish "not ready yet" from "broken".
    """
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        # Deliberately no exception detail in the response body:
        # SECURITY_SPEC.md Section 5 - never leak DB errors to clients.
        body = HealthResponse(
            status="degraded",
            environment=settings.ENVIRONMENT,
            database="unavailable",
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=body.model_dump(),
        )

    body = HealthResponse(
        status="ok",
        environment=settings.ENVIRONMENT,
        database="ok",
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=body.model_dump())
