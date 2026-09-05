"""Audit logging helper.

One function, used everywhere, so the audit trail cannot drift into several
inconsistent shapes. SECURITY_SPEC.md Section 10 fixes the field list; PRD A3
requires user, timestamp and reason on every approval, rejection and edit.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


def client_ip(request: Request | None) -> str | None:
    """Best-effort client address.

    X-Forwarded-For is honoured only for its first entry and only because this
    runs behind Docker's port forwarding. It is attacker-controlled, so it is
    recorded as evidence, never used for an authorization decision.
    """
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host[:45] if request.client else None


async def record(
    session: AsyncSession,
    *,
    action: str,
    status: str = "success",
    user_id: int | None = None,
    resource: str | None = None,
    resource_id: str | int | None = None,
    reason: str | None = None,
    request: Request | None = None,
) -> None:
    """Append one audit row.

    Deliberately does not commit: the audit entry belongs to the same
    transaction as the thing it describes, so a rolled-back approval cannot
    leave behind a log line claiming it happened.
    """
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=str(resource_id) if resource_id is not None else None,
            status=status,
            ip_address=client_ip(request),
            user_agent=(request.headers.get("user-agent", "")[:255] or None) if request else None,
            reason=reason,
        )
    )
