"""Audit trail.

Field list is taken directly from SECURITY_SPEC.md Section 10. This serves two
masters at once: it is a security control, and it is an explicit PRD
requirement (A3: "All approvals, rejections, and edits must be logged with
user, timestamp, and reason").
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin

if TYPE_CHECKING:
    from app.models.rbac import User


class AuditAction:
    """Canonical action codes.

    A class of constants rather than an enum: SECURITY_SPEC.md Section 10
    gives a *minimum* set, and new actions get added routinely as features
    land. A plain VARCHAR column plus these constants avoids a schema
    migration every time something new becomes worth logging, while keeping
    the strings in one place so they cannot drift into typos.
    """

    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    MFA_FAILED = "MFA_FAILED"
    QUOTATION_CREATED = "QUOTATION_CREATED"
    QUOTATION_UPDATED = "QUOTATION_UPDATED"
    QUOTATION_STATUS_CHANGED = "QUOTATION_STATUS_CHANGED"
    DISCOUNT_APPROVAL_REQUESTED = "DISCOUNT_APPROVAL_REQUESTED"
    DISCOUNT_APPROVED = "DISCOUNT_APPROVED"
    DISCOUNT_REJECTED = "DISCOUNT_REJECTED"
    DISCOUNT_RETURNED_FOR_REVISION = "DISCOUNT_RETURNED_FOR_REVISION"
    PORTAL_COUNTER_OFFER = "PORTAL_COUNTER_OFFER"
    FULFILLMENT_SPLIT_SUGGESTED = "FULFILLMENT_SPLIT_SUGGESTED"
    FULFILLMENT_SPLIT_ACCEPTED = "FULFILLMENT_SPLIT_ACCEPTED"
    FULFILLMENT_SPLIT_OVERRIDDEN = "FULFILLMENT_SPLIT_OVERRIDDEN"
    FULFILLMENT_BACKORDER_CONSOLIDATED = "FULFILLMENT_BACKORDER_CONSOLIDATED"
    SUBSCRIPTION_MODIFIED = "SUBSCRIPTION_MODIFIED"
    SUBSCRIPTION_CANCELLED = "SUBSCRIPTION_CANCELLED"
    PAYMENT_RECORDED = "PAYMENT_RECORDED"
    DEAL_NUDGE_SENT = "DEAL_NUDGE_SENT"
    ROLE_CHANGED = "ROLE_CHANGED"
    UNAUTHORIZED_ACCESS_ATTEMPT = "UNAUTHORIZED_ACCESS_ATTEMPT"


class AuditLog(IdMixin, Base):
    """An append-only record of a security- or business-significant event.

    Intentionally NOT using AuditMixin: an audit row has no `updated_at`
    because it is never updated, and no `created_by` because `user_id` already
    names the actor. Adding a mutable timestamp to an audit table invites
    exactly the tampering the table exists to detect.
    """

    __tablename__ = "audit_logs"

    # Nullable and RESTRICT-on-delete. Nullable because a failed login may not
    # resolve to a real user, and we must still record the attempt.
    # RESTRICT because deleting a user must never erase their audit history -
    # SECURITY_SPEC.md Section 6 warns specifically against cascade-deleting
    # audit records.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )

    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    resource: Mapped[str | None] = mapped_column(String(60), index=True)
    # String, not int: resources are not all integer-keyed, and an audit row
    # must survive its target being removed.
    resource_id: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # Wide enough for IPv6, and for an IPv4-mapped IPv6 address.
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    # The "reason" half of the PRD's user/timestamp/reason requirement.
    reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    user: Mapped[User | None] = relationship()

    __table_args__ = (
        # "What happened to this quotation?" - the audit view's main query.
        Index("ix_audit_logs_resource_resource_id", "resource", "resource_id"),
        # "What has this user been doing?", newest first.
        Index("ix_audit_logs_user_id_created_at", "user_id", "created_at"),
    )
