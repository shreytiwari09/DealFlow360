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
from app.models.rbac import Role, User


class AuthError(Exception):
    """Authentication failed. Intentionally carries no detail."""


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
