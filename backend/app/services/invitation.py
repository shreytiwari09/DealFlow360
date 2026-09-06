"""Admin-provisioned account invitations.

PRD A1 ("After login, internal users can access backend configuration") and
`Locked Business Rules #5` together say: internal users may self-register
(`services/auth.py::signup`), but a portal account must always be created by
an Admin/Sales Rep and linked to a specific `customer_id` - a stranger must
never be able to self-select which company they represent. The same
Admin-creates-first shape is used here for internal roles too (Sales
Manager, Finance/Ops), which doubles as the answer to the previously-deferred
"promote a self-registered Sales Rep" gap: an Admin directly provisioning the
right role from the start is the more realistic ERP pattern, not a promotion
endpoint bolted on afterwards.

Nobody but the invitee ever handles the invitee's password - the same reason
a password-reset flow works this way. The raw token is generated once here,
returned to the caller (the Admin), and never stored; only its SHA-256 digest
lives in the database, matching `RefreshToken.token_hash`.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import hash_password
from app.models.auth import UserInvitation
from app.models.customer import Customer
from app.models.enums import RoleCode
from app.models.rbac import Role, User
from app.services.auth import TokenPair, issue_token_pair

# A little over a week: long enough that a customer who is travelling or
# whose contact checks email irregularly is not locked out, short enough
# that a stale, un-actioned invite does not sit valid indefinitely. No
# PRD-specified value exists for this, unlike the deal-health thresholds -
# it is an implementation default, not a business rule, so it was not put to
# the user as a stop-and-ask question.
INVITATION_TTL_DAYS = 7

_TOKEN_BYTES = 32


class InvitationError(Exception):
    """Invitation could not be created or accepted. Carries a detail, like
    `SignupError` - the same reasoning applies: "this email already has an
    account" or "this link has expired" is normal UX, not user enumeration
    of *login* credentials."""


@dataclass(frozen=True)
class InvitationPreview:
    email: str
    full_name: str
    role_name: str
    customer_name: str | None
    expires_at: datetime
    already_accepted: bool
    is_expired: bool


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def invite_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str,
    role_id: int,
    customer_id: int | None,
    invited_by: User,
) -> tuple[User, str, datetime]:
    """Create the (inactive, passwordless) account and its invitation.

    Returns the raw token — this is the ONE moment it exists outside the
    invitee's own inbox/clipboard, exactly like a password-reset token.
    """
    normalised = email.strip().lower()
    existing = (
        await session.execute(select(User).where(User.email == normalised))
    ).scalar_one_or_none()
    if existing is not None:
        raise InvitationError("An account with this email already exists.")

    role = await session.get(Role, role_id)
    if role is None:
        raise InvitationError("Unknown role.")

    customer: Customer | None = None
    if role.code == RoleCode.CUSTOMER:
        if customer_id is None:
            raise InvitationError("A portal account must be linked to a customer.")
        customer = await session.get(Customer, customer_id)
        if customer is None or not customer.is_active:
            raise InvitationError("Unknown or archived customer.")
    elif customer_id is not None:
        # Mirrors the invariant `models/rbac.py::User` documents at the
        # column level: role is customer <=> customer_id is set. An internal
        # role with a customer attached would silently scope that user's
        # portal-side ownership checks to a company they have no business in.
        raise InvitationError("Only a portal (customer) account may be linked to a customer.")

    user = User(
        email=normalised,
        password_hash=None,
        full_name=full_name.strip(),
        role_id=role.id,
        customer_id=customer.id if customer else None,
        is_active=False,
        created_by=invited_by.id,
    )
    session.add(user)
    await session.flush()

    raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
    expires_at = datetime.now(UTC) + timedelta(days=INVITATION_TTL_DAYS)
    invitation = UserInvitation(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        invited_by_id=invited_by.id,
        expires_at=expires_at,
    )
    session.add(invitation)
    await session.flush()

    loaded = (
        await session.execute(
            select(User)
            .where(User.id == user.id)
            .options(selectinload(User.role), selectinload(User.customer))
        )
    ).scalar_one()
    return loaded, raw_token, expires_at


async def _load_invitation(session: AsyncSession, token: str) -> UserInvitation | None:
    return (
        await session.execute(
            select(UserInvitation)
            .where(UserInvitation.token_hash == _hash_token(token))
            .options(
                selectinload(UserInvitation.user).selectinload(User.role),
                selectinload(UserInvitation.user).selectinload(User.customer),
            )
        )
    ).scalar_one_or_none()


async def preview_invitation(session: AsyncSession, token: str) -> InvitationPreview:
    """Read-only lookup for the activation page, shown BEFORE the invitee has
    proven anything — so it must never leak more than "who is this link for",
    and must fail the same generic way for a garbled, already-used, or
    genuinely nonexistent token."""
    invitation = await _load_invitation(session, token)
    if invitation is None:
        raise InvitationError("This invitation link is invalid.")

    now = datetime.now(UTC)
    return InvitationPreview(
        email=invitation.user.email,
        full_name=invitation.user.full_name,
        role_name=invitation.user.role.name,
        customer_name=invitation.user.customer.name if invitation.user.customer else None,
        expires_at=invitation.expires_at,
        already_accepted=invitation.accepted_at is not None,
        is_expired=invitation.expires_at <= now,
    )


async def accept_invitation(
    session: AsyncSession, *, token: str, password: str
) -> tuple[User, TokenPair]:
    """The invitee's one action: prove they hold the link, choose a password,
    and (like `signup`) be logged straight in — there is no reason to make
    someone who just proved ownership of the link log in a second time."""
    invitation = await _load_invitation(session, token)
    if invitation is None:
        raise InvitationError("This invitation link is invalid.")

    now = datetime.now(UTC)
    if invitation.accepted_at is not None:
        raise InvitationError("This invitation has already been used.")
    if invitation.expires_at <= now:
        raise InvitationError("This invitation has expired. Ask an admin to send a new one.")

    user = invitation.user
    user.password_hash = hash_password(password)
    user.is_active = True
    invitation.accepted_at = now
    await session.flush()

    return user, await issue_token_pair(session, user)
