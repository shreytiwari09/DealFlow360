"""CSRF protection for the two cookie-authenticated endpoints.

Every OTHER endpoint in this app is authenticated by the `Authorization`
header, which a cross-site request cannot forge - a browser only attaches a
credential to a request AUTOMATICALLY for cookies, never for a header a
script chose not to set. CSRF therefore only matters for `POST /auth/refresh`
and `POST /auth/logout`, the two routes that read the HttpOnly
`refresh_token` cookie (`core/cookies.py`).

Signed double-submit, not a naive one: the CSRF token is
`HMAC(JWT_SECRET_KEY, refresh-token jti)`, never a value chosen or stored
independently of the refresh token it accompanies. A plain double-submit
(two unrelated random cookies, compared to each other) is defeated by ANY
bug that lets an attacker set their OWN matching pair of cookies on the
victim's browser - a related subdomain, an unrelated XSS elsewhere. Tying the
CSRF value to the refresh token's own `jti` means an attacker would need to
already know that jti - which requires already having compromised the
HttpOnly cookie, at which point CSRF is no longer the weakest link anyway.
"""

from __future__ import annotations

import hashlib
import hmac

from app.core.config import settings


def compute_csrf_token(jti: str) -> str:
    return hmac.new(settings.JWT_SECRET_KEY.encode(), jti.encode(), hashlib.sha256).hexdigest()


def csrf_token_valid(*, jti: str, presented: str | None) -> bool:
    """`hmac.compare_digest` - a plain `==` would leak the correct token one
    byte at a time through response-timing, over enough requests."""
    if not presented:
        return False
    return hmac.compare_digest(compute_csrf_token(jti), presented)
