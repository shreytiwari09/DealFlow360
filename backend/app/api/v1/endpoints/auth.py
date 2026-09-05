"""Authentication endpoints.

Rate limiting is applied here and not deferred: SECURITY_SPEC.md Section 11's
pre-submission checklist requires it, and PLAN.md Section 26 ranks security
basics below core workflow in a crunch — which is exactly how a "we'll harden
later" item never happens.

There is deliberately NO signup endpoint. See PROJECT_CONTEXT.md Locked
Business Rules #5.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, SessionDep, user_permissions
from app.core.rate_limit import limiter
from app.models.audit import AuditAction
from app.schemas.api import (
    CurrentUserResponse,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from app.services import audit
from app.services.auth import (
    AuthError,
    authenticate,
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# One message for every failure mode: unknown email, wrong password, inactive
# account. Anything more specific is user enumeration.
_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect email or password.",
)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    session: SessionDep,
) -> TokenResponse:
    """`response` is required by slowapi: with headers_enabled it injects
    X-RateLimit-* and Retry-After, and it needs a Response object to write
    them onto. Removing it makes every call to this endpoint 500."""
    try:
        user, tokens = await authenticate(session, payload.email, payload.password)
    except AuthError:
        # The attempt is logged with the email that was tried, which is
        # evidence, not a secret. The password never is.
        await audit.record(
            session,
            action=AuditAction.LOGIN_FAILED,
            status="failure",
            resource="auth",
            reason=f"failed login for {payload.email.strip().lower()[:120]}",
            request=request,
        )
        await session.commit()
        raise _INVALID_CREDENTIALS from None

    await audit.record(
        session,
        action=AuditAction.LOGIN_SUCCESS,
        user_id=user.id,
        resource="auth",
        resource_id=user.id,
        request=request,
    )
    await session.commit()
    return TokenResponse(**tokens.__dict__)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest,
    session: SessionDep,
) -> TokenResponse:
    try:
        _, tokens = await rotate_refresh_token(session, payload.refresh_token)
    except AuthError:
        await session.commit()  # persist any family revocation from reuse detection
        raise _INVALID_CREDENTIALS from None

    await session.commit()
    return TokenResponse(**tokens.__dict__)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, payload: RefreshRequest, session: SessionDep) -> None:
    """Invalidates server-side refresh state, per SECURITY_SPEC.md Section 3.

    Unauthenticated on purpose: a client holding a token it wants to discard
    should always be able to, even if the access token has already expired.
    """
    await revoke_refresh_token(session, payload.refresh_token)
    await audit.record(session, action=AuditAction.LOGOUT, resource="auth", request=request)
    await session.commit()


@router.get("/me", response_model=CurrentUserResponse)
async def me(user: CurrentUser) -> CurrentUserResponse:
    """Identity plus the permission list the UI uses to hide controls.

    Returning permissions is a convenience for the frontend, never a grant:
    every endpoint re-checks server-side regardless of what the client was
    told (SECURITY_SPEC.md — frontend controls are UX only).
    """
    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.code,
        permissions=sorted(user_permissions(user)),
        customer_id=user.customer_id,
        customer_name=user.customer.name if user.customer else None,
    )
