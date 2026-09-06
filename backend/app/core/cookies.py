"""HttpOnly refresh-token cookie + its readable CSRF companion.

SECURITY_SPEC.md Section 7: "Prefer secure HttpOnly cookies over localStorage
for session/refresh credentials." The refresh token now lives ONLY here -
never in a JSON response body, never in browser-script-accessible storage.
The access token is unaffected: it stays in the response body and in the
frontend's in-memory variable, since a short-lived bearer token attached
manually via the `Authorization` header carries none of localStorage's
XSS-exfiltration risk and needs none of a cookie's CSRF mitigation.

Both cookies are scoped to `/api/v1/auth` (`Path`), not the whole API - the
browser then only ever sends them to the handful of routes that read them,
not to every other request this app makes.
"""

from __future__ import annotations

from fastapi import Request, Response

from app.core.config import settings
from app.core.csrf import compute_csrf_token

REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"
AUTH_COOKIE_PATH = "/api/v1/auth"


def set_auth_cookies(response: Response, *, refresh_token: str, jti: str) -> None:
    max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    # `Secure` requires HTTPS - forcing it on in local dev (plain http://)
    # would mean the browser silently drops the cookie and nothing works.
    # `is_production` already gates the same trade-off for the OpenAPI docs.
    secure = settings.is_production
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path=AUTH_COOKIE_PATH,
    )
    # NOT httponly - the frontend must be able to read this one to echo it
    # back as the `X-CSRF-Token` header. That is the entire point of a
    # double-submit token: it is only useful to the extent JS on THIS origin
    # can read it, which a cross-site attacker's script cannot.
    response.set_cookie(
        CSRF_COOKIE,
        compute_csrf_token(jti),
        max_age=max_age,
        httponly=False,
        samesite="lax",
        secure=secure,
        path=AUTH_COOKIE_PATH,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=AUTH_COOKIE_PATH)
    response.delete_cookie(CSRF_COOKIE, path=AUTH_COOKIE_PATH)


def get_refresh_cookie(request: Request) -> str | None:
    return request.cookies.get(REFRESH_COOKIE)


def get_presented_csrf_token(request: Request) -> str | None:
    return request.headers.get("X-CSRF-Token")
