"""HttpOnly refresh-token cookie + its readable CSRF companion.

SECURITY_SPEC.md Section 7: "Prefer secure HttpOnly cookies over localStorage
for session/refresh credentials." The refresh token now lives ONLY here -
never in a JSON response body, never in browser-script-accessible storage.
The access token is unaffected: it stays in the response body and in the
frontend's in-memory variable, since a short-lived bearer token attached
manually via the `Authorization` header carries none of localStorage's
XSS-exfiltration risk and needs none of a cookie's CSRF mitigation.

The two cookies are deliberately scoped to DIFFERENT paths, not the same
one - this was a real bug caught by driving the app in a real browser
(neither pytest nor a script-level HTTP client exercises `document.cookie`,
so nothing before that caught it):

  * `refresh_token` (`Path=/api/v1/auth`) only needs to be attached
    automatically by the browser to REQUESTS whose target URL is under that
    path - which every fetch to `/auth/refresh` and `/auth/logout` is,
    regardless of which frontend route the call happens to originate from.
    Narrow on purpose: the browser then never sends it anywhere else.

  * `csrf_token` (`Path=/`) has a different consumer: the frontend's own
    `document.cookie`, read from whatever SPA route the user is actually
    on - `/dashboard`, `/quotations/12`, anything. Cookie path-matching for
    `document.cookie` is evaluated against the CURRENT PAGE's path, not the
    path of some future request, so scoping this cookie to `/api/v1/auth`
    (a path the frontend's own pages never live under) made it invisible to
    `document.cookie` everywhere except literally the auth pages themselves
    - which is nowhere a real user's browser tab ever is. The practical
    effect was that a reloaded tab could never resume its session at all:
    `getCsrfToken()` always came back empty, the resulting `/auth/refresh`
    call always failed CSRF validation, and the user was bounced to
    `/login` despite holding a perfectly valid refresh cookie. `Path=/` is
    not a materially wider security exposure - the value is already
    designed to be freely JS-readable, so widening WHERE it is readable
    changes nothing about what an attacker can do with it.

`SameSite` is also environment-dependent, for a related but distinct reason.
Local dev has frontend (:5173) and backend (:8000) on the same host
("localhost"), which browsers treat as the same SITE regardless of port -
`Lax` cookies flow between them with no extra config. A split-platform
production deploy (frontend on Vercel, backend on Render) puts them on two
entirely different registrable domains - genuinely cross-site, not just
cross-origin - and `Lax` cookies are simply never sent on a cross-site
fetch/XHR at all, no matter what CORS says. `SameSite=None` is required for
that topology, and browsers refuse to honor `None` without `Secure` - hence
both being tied to the same `is_production` flag below. This does NOT weaken
CSRF protection here: the actual CSRF defense is the signed double-submit
token in `core/csrf.py` (a value a cross-site attacker's page cannot read,
regardless of SameSite), not `SameSite` itself - `SameSite=Lax` in dev was
always a second, redundant layer on top of that, never the only one.
"""

from __future__ import annotations

from fastapi import Request, Response

from app.core.config import settings
from app.core.csrf import compute_csrf_token

REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"
CSRF_COOKIE_PATH = "/"


def set_auth_cookies(response: Response, *, refresh_token: str, jti: str) -> None:
    max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    # `Secure` requires HTTPS - forcing it on in local dev (plain http://)
    # would mean the browser silently drops the cookie and nothing works.
    # `is_production` already gates the same trade-off for the OpenAPI docs.
    # `SameSite=None` requires `Secure` too (browsers reject the pairing
    # otherwise), which is why both are the same expression - see the
    # module docstring for why production needs `None` at all.
    secure = settings.is_production
    samesite = "none" if settings.is_production else "lax"
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=max_age,
        httponly=True,
        samesite=samesite,
        secure=secure,
        path=REFRESH_COOKIE_PATH,
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
        samesite=samesite,
        secure=secure,
        path=CSRF_COOKIE_PATH,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    response.delete_cookie(CSRF_COOKIE, path=CSRF_COOKIE_PATH)


def get_refresh_cookie(request: Request) -> str | None:
    return request.cookies.get(REFRESH_COOKIE)


def get_presented_csrf_token(request: Request) -> str | None:
    return request.headers.get("X-CSRF-Token")
