"""Quotations and their lines - the centre of the domain."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AuditMixin, Base, IdMixin
from app.models.enums import ItemType, QuotationStatus, enum_column

if TYPE_CHECKING:
    from app.models.approval import ApprovalRequest
    from app.models.billing import BillingSchedule, Subscription, SubscriptionPlan
    from app.models.catalog import Product, ProductVariant
    from app.models.customer import Customer
    from app.models.dealhealth import DealHealthSnapshot
    from app.models.inventory import Fulfillment
    from app.models.rbac import User


class Quotation(IdMixin, AuditMixin, Base):
    __tablename__ = "quotations"

    quote_number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # The owning sales rep. This column is the anchor for the rep-side
    # ownership check that stops one rep editing another's quote by changing
    # the id in the URL (SECURITY_SPEC.md Section 4, IDOR/BOLA).
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    status: Mapped[QuotationStatus] = mapped_column(
        enum_column(QuotationStatus, "quotation_status"),
        nullable=False,
        server_default=QuotationStatus.DRAFT.value,
        index=True,
    )

    # --- Monetary totals ---------------------------------------------------
    # Denormalised from the lines on purpose: a quotation is a financial
    # document, and recomputing historical totals from current master data is
    # how ERP systems produce numbers that disagree with what was signed.
    subtotal_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    # Live margin indicator (PRD B3), updated as lines change.
    margin_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    margin_percent: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="0"
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")

    # --- Discount risk -----------------------------------------------------
    # See PROJECT_CONTEXT.md Locked Business Rules #1 for the formula.
    # Persisted rather than computed on read so that an approver sees the
    # score the routing decision was actually made on, even if a ceiling is
    # reconfigured afterwards.
    blended_risk_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="0"
    )
    # Drives the single-line Finance gate (max(line_excess) > 15). Stored
    # alongside the score so the gate decision is reproducible from the row.
    max_line_excess: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="0"
    )
    requires_finance_approval: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    valid_until: Mapped[date | None] = mapped_column()
    # Feeds stalled-deal detection on the deal health dashboard (PRD B9).
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    # Optimistic locking. PLAN.md Section 14 calls out two managers approving
    # the same quote at once; SQLAlchemy raises StaleDataError when the
    # version read does not match the version written, turning a silent
    # last-write-wins into a visible conflict.
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")

    customer: Mapped[Customer] = relationship(back_populates="quotations")
    owner: Mapped[User] = relationship(back_populates="owned_quotations", foreign_keys=[owner_id])
    lines: Mapped[list[QuotationLine]] = relationship(
        back_populates="quotation",
        cascade="all, delete-orphan",
        order_by="QuotationLine.line_number",
    )
    approval_requests: Mapped[list[ApprovalRequest]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )
    fulfillments: Mapped[list[Fulfillment]] = relationship(back_populates="quotation")
    billing_schedules: Mapped[list[BillingSchedule]] = relationship(back_populates="quotation")
    health_snapshots: Mapped[list[DealHealthSnapshot]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="total_amount_non_negative"),
        CheckConstraint("blended_risk_score >= 0", name="blended_risk_score_non_negative"),
        CheckConstraint("max_line_excess >= 0", name="max_line_excess_non_negative"),
        # The pipeline board and the approval queue both filter this way.
        Index("ix_quotations_status_created_at", "status", "created_at"),
        Index("ix_quotations_owner_id_status", "owner_id", "status"),
        Index("ix_quotations_customer_id_status", "customer_id", "status"),
    )


class QuotationLine(IdMixin, AuditMixin, Base):
    """One product line on a quotation.

    Prices, costs and the applicable discount ceiling are all *snapshotted*
    onto the line at the time of quoting. This is deliberate and is standard
    ERP practice: master data changes, and an approved quotation must remain
    reproducible. It also means an auditor can answer "what was the policy
    when this was approved?" - which is exactly what `allowed_discount_percent`
    records.
    """

    __tablename__ = "quotation_lines"

    # CASCADE: a line has no independent existence. Quotations are cancelled
    # rather than deleted in normal operation, so this fires only on cleanup.
    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(nullable=False)

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="RESTRICT"), index=True
    )

    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)

    # --- Snapshots taken at quoting time -----------------------------------
    unit_list_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unit_cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0"
    )
    # The ceiling that applied to this line, from discount_tiers.
    allowed_discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0"
    )
    # max(0, discount_percent - allowed_discount_percent), in percentage
    # points. Persisted so the approval screen can show a per-line breakdown
    # of *why* the quotation scored what it did, rather than one opaque number.
    line_excess_points: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="0"
    )

    # --- Line totals -------------------------------------------------------
    line_subtotal: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    line_discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    line_tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")

    # --- Hybrid billing ----------------------------------------------------
    # One-time and subscription lines coexist on the same quotation; this is
    # what the PRD means by a single order mixing hardware and subscriptions.
    line_type: Mapped[ItemType] = mapped_column(
        enum_column(ItemType, "quotation_line_item_type"),
        nullable=False,
        server_default=ItemType.ONE_TIME.value,
        index=True,
    )
    subscription_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"), index=True
    )

    # True when the line was added from the upsell/cross-sell panel. Lets the
    # demo and reporting show that the suggestion engine actually influenced
    # the deal (PRD B5).
    added_from_upsell: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    quotation: Mapped[Quotation] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()
    variant: Mapped[ProductVariant | None] = relationship()
    subscription_plan: Mapped[SubscriptionPlan | None] = relationship()
    subscription: Mapped[Subscription | None] = relationship(
        back_populates="quotation_line", uselist=False
    )

    __table_args__ = (
        UniqueConstraint(
            "quotation_id", "line_number", name="uq_quotation_lines_quotation_line_no"
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "discount_percent >= 0 AND discount_percent <= 100",
            name="discount_percentage_range",
        ),
        CheckConstraint(
            "allowed_discount_percent >= 0 AND allowed_discount_percent <= 100",
            name="allowed_discount_percentage_range",
        ),
        CheckConstraint("line_excess_points >= 0", name="line_excess_non_negative"),
        CheckConstraint("unit_list_price >= 0", name="unit_list_price_non_negative"),
        CheckConstraint("unit_cost_price >= 0", name="unit_cost_price_non_negative"),
        # A subscription line without a plan cannot generate a billing
        # schedule, and a one-time line with a plan is nonsense. Unlike the
        # users/roles invariant, both columns live on this table, so the
        # database can enforce it directly.
        CheckConstraint(
            "(line_type = 'subscription' AND subscription_plan_id IS NOT NULL)"
            " OR (line_type = 'one_time' AND subscription_plan_id IS NULL)",
            name="subscription_line_requires_plan",
        ),
    )
