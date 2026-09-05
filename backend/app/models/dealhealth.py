"""Deal health and anomaly monitoring (PRD B9)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AuditMixin, Base, IdMixin

if TYPE_CHECKING:
    from app.models.quotation import Quotation


class DealHealthSnapshot(IdMixin, AuditMixin, Base):
    """A point-in-time health assessment of one quotation.

    Snapshots rather than live-computed flags, for two reasons: the dashboard
    must load without recomputing anomaly statistics across every deal on
    every request, and a history of snapshots is what lets a manager see that
    a deal has been stalling for a week rather than only that it is stalled
    now.

    Written by the scheduled stalled-deal task (PROJECT_CONTEXT.md
    "Background Jobs") - a plain async task, not a queue.

    NOTE - the thresholds that decide `is_stalled` and `has_discount_anomaly`
    are still an open question in PROJECT_CONTEXT.md and must be confirmed
    before the Phase 5 dashboard is built. The schema deliberately stores the
    measured values (`days_inactive`, `discount_vs_rep_average`) alongside the
    booleans, so changing a threshold later only changes how new rows are
    classified - it does not invalidate the measurements already recorded.
    """

    __tablename__ = "deal_health_snapshots"

    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Stalled deals: quotations inactive for more than a configured number of days.
    is_stalled: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    days_inactive: Mapped[int] = mapped_column(nullable=False, server_default="0")

    # Discount anomaly: a discount well above this rep's historical average.
    has_discount_anomaly: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # Signed percentage-point difference between this quotation's effective
    # discount and the owning rep's running average.
    discount_vs_rep_average: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="0"
    )

    # Delivery promise slippage.
    has_delivery_slippage: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    days_slipped: Mapped[int] = mapped_column(nullable=False, server_default="0")

    notes: Mapped[str | None] = mapped_column(Text)

    quotation: Mapped[Quotation] = relationship(back_populates="health_snapshots")

    __table_args__ = (
        CheckConstraint("days_inactive >= 0", name="days_inactive_non_negative"),
        # The dashboard query is "most recent snapshot per quotation, alerts first".
        Index(
            "ix_deal_health_snapshots_quotation_snapshot",
            "quotation_id",
            "snapshot_at",
        ),
        Index(
            "ix_deal_health_snapshots_alerts",
            "is_stalled",
            "has_discount_anomaly",
            "has_delivery_slippage",
        ),
    )
