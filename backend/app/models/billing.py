"""Hybrid billing: one-time lines and recurring subscriptions on one order.

PRD A5 and B7. The key structural idea is that `billing_schedules` holds BOTH
one-time and recurring entries for a quotation, which is what lets the billing
screen show them "separately within the same order" while still reconciling to
one total.
"""

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
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import ArchivableMixin, AuditMixin, Base, IdMixin
from app.models.enums import (
    BillingInterval,
    BillingScheduleStatus,
    BillingScheduleType,
    PaymentMethod,
    RefundPolicy,
    SubscriptionStatus,
    enum_column,
)

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.quotation import Quotation, QuotationLine


class SubscriptionPlan(IdMixin, AuditMixin, ArchivableMixin, Base):
    """PRD A5: recurring plans attachable to products or services."""

    __tablename__ = "subscription_plans"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    billing_interval: Mapped[BillingInterval] = mapped_column(
        enum_column(BillingInterval, "billing_interval"), nullable=False
    )
    # Lets "every 2 months" be expressed without inventing a new interval.
    interval_count: Mapped[int] = mapped_column(nullable=False, server_default="1")
    unit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # PRD A5: "Configure proration rules for mid cycle quantity or plan
    # changes" and "cancellation and partial refund rules".
    proration_enabled: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    refund_policy: Mapped[RefundPolicy] = mapped_column(
        enum_column(RefundPolicy, "refund_policy"),
        nullable=False,
        server_default=RefundPolicy.PRORATED.value,
    )
    cancellation_notice_days: Mapped[int] = mapped_column(nullable=False, server_default="0")

    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="plan")

    __table_args__ = (
        CheckConstraint("interval_count >= 1", name="interval_count_positive"),
        CheckConstraint("unit_amount >= 0", name="unit_amount_non_negative"),
        CheckConstraint("cancellation_notice_days >= 0", name="cancellation_notice_non_negative"),
    )


class Subscription(IdMixin, AuditMixin, Base):
    """A live recurring commitment created from a subscription quotation line."""

    __tablename__ = "subscriptions"

    # One subscription per line: UNIQUE, not merely indexed.
    quotation_line_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_lines.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    subscription_plan_id: Mapped[int] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        enum_column(SubscriptionStatus, "subscription_status"),
        nullable=False,
        server_default=SubscriptionStatus.ACTIVE.value,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # The cycle currently being billed. Proration is computed against these
    # two dates, so they must always be populated and ordered.
    current_cycle_start: Mapped[date] = mapped_column(nullable=False)
    current_cycle_end: Mapped[date] = mapped_column(nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    quotation_line: Mapped[QuotationLine] = relationship(back_populates="subscription")
    plan: Mapped[SubscriptionPlan] = relationship(back_populates="subscriptions")
    customer: Mapped[Customer] = relationship()
    billing_schedules: Mapped[list[BillingSchedule]] = relationship(back_populates="subscription")
    proration_records: Mapped[list[ProrationRecord]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="subscription_quantity_positive"),
        CheckConstraint("unit_amount >= 0", name="subscription_unit_amount_non_negative"),
        CheckConstraint("current_cycle_end > current_cycle_start", name="cycle_dates_ordered"),
    )


class BillingSchedule(IdMixin, AuditMixin, Base):
    """One dated amount to be billed.

    Holds both the one-time invoice for hardware/services and each recurring
    instalment for subscriptions, distinguished by `schedule_type`. Every row
    carries `quotation_id`, which is what keeps a hybrid order reconciled to a
    single document (PRD B7).
    """

    __tablename__ = "billing_schedules"

    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("quotations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # NULL for one-time rows.
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="RESTRICT"), index=True
    )

    schedule_type: Mapped[BillingScheduleType] = mapped_column(
        enum_column(BillingScheduleType, "billing_schedule_type"),
        nullable=False,
        index=True,
    )
    status: Mapped[BillingScheduleStatus] = mapped_column(
        enum_column(BillingScheduleStatus, "billing_schedule_status"),
        nullable=False,
        server_default=BillingScheduleStatus.SCHEDULED.value,
        index=True,
    )

    due_date: Mapped[date] = mapped_column(nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # The period this instalment covers; NULL for one-time rows.
    cycle_start: Mapped[date | None] = mapped_column()
    cycle_end: Mapped[date | None] = mapped_column()

    invoice_number: Mapped[str | None] = mapped_column(String(40), unique=True)
    invoiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Negative amounts are credit notes arising from a downgrade or
    # cancellation (PRD B7).
    is_credit_note: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    quotation: Mapped[Quotation] = relationship(back_populates="billing_schedules")
    subscription: Mapped[Subscription | None] = relationship(back_populates="billing_schedules")
    payments: Mapped[list[Payment]] = relationship(
        back_populates="billing_schedule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # A recurring row must belong to a subscription; a one-time row must not.
        CheckConstraint(
            "(schedule_type = 'recurring' AND subscription_id IS NOT NULL)"
            " OR (schedule_type = 'one_time' AND subscription_id IS NULL)",
            name="recurring_schedule_requires_subscription",
        ),
        CheckConstraint(
            "(cycle_start IS NULL AND cycle_end IS NULL)"
            " OR (cycle_start IS NOT NULL AND cycle_end IS NOT NULL"
            " AND cycle_end >= cycle_start)",
            name="schedule_cycle_dates_consistent",
        ),
        Index("ix_billing_schedules_status_due_date", "status", "due_date"),
    )


class ProrationRecord(IdMixin, AuditMixin, Base):
    """An audit row for one mid-cycle change.

    Every input to the calculation is stored, not just the result. That is the
    difference between being able to answer a billing dispute and not - and it
    is required by PROJECT_CONTEXT.md Locked Business Rules #3.

    Formula (locked): daily basis, ROUND_HALF_UP to 2dp.
        credit    = old_amount x (remaining_days / cycle_days)
        charge    = new_amount x (remaining_days / cycle_days)
        proration = ROUND_HALF_UP(charge - credit, 2)
    """

    __tablename__ = "proration_records"

    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    change_date: Mapped[date] = mapped_column(nullable=False)
    cycle_start: Mapped[date] = mapped_column(nullable=False)
    cycle_end: Mapped[date] = mapped_column(nullable=False)
    cycle_days: Mapped[int] = mapped_column(nullable=False)
    remaining_days: Mapped[int] = mapped_column(nullable=False)

    old_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    new_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    old_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    new_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    credit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    charge_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # Signed: negative means the customer is owed a credit note.
    proration_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    subscription: Mapped[Subscription] = relationship(back_populates="proration_records")

    __table_args__ = (
        CheckConstraint("cycle_days > 0", name="cycle_days_positive"),
        CheckConstraint(
            "remaining_days >= 0 AND remaining_days <= cycle_days",
            name="remaining_days_within_cycle",
        ),
        CheckConstraint("cycle_end > cycle_start", name="proration_cycle_dates_ordered"),
        CheckConstraint(
            "change_date >= cycle_start AND change_date <= cycle_end",
            name="change_date_within_cycle",
        ),
    )


class Payment(IdMixin, AuditMixin, Base):
    """A payment recorded against a billing schedule.

    Required by the PRD's own quick test flow (Section 9): "Confirm the order,
    record a payment, and check that the invoice status updates correctly."
    """

    __tablename__ = "payments"

    billing_schedule_id: Mapped[int] = mapped_column(
        ForeignKey("billing_schedules.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(
        enum_column(PaymentMethod, "payment_method"), nullable=False
    )
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)

    billing_schedule: Mapped[BillingSchedule] = relationship(back_populates="payments")

    __table_args__ = (CheckConstraint("amount > 0", name="payment_amount_positive"),)
