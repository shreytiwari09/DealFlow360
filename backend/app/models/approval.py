"""Approval requests and their ordered steps (PRD B4).

Modelled as request -> steps rather than a single flat row because the PRD
requires "Approval steps list: Sales Manager, and Finance (only shown when
required)", and each step is decided by a different person at a different
time with its own reason. One row per decision is also what makes the audit
trail complete.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AuditMixin, Base, IdMixin
from app.models.enums import ApprovalStatus, enum_column

if TYPE_CHECKING:
    from app.models.quotation import Quotation
    from app.models.rbac import Role, User


class ApprovalRequest(IdMixin, AuditMixin, Base):
    """One trip through the approval flow for a quotation.

    A quotation can have several of these over its life: the PRD requires a
    customer counter-offer that breaches a threshold to re-enter approval, and
    that must produce a *new* request rather than reopening the decided one,
    or the history of who approved what is lost.
    """

    __tablename__ = "approval_requests"

    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Score snapshots. The live quotation may be edited after this request is
    # raised; these record what the routing decision was actually based on.
    blended_risk_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_line_excess: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    # True when routing was forced by the single-line gate rather than by the
    # score band - worth showing an approver, since a low blended score with
    # Finance involved otherwise looks like a bug.
    triggered_by_line_gate: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    status: Mapped[ApprovalStatus] = mapped_column(
        enum_column(ApprovalStatus, "approval_request_status"),
        nullable=False,
        server_default=ApprovalStatus.PENDING.value,
        index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    quotation: Mapped[Quotation] = relationship(back_populates="approval_requests")
    steps: Mapped[list[ApprovalStep]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="ApprovalStep.step_order",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("blended_risk_score >= 0", name="request_score_non_negative"),
        Index("ix_approval_requests_status_requested_at", "status", "requested_at"),
    )


class ApprovalStep(IdMixin, AuditMixin, Base):
    """A single reviewer's decision within a request.

    `required_role_id` is copied from the matching `approval_chains` row when
    the request is raised. Snapshotting it means reconfiguring the chain later
    cannot retroactively change who was supposed to approve a past deal.
    """

    __tablename__ = "approval_steps"

    request_id: Mapped[int] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_order: Mapped[int] = mapped_column(nullable=False)
    required_role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    status: Mapped[ApprovalStatus] = mapped_column(
        enum_column(ApprovalStatus, "approval_step_status"),
        nullable=False,
        server_default=ApprovalStatus.PENDING.value,
        index=True,
    )
    # RESTRICT: the person who approved a deal must remain resolvable.
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # PRD A3: "All approvals, rejections, and edits must be logged with user,
    # timestamp, and reason."
    reason: Mapped[str | None] = mapped_column(Text)

    request: Mapped[ApprovalRequest] = relationship(back_populates="steps")
    required_role: Mapped[Role] = relationship(lazy="selectin")
    # foreign_keys is required: AuditMixin adds a second FK to users
    # (created_by), so the join to users is otherwise ambiguous. `created_by`
    # is who raised the step; `actor_id` is who decided it - not the same
    # person, and conflating them would corrupt the audit trail.
    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id])

    __table_args__ = (
        UniqueConstraint("request_id", "step_order", name="uq_approval_steps_request_step"),
        CheckConstraint("step_order >= 1", name="step_order_positive"),
        # A decided step must record who decided it and when. A pending step
        # must not. This keeps half-written decisions out of the audit trail.
        CheckConstraint(
            "(status = 'pending' AND actor_id IS NULL AND decided_at IS NULL)"
            " OR (status <> 'pending' AND actor_id IS NOT NULL AND decided_at IS NOT NULL)",
            name="decided_step_has_actor_and_timestamp",
        ),
    )
