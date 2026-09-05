"""Rate limiting.

slowapi was adopted at the Phase 3 Section 0.5 checkpoint over a hand-rolled
limiter: a dict-pruned-on-read window has a genuine read-then-write race under
async, and a rate limiter is not something anyone writes tests for at 2am.

The default backend is in-memory, so "no Redis" is the normal path rather than
a workaround. If a later checkpoint adopts Redis, only the storage URI changes
— every `@limiter.limit(...)` call site stays as it is.
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _identify(request: Request) -> str:
    """Key limits by client address.

    Deliberately NOT keyed by the submitted email: that would let an attacker
    lock a real user out of their own account by hammering their address with
    wrong passwords. Rate limiting the source is the behaviour we want.
    """
    return get_remote_address(request)


limiter = Limiter(
    key_func=_identify,
    # Tests exercise login repeatedly and are not what the limiter is for.
    enabled=settings.ENVIRONMENT != "test",
    headers_enabled=True,
)
