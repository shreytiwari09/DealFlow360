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

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import SessionDep, require_permission
from app.core.config import settings
from app.models.audit import AuditAction
from app.models.enums import RoleCode
from app.models.rbac import Role, User
from app.schemas.api import (
    AdminUserResponse,
    ChangeUserRoleRequest,
    InviteUserRequest,
    InviteUserResponse,
)
from app.services import audit
from app.services.invitation import InvitationError, invite_user
from app.services.mailer import MailError, send_invitation_email

router = APIRouter(prefix="/admin", tags=["admin"])

logger = logging.getLogger(__name__)

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
    """Create the (inactive) account, email its one-time activation link, and
    return that same link in the response regardless — an SMTP outage must
    never be able to silently make an invitation un-actionable, so the
    Admin's copy-link fallback always works even when `email_sent` is False.
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

    invite_url = f"{settings.FRONTEND_BASE_URL}/activate/{raw_token}"

    # Sent AFTER commit: the invitation must exist and be usable via the
    # copy-link fallback regardless of whether the send below succeeds -
    # never let an SMTP failure roll back an otherwise-successful invite.
    email_sent = True
    try:
        await send_invitation_email(
            to=invited.email,
            full_name=invited.full_name,
            invite_url=invite_url,
            role_name=invited.role.name,
        )
    except MailError as exc:
        # `email_sent: false` in the response is enough for the Admin looking
        # at THIS screen right now, but an outage affecting every invite for
        # a while needs to be visible to whoever is watching logs, not only
        # discoverable one API response at a time.
        logger.warning("Invitation email to %s failed: %s", invited.email, exc)
        email_sent = False

    return InviteUserResponse(
        user=_user_response(invited),
        invite_url=invite_url,
        expires_at=expires_at,
        email_sent=email_sent,
    )


@router.patch("/users/{user_id}/role", response_model=AdminUserResponse)
async def change_role(
    request: Request,
    user_id: int,
    payload: ChangeUserRoleRequest,
    session: SessionDep,
    user: CanManageUsers,
) -> AdminUserResponse:
    """Correct an already-provisioned user's role — promoting, demoting, or
    fixing a mis-provisioned one. This is deliberately NOT how a portal
    account gets its role: both the current and the target role must be
    internal (non-`customer`), since a customer role is meaningless without
    the `customer_id` link `POST /admin/users/invite` sets up, and this
    endpoint has no way to supply or remove that link. Provisioning a portal
    account, or a fresh internal one, goes through the invite flow above;
    this endpoint only ever changes which INTERNAL role an existing internal
    account holds.
    """
    target = (
        await session.execute(
            select(User).where(User.id == user_id).options(selectinload(User.role))
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if target.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You cannot change your own role."
        )
    if target.role.code == RoleCode.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Portal accounts' roles cannot be changed here.",
        )

    new_role = await session.get(Role, payload.role_id)
    if new_role is None:
        raise HTTPException(status_code=422, detail="Unknown role.")
    if new_role.code == RoleCode.CUSTOMER:
        raise HTTPException(
            status_code=422,
            detail="Cannot change an internal account into a portal account here.",
        )

    old_role_name = target.role.name
    target.role = new_role

    await audit.record(
        session,
        action=AuditAction.ROLE_CHANGED,
        user_id=user.id,
        resource="user",
        resource_id=target.id,
        reason=f"changed {target.email} from {old_role_name} to {new_role.name}",
        request=request,
    )
    await session.commit()

    loaded = (
        await session.execute(
            select(User)
            .where(User.id == target.id)
            .options(selectinload(User.role), selectinload(User.customer))
        )
    ).scalar_one()
    return _user_response(loaded)
