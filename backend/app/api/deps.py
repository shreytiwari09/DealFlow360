"""Shared FastAPI dependencies.

Phase 6 adds the authentication and permission dependencies here
(`get_current_user`, `require_permission(...)`, ownership checks) so that
authorization lives in exactly one place - SECURITY_SPEC.md non-negotiable:
"Do NOT duplicate authentication/authorization logic in multiple
inconsistent places."
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

# Annotated form rather than `= Depends(...)` in the signature: it keeps the
# call out of a mutable argument default (ruff B008) and is reusable across
# every endpoint added from Phase 3 onward.
SessionDep = Annotated[AsyncSession, Depends(get_session)]

__all__ = ["SessionDep", "get_session"]
