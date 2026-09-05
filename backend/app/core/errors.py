"""Global exception handling.

SECURITY_SPEC.md Section 5: API error responses must never expose stack
traces, SQL, DB credentials, or internal paths. Details are logged
server-side; the client gets a stable, generic shape.

PLAN.md Section 14: the system should fail predictably - no silent failures.
"""

import logging
import uuid

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def _error_body(message: str, *, error_id: str | None = None) -> dict[str, object]:
    body: dict[str, object] = {"detail": message}
    if error_id:
        # Lets a user quote an id in a bug report without us leaking internals.
        body["error_id"] = error_id
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Intentional, already-safe messages raised by our own code.
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic's own errors describe the *client's* payload, not our
        # internals, so they are safe to return and genuinely useful.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Validation error", "errors": exc.errors()},
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        error_id = uuid.uuid4().hex
        logger.exception("Database error [%s] on %s %s", error_id, request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body("A database error occurred.", error_id=error_id),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        error_id = uuid.uuid4().hex
        logger.exception(
            "Unhandled error [%s] on %s %s", error_id, request.method, request.url.path
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body("Internal server error.", error_id=error_id),
        )
