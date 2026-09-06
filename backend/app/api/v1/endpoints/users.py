"""Admin user management and invitations.

Gated by `user.manage` ("Create users and change roles" — `app/seed.py`),
distinct from the `config.manage` gate on `admin.py`'s master data: who may
create an account and who may configure the product catalogue are different
questions, and the seed already grants them separately (Admin holds both;
Sales Manager holds only `config.manage`).

This closes the gap `PROJECT_CONTEXT.md` flagged: before this file, the only
way ANY user row came to exist — besides the seed fixtures — was the public
Sales Rep self-signup in `auth.py`. There was no way for an Admin to create a
Finance/Ops user, a Sales Manager, or a customer portal login at all. See
`services/invitation.py`'s module docstring for why this is invite-based
rather than a direct "set their password" form.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import SessionDep, require_permission
from app.core.config import settings
from app.models.audit import AuditAction
from app.models.rbac import User
from app.schemas.api import AdminUserResponse, InviteUserRequest, InviteUserResponse
from app.services import audit
from app.services.invitation import InvitationError, invite_user

router = APIRouter(prefix="/admin", tags=["admin"])

CanManageUsers = Annotated[User, Depends(require_permission("user.manage"))]


def _user_response(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role_id=user.role_id,
        role_code=user.role.code,
        role_name=user.role.name,
        customer_id=user.customer_id,
        customer_name=user.customer.name if user.customer else None,
        is_active=user.is_active,
        has_password=user.password_hash is not None,
    )


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(session: SessionDep, user: CanManageUsers) -> list[AdminUserResponse]:
    rows = (
        (
            await session.execute(
                select(User)
                .options(selectinload(User.role), selectinload(User.customer))
                .order_by(User.full_name)
            )
        )
        .scalars()
        .all()
    )
    return [_user_response(u) for u in rows]


@router.post(
    "/users/invite", response_model=InviteUserResponse, status_code=status.HTTP_201_CREATED
)
async def invite(
    request: Request, payload: InviteUserRequest, session: SessionDep, user: CanManageUsers
) -> InviteUserResponse:
    """Create the (inactive) account and return its one-time activation
    link. The link is never emailed by this project (no SMTP/email provider
    exists — see PROJECT_CONTEXT.md); the Admin copies it and sends it
    however they already reach the invitee, same as sharing a document link.
    """
    try:
        invited, raw_token, expires_at = await invite_user(
            session,
            email=payload.email,
            full_name=payload.full_name,
            role_id=payload.role_id,
            customer_id=payload.customer_id,
            invited_by=user,
        )
    except InvitationError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    await audit.record(
        session,
        action=AuditAction.USER_INVITED,
        user_id=user.id,
        resource="user",
        resource_id=invited.id,
        reason=f"invited {invited.email} as {invited.role.name}",
        request=request,
    )
    await session.commit()

    return InviteUserResponse(
        user=_user_response(invited),
        invite_url=f"{settings.FRONTEND_BASE_URL}/activate/{raw_token}",
        expires_at=expires_at,
    )
