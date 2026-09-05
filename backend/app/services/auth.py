"""Authentication service: login, refresh rotation, logout.

Every failure path returns the same generic outcome to the caller. The caller
never learns whether an email exists, whether the password was wrong, or
whether the account is inactive — SECURITY_SPEC.md Section 3 forbids user
enumeration.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import hash_password, needs_rehash, verify_password
from app.core.tokens import TokenError, create_access_token, create_refresh_token, decode_token
from app.models.auth import RefreshToken
from app.models.enums import RoleCode
from app.models.rbac import Role, User


class AuthError(Exception):
    """Authentication failed. Intentionally carries no detail."""


class SignupError(Exception):
    """Registration could not proceed. Unlike `AuthError`, this DOES carry a
    detail — a duplicate-email conflict on signup is normal, expected UX
    (SECURITY_SPEC.md's user-enumeration concern is about *login* telling an
    attacker which emails have accounts; a signup form telling the person
    who just typed their own email that it's already registered is not the
    same threat model, and every real registration form does this)."""


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


def _hash_jti(jti: str) -> str:
    """Store only a digest of the token id, never the id itself."""
    return hashlib.sha256(jti.encode()).hexdigest()


# Every user load needs the role (for permissions) AND the customer link.
#
# `User.customer` looks harmless because it is None for internal users, and a
# many-to-one with a NULL foreign key resolves to None without emitting SQL.
# For a PORTAL user it is populated, so touching it lazy-loads inside async and
# raises MissingGreenlet - meaning /auth/me 500s for customers only. Eager
# loading both here is what keeps that from being a role-specific landmine.
_USER_LOADS = (
    selectinload(User.role).selectinload(Role.permissions),
    selectinload(User.customer),
)


async def _load_user(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id).options(*_USER_LOADS))
    return result.scalar_one_or_none()


async def _issue_pair(session: AsyncSession, user: User) -> TokenPair:
    refresh_token, jti, expires_at = create_refresh_token(user.id)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash_jti(jti),
            expires_at=expires_at,
        )
    )
    await session.flush()
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=refresh_token,
    )


async def signup(
    session: AsyncSession, *, email: str, password: str, full_name: str
) -> tuple[User, TokenPair]:
    """PRD A1 ("Internal users can sign up and log in") and Locked Business
    Rules #5: always creates a Sales Rep, never a portal account (there is no
    `customer_id` to set here — portal accounts remain Admin-created only,
    which is the correct outcome: self-signup must never be able to attach
    itself to an existing customer's quotations).

    Auto-issues a token pair on success, matching `authenticate()`'s shape,
    so "sign up" and "log in" are one action from the caller's side — the PRD
    lists them as alternatives ("signs up (first time) or logs in"), not as
    two separate steps a new user has to perform back to back.
    """
    normalised = email.strip().lower()
    existing = (
        await session.execute(select(User).where(User.email == normalised))
    ).scalar_one_or_none()
    if existing is not None:
        raise SignupError("An account with this email already exists.")

    role = (await session.execute(select(Role).where(Role.code == RoleCode.SALES_REP))).scalar_one()

    user = User(
        email=normalised,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
        role_id=role.id,
    )
    session.add(user)
    await session.flush()

    loaded = await _load_user(session, user.id)
    assert loaded is not None  # just inserted in this same transaction
    return loaded, await _issue_pair(session, loaded)


async def authenticate(session: AsyncSession, email: str, password: str) -> tuple[User, TokenPair]:
    """Verify credentials and issue a token pair.

    The password is verified even when no user matches, against a throwaway
    hash. Skipping that would make a missing account return measurably faster
    than a wrong password, which is user enumeration through a timing side
    channel.
    """
    normalised = email.strip().lower()
    result = await session.execute(
        select(User).where(User.email == normalised).options(*_USER_LOADS)
    )
    user = result.scalar_one_or_none()

    if user is None:
        verify_password(password, hash_password("timing-equalisation-only"))
        raise AuthError

    if not verify_password(password, user.password_hash):
        raise AuthError

    if not user.is_active:
        raise AuthError

    # The one moment the plaintext is available, so the one moment a stored
    # hash using weaker parameters can be upgraded.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    return user, await _issue_pair(session, user)


async def rotate_refresh_token(session: AsyncSession, token: str) -> tuple[User, TokenPair]:
    """Exchange a refresh token for a new pair, revoking the old one.

    Reuse detection: presenting an already-revoked token means it was either
    replayed by an attacker or replayed by a confused client, and there is no
    way to tell which. Every token for that user is revoked, forcing a fresh
    login — the standard, deliberately blunt response.
    """
    try:
        claims = decode_token(token, expect="refresh")
    except TokenError as exc:
        raise AuthError from exc

    token_hash = _hash_jti(claims.jti)
    stored = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    ).scalar_one_or_none()

    if stored is None:
        raise AuthError

    now = datetime.now(UTC)

    if stored.revoked_at is not None:
        await _revoke_all_for_user(session, stored.user_id, now)
        raise AuthError

    if stored.expires_at <= now:
        raise AuthError

    user = await _load_user(session, stored.user_id)
    if user is None or not user.is_active:
        raise AuthError

    pair = await _issue_pair(session, user)
    stored.revoked_at = now
    # Record the successor so the chain is auditable after the fact.
    stored.replaced_by_hash = _hash_jti(decode_token(pair.refresh_token, expect="refresh").jti)
    await session.flush()
    return user, pair


async def revoke_refresh_token(session: AsyncSession, token: str) -> None:
    """Logout. Best-effort: an invalid token is not an error to the caller."""
    try:
        claims = decode_token(token, expect="refresh")
    except TokenError:
        return

    stored = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == _hash_jti(claims.jti))
        )
    ).scalar_one_or_none()

    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
        await session.flush()


async def _revoke_all_for_user(session: AsyncSession, user_id: int, when: datetime) -> None:
    rows = (
        await session.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
            )
        )
    ).scalars()
    for row in rows:
        row.revoked_at = when
    await session.flush()


async def user_from_access_token(session: AsyncSession, token: str) -> User:
    try:
        claims = decode_token(token, expect="access")
    except TokenError as exc:
        raise AuthError from exc

    user = await _load_user(session, claims.user_id)
    if user is None or not user.is_active:
        raise AuthError
    return user
