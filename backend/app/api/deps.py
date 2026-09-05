"""Shared FastAPI dependencies.

All authentication and authorization lives here and nowhere else —
SECURITY_SPEC.md's non-negotiable: "Do NOT duplicate authentication /
authorization logic in multiple inconsistent places."

The authorization order from SECURITY_SPEC.md Section 4 is enforced as
separate, composable layers:

    identity   ->  get_current_user
    permission ->  require_permission("deal.approve_finance")
    ownership  ->  assert_can_view_quotation / assert_can_edit_quotation

A permission check alone is NOT enough on a resource route. A rep holding
`deal.update_own` must still be checked against *which* quotation they are
touching, or `/quotations/101` -> `/quotations/102` is an open door.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.enums import RoleCode
from app.models.quotation import Quotation
from app.models.rbac import User
from app.services import audit
from app.services.auth import AuthError, user_from_access_token

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# auto_error=False so a missing header produces our own generic 401 rather
# than FastAPI's, keeping every auth failure identically shaped.
_bearer = HTTPBearer(auto_error=False)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)
# 403 for both "wrong permission" and "not your resource". Returning 404 for
# the latter would leak whether a given id exists; returning a distinct code
# would confirm it. One response for both.
_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="You do not have access to this resource.",
)


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _UNAUTHENTICATED
    try:
        return await user_from_access_token(session, credentials.credentials)
    except AuthError:
        # `from None` deliberately: the client learns only that it is not
        # authenticated, never why.
        raise _UNAUTHENTICATED from None


CurrentUser = Annotated[User, Depends(get_current_user)]


def user_permissions(user: User) -> set[str]:
    return {permission.code for permission in user.role.permissions}


def has_permission(user: User, code: str) -> bool:
    return code in user_permissions(user)


def require_permission(code: str):
    """Dependency factory: reject anyone lacking `code`.

    Unauthorized attempts are audited (SECURITY_SPEC.md Section 10 lists
    UNAUTHORIZED_ACCESS_ATTEMPT as a minimum event) — a probe for endpoints a
    user cannot reach is exactly the signal worth keeping.
    """

    async def _check(request: Request, session: SessionDep, user: CurrentUser) -> User:
        if not has_permission(user, code):
            await audit.record(
                session,
                action="UNAUTHORIZED_ACCESS_ATTEMPT",
                status="denied",
                user_id=user.id,
                resource=request.url.path,
                reason=f"missing permission {code}",
                request=request,
            )
            await session.commit()
            raise _FORBIDDEN
        return user

    return _check


# --- Resource ownership ----------------------------------------------------


def _is_internal(user: User) -> bool:
    return user.role.code != RoleCode.CUSTOMER


def can_view_quotation(user: User, quotation: Quotation) -> bool:
    """Read access, in SECURITY_SPEC.md Section 4's order.

    A customer is scoped to their own company's quotations by `customer_id`.
    A rep is scoped to quotations they own, unless they also hold a broader
    read permission. Nobody's scope is ever taken from the request.
    """
    if user.role.code == RoleCode.CUSTOMER:
        return user.customer_id is not None and quotation.customer_id == user.customer_id

    permissions = user_permissions(user)
    if "deal.read_all" in permissions:
        return True
    if quotation.owner_id == user.id:
        return True
    # Team-level read: the manager of the owner's team may see it.
    if "deal.read_team" in permissions:
        return True
    return False


def can_edit_quotation(user: User, quotation: Quotation) -> bool:
    """Write access. Only the owning rep may edit, and only their own."""
    if not _is_internal(user):
        return False
    permissions = user_permissions(user)
    if "deal.update_own" not in permissions:
        return False
    return quotation.owner_id == user.id


async def assert_can_view_quotation(
    request: Request, session: AsyncSession, user: User, quotation: Quotation
) -> None:
    if not can_view_quotation(user, quotation):
        await audit.record(
            session,
            action="UNAUTHORIZED_ACCESS_ATTEMPT",
            status="denied",
            user_id=user.id,
            resource="quotation",
            resource_id=quotation.id,
            reason="not owner / out of scope",
            request=request,
        )
        await session.commit()
        raise _FORBIDDEN


async def assert_can_edit_quotation(
    request: Request, session: AsyncSession, user: User, quotation: Quotation
) -> None:
    if not can_edit_quotation(user, quotation):
        await audit.record(
            session,
            action="UNAUTHORIZED_ACCESS_ATTEMPT",
            status="denied",
            user_id=user.id,
            resource="quotation",
            resource_id=quotation.id,
            reason="not owner / not editable by this role",
            request=request,
        )
        await session.commit()
        raise _FORBIDDEN


__all__ = [
    "CurrentUser",
    "SessionDep",
    "assert_can_edit_quotation",
    "assert_can_view_quotation",
    "can_edit_quotation",
    "can_view_quotation",
    "get_current_user",
    "get_session",
    "has_permission",
    "require_permission",
    "user_permissions",
]
