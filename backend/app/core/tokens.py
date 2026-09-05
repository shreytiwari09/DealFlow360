"""JWT issuing and verification.

Implements the SECURITY_SPEC.md Section 9 defence table directly:

  alg:none / algorithm confusion  ->  `algorithms=` is a required argument to
                                      PyJWT's decode, so the allowlist cannot
                                      be omitted and the header's own `alg` is
                                      never trusted.
  token replay                    ->  short-lived access token + refresh
                                      rotation (see app/services/auth.py).
  payload disclosure              ->  the payload carries `sub`, `jti`, `type`,
                                      `iat`, `exp`, `iss`, `aud` and NOTHING
                                      else. No email, no name, no role string.
                                      Roles and permissions are read from the
                                      database on every request, so revoking a
                                      permission takes effect immediately
                                      rather than when the token expires.
  expired / wrong issuer/audience ->  exp, iss and aud validated on every
                                      decode, by the library.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]

# Explicit allowlist. Never derived from the incoming token's header.
ALLOWED_ALGORITHMS = [settings.JWT_ALGORITHM]


class TokenError(Exception):
    """Any token that fails verification, for any reason.

    Deliberately one exception type: the API must not tell a caller whether a
    token was expired, forged, or issued for a different audience.
    """


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    token_type: TokenType
    jti: str
    expires_at: datetime


def _create_token(
    *, user_id: int, token_type: TokenType, lifetime: timedelta
) -> tuple[str, str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + lifetime
    jti = uuid.uuid4().hex

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": token_type,
        "jti": jti,
        "iat": now,
        "exp": expires_at,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti, expires_at


def create_access_token(user_id: int) -> str:
    token, _, _ = _create_token(
        user_id=user_id,
        # ruff flags `token_type=` as a possible hardcoded password (S106).
        # It is the JWT's own "type" claim - the literal strings "access"
        # and "refresh" - not a credential.
        token_type="access",  # noqa: S106
        lifetime=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return token


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at) - the caller persists the jti."""
    return _create_token(
        user_id=user_id,
        token_type="refresh",  # noqa: S106
        lifetime=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, *, expect: TokenType) -> TokenClaims:
    """Verify a token and return its claims, or raise `TokenError`.

    `expect` matters: without it an attacker could present a long-lived
    refresh token wherever a short-lived access token is required and get the
    extended lifetime for free.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=ALLOWED_ALGORITHMS,
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={"require": ["exp", "iat", "sub", "jti", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError("token verification failed") from exc

    if payload.get("type") != expect:
        raise TokenError("wrong token type")

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenError("malformed subject") from exc

    return TokenClaims(
        user_id=user_id,
        token_type=expect,
        jti=payload["jti"],
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )
