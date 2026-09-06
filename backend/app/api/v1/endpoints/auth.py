"""Authentication endpoints.

Rate limiting is applied here and not deferred: SECURITY_SPEC.md Section 11's
pre-submission checklist requires it, and PLAN.md Section 26 ranks security
basics below core workflow in a crunch — which is exactly how a "we'll harden
later" item never happens.

Public signup exists (`POST /signup`) per PROJECT_CONTEXT.md Locked Business
Rules #5 — this module's own docstring used to claim the opposite, which was
simply wrong: the rule was locked and written up early in the build, but the
endpoint implementing it was never actually added until now.

Cookie migration (SECURITY_SPEC.md Section 7): the refresh token is issued
and read ONLY as an HttpOnly cookie now (`core/cookies.py`), never in a JSON
body a script could read. `POST /refresh` and `POST /logout` therefore take
no request body at all — the cookie IS the credential — and both require a
matching `X-CSRF-Token` header (`core/csrf.py`) before touching anything,
since a cookie (unlike the `Authorization` header every other endpoint uses)
is sent by the browser automatically, which is exactly what CSRF exploits.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, SessionDep, user_permissions
from app.core.config import settings
from app.core.cookies import (
    clear_auth_cookies,
    get_presented_csrf_token,
    get_refresh_cookie,
    set_auth_cookies,
)
from app.core.csrf import csrf_token_valid
from app.core.rate_limit import limiter
from app.core.tokens import TokenError, decode_token
from app.models.audit import AuditAction
from app.schemas.api import (
    AcceptInvitationRequest,
    ChangePasswordRequest,
    CurrentUserResponse,
    InvitationPreviewResponse,
    LoginRequest,
    SignupRequest,
    TokenResponse,
)
from app.services import audit
from app.services.auth import (
    AuthError,
    PasswordChangeError,
    SignupError,
    TokenPair,
    authenticate,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.services.auth import change_password as change_password_service
from app.services.auth import signup as signup_user  # avoids shadowing the endpoint below
from app.services.invitation import InvitationError, accept_invitation, preview_invitation

router = APIRouter(prefix="/auth", tags=["auth"])

# One message for every failure mode: unknown email, wrong password, inactive
# account. Anything more specific is user enumeration.
_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect email or password.",
)
_INVALID_REQUEST = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Invalid request.",
)


def _issue_response(response: Response, tokens: TokenPair) -> TokenResponse:
    """Set the refresh+CSRF cookies from a freshly issued pair and return the
    body every login-shaped endpoint sends back. One place for this so the
    four callers (signup, login, refresh, accept-invite) cannot drift into
    setting the cookies slightly differently from each other."""
    jti = decode_token(tokens.refresh_token, expect="refresh").jti
    set_auth_cookies(response, refresh_token=tokens.refresh_token, jti=jti)
    return TokenResponse(access_token=tokens.access_token)


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def signup(
    request: Request,
    response: Response,
    payload: SignupRequest,
    session: SessionDep,
) -> TokenResponse:
    """PRD A1: "Internal users can sign up and log in with standard
    credentials." Always creates a Sales Rep (Locked Business Rules #5) —
    `SignupRequest` has no `role` field for a crafted body to smuggle a
    privilege escalation through in the first place.

    Tighter rate limit than login (5/minute vs 10/minute): account creation
    is the more expensive operation (an Argon2id hash plus a DB write, not
    just a hash comparison) and a more attractive target for abuse.

    Gated by `settings.ALLOW_PUBLIC_SIGNUP` (default on, matching this
    project's demo/dev behavior unchanged) - open self-signup handing out an
    internal workspace to anyone is right for a hackathon and wrong left on
    in production; PROJECT_CONTEXT.md's "Deferred deliberately" flagged this
    as a real gap, and this flag is the fix. Checked before the rate limiter
    would even matter, and returns the same 403 shape `require_permission`
    uses elsewhere, not a 404 - there is nothing to hide about whether this
    endpoint exists, only whether it currently accepts new accounts.
    """
    if not settings.ALLOW_PUBLIC_SIGNUP:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is currently disabled. Ask an Admin for an invite.",
        )
    try:
        user, tokens = await signup_user(
            session, email=payload.email, password=payload.password, full_name=payload.full_name
        )
    except SignupError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    await audit.record(
        session,
        action=AuditAction.USER_REGISTERED,
        user_id=user.id,
        resource="auth",
        resource_id=user.id,
        reason=f"self-registered as {user.email}",
        request=request,
    )
    await session.commit()
    return _issue_response(response, tokens)


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
    return _issue_response(response, tokens)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh(request: Request, response: Response, session: SessionDep) -> TokenResponse:
    """No request body: the refresh token comes ONLY from the HttpOnly
    cookie now. A missing cookie, a garbled one, and a CSRF-header mismatch
    all collapse to the same generic 401/403 shape as any other auth
    failure — none of the three should tell a caller which one happened.
    """
    raw_refresh = get_refresh_cookie(request)
    if raw_refresh is None:
        raise _INVALID_CREDENTIALS

    try:
        claims = decode_token(raw_refresh, expect="refresh")
    except TokenError:
        clear_auth_cookies(response)
        raise _INVALID_CREDENTIALS from None

    if not csrf_token_valid(jti=claims.jti, presented=get_presented_csrf_token(request)):
        raise _INVALID_REQUEST

    try:
        _, tokens = await rotate_refresh_token(session, raw_refresh)
    except AuthError:
        await session.commit()  # persist any family revocation from reuse detection
        clear_auth_cookies(response)
        raise _INVALID_CREDENTIALS from None

    await session.commit()
    return _issue_response(response, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: SessionDep) -> None:
    """Invalidates server-side refresh state, per SECURITY_SPEC.md Section 3.

    Unauthenticated on purpose: a client holding a cookie it wants to discard
    should always be able to, even if the access token has already expired.
    The cookies are cleared regardless of whether server-side revocation
    below actually runs — a missing/garbled cookie or a failed CSRF check
    must never leave the browser still holding what it asked to throw away.
    """
    raw_refresh = get_refresh_cookie(request)
    if raw_refresh is not None:
        try:
            claims = decode_token(raw_refresh, expect="refresh")
            if csrf_token_valid(jti=claims.jti, presented=get_presented_csrf_token(request)):
                await revoke_refresh_token(session, raw_refresh)
        except TokenError:
            pass

    clear_auth_cookies(response)
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


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    response: Response,
    payload: ChangePasswordRequest,
    session: SessionDep,
    user: CurrentUser,
) -> None:
    """Any authenticated user's own "Profile" password change — the portal's
    Profile screen is the first caller, but this is deliberately not portal-
    specific (see `services/auth.py::change_password`'s docstring).

    Same generic-failure shape as login for a wrong current password: no
    "your current password is wrong" vs. some other reason distinction that
    would matter to an attacker holding a stolen access token.
    """
    try:
        await change_password_service(
            session,
            user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except PasswordChangeError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        ) from None

    await audit.record(
        session,
        action=AuditAction.PASSWORD_CHANGED,
        user_id=user.id,
        resource="auth",
        resource_id=user.id,
        request=request,
    )
    await session.commit()


# --- Invitations -------------------------------------------------------------
#
# The activation half of `POST /admin/users/invite` (users.py). Both routes
# below are unauthenticated on purpose: the invitee has no account they can
# log in with yet — the token in the URL IS their credential, exactly like a
# password-reset link.


@router.get("/invitations/{token}", response_model=InvitationPreviewResponse)
@limiter.limit("20/minute")
async def preview_invite(
    request: Request, response: Response, token: str, session: SessionDep
) -> InvitationPreviewResponse:
    """Lets the activation page greet the invitee by name before asking them
    to set a password, without requiring a second round trip once they
    submit. Read-only: looking this up accepts nothing.

    `response` is required by slowapi, same as every other rate-limited route
    in this file — see `login()`'s docstring above."""
    try:
        preview = await preview_invitation(session, token)
    except InvitationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    return InvitationPreviewResponse(
        email=preview.email,
        full_name=preview.full_name,
        role_name=preview.role_name,
        customer_name=preview.customer_name,
        expires_at=preview.expires_at,
        already_accepted=preview.already_accepted,
        is_expired=preview.is_expired,
    )


@router.post("/invitations/{token}/accept", response_model=TokenResponse)
@limiter.limit("5/minute")
async def accept_invite(
    request: Request,
    response: Response,
    token: str,
    payload: AcceptInvitationRequest,
    session: SessionDep,
) -> TokenResponse:
    try:
        user, tokens = await accept_invitation(session, token=token, password=payload.password)
    except InvitationError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    await audit.record(
        session,
        action=AuditAction.INVITATION_ACCEPTED,
        user_id=user.id,
        resource="auth",
        resource_id=user.id,
        reason=f"activated invited account {user.email}",
        request=request,
    )
    await session.commit()
    return _issue_response(response, tokens)
