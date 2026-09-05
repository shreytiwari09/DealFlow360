"""Hybrid billing: schedule generation and mid-cycle proration (PRD B7).

Mirrors risk.py's and fulfillment.py's shape: a pure calculation function
first (`compute_proration`, unit-testable with no database), then the
database-orchestration layer that persists it.

PROJECT_CONTEXT.md "Locked Business Rules" #3 is authoritative for the
formula and is not restated here beyond the docstrings needed to explain the
code — see that document for the worked example and the rationale for
`Decimal` + `ROUND_HALF_UP` over the builtin `round()`.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.billing import (
    BillingSchedule,
    Payment,
    ProrationRecord,
    Subscription,
    SubscriptionPlan,
)
from app.models.enums import (
    BillingInterval,
    BillingScheduleStatus,
    BillingScheduleType,
    ItemType,
    PaymentMethod,
    RefundPolicy,
    SubscriptionStatus,
)
from app.models.quotation import Quotation, QuotationLine
from app.services.state_machine import InvalidStateTransition, assert_transition

_MONEY = Decimal("0.01")
# Matches `subscriptions.quantity`'s Numeric(12, 3) column scale. Quantizing
# here, not just on write, keeps a value set in this request (e.g. a modify's
# `new_quantity`) printing the same "N.NNN" shape a DB-round-tripped value
# already has - without it, the API would return "3" for a value set this
# request but "3.000" for the same value read back after a reload, which is
# confusing on a screen showing both in the same table.
_QUANTITY = Decimal("0.001")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _qty(value: Decimal) -> Decimal:
    return value.quantize(_QUANTITY, rounding=ROUND_HALF_UP)


class BillingError(Exception):
    """A billing action was attempted against invalid state or input."""


# --- Pure proration math -----------------------------------------------------


@dataclass(frozen=True)
class ProrationResult:
    """Every input plus the result. Locked Business Rules #3: storing only the
    answer makes a billing dispute unanswerable, so every field here is meant
    to be persisted, not just `proration_amount`."""

    change_date: date
    cycle_start: date
    cycle_end: date
    cycle_days: int
    remaining_days: int
    old_amount: Decimal
    new_amount: Decimal
    credit_amount: Decimal
    charge_amount: Decimal
    proration_amount: Decimal  # negative = credit note


def compute_proration(
    *,
    old_amount: Decimal,
    new_amount: Decimal,
    cycle_start: date,
    cycle_end: date,
    change_date: date,
) -> ProrationResult:
    """Pure. Daily basis, `ROUND_HALF_UP` to 2dp.

        cycle_days     = cycle_end - cycle_start
        remaining_days = cycle_end - change_date
        credit         = old_amount x (remaining_days / cycle_days)
        charge         = new_amount x (remaining_days / cycle_days)
        proration      = ROUND_HALF_UP(charge - credit, 2)

    Reproduces the locked worked example exactly: 1200/month upgraded to
    1800/month on day 10 of a 30-day cycle gives credit 800.04, charge
    1200.06, proration +400.02.
    """
    if cycle_end <= cycle_start:
        raise BillingError("cycle_end must be after cycle_start.")
    if not (cycle_start <= change_date <= cycle_end):
        raise BillingError("change_date must fall within the cycle.")

    cycle_days = (cycle_end - cycle_start).days
    remaining_days = (cycle_end - change_date).days
    fraction = Decimal(remaining_days) / Decimal(cycle_days)

    credit = _money(old_amount * fraction)
    charge = _money(new_amount * fraction)

    return ProrationResult(
        change_date=change_date,
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        cycle_days=cycle_days,
        remaining_days=remaining_days,
        old_amount=old_amount,
        new_amount=new_amount,
        credit_amount=credit,
        charge_amount=charge,
        proration_amount=_money(charge - credit),
    )


def add_billing_interval(start: date, interval: BillingInterval, interval_count: int) -> date:
    """Advance `start` by one plan cycle. PRD A5: monthly/quarterly/yearly,
    with `interval_count` letting "every 2 months" be expressed.

    Calendar-month arithmetic, not `+30 days` — a monthly plan started on the
    31st must land on the 28th/29th/30th of a shorter month, not silently
    drift earlier every cycle the way naive day-counting would.
    """
    months = {
        BillingInterval.MONTHLY: 1,
        BillingInterval.QUARTERLY: 3,
        BillingInterval.YEARLY: 12,
    }[interval] * interval_count

    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


# --- Database orchestration --------------------------------------------------


async def load_subscription(session: AsyncSession, subscription_id: int) -> Subscription | None:
    result = await session.execute(
        select(Subscription)
        .where(Subscription.id == subscription_id)
        .options(
            selectinload(Subscription.plan),
            selectinload(Subscription.customer),
            selectinload(Subscription.quotation_line).selectinload(QuotationLine.quotation),
            selectinload(Subscription.quotation_line).selectinload(QuotationLine.product),
            # .quotation on each schedule: `_schedule_response` reads
            # `bs.quotation.quote_number`, and without eager-loading it here
            # that is a lazy load outside a sync context - the same
            # MissingGreenlet failure class documented in "Do Not Change".
            selectinload(Subscription.billing_schedules).selectinload(BillingSchedule.quotation),
            selectinload(Subscription.proration_records),
        )
    )
    return result.scalar_one_or_none()


async def load_billing_schedule(session: AsyncSession, schedule_id: int) -> BillingSchedule | None:
    result = await session.execute(
        select(BillingSchedule)
        .where(BillingSchedule.id == schedule_id)
        .options(
            selectinload(BillingSchedule.quotation).selectinload(Quotation.customer),
            selectinload(BillingSchedule.payments),
        )
    )
    return result.scalar_one_or_none()


async def generate_billing_for_quotation(
    session: AsyncSession, quotation: Quotation, *, actor_id: int
) -> list[BillingSchedule]:
    """Create the billing schedule for a newly confirmed quotation.

    One `one_time` row covering every one-time line's total (already
    tax-inclusive via `line_total`), plus one `Subscription` row and its
    first-cycle `recurring` row per subscription line.

    Called from the same CONFIRMED transition that unlocks fulfillment
    (Locked Business Rules #7: CONFIRMED is where "the order is real" is
    decided everywhere else in this codebase, so billing uses the same
    trigger point rather than inventing a second one). Idempotent — viewing
    or re-confirming must never double-bill, mirroring
    `generate_fulfillment`'s existing-row guard.
    """
    await session.refresh(quotation, attribute_names=["lines", "billing_schedules"])
    if quotation.billing_schedules:
        return quotation.billing_schedules

    today = datetime.now(UTC).date()

    one_time_lines = [line for line in quotation.lines if line.line_type == ItemType.ONE_TIME]
    if one_time_lines:
        amount = _money(sum((line.line_total for line in one_time_lines), Decimal("0")))
        session.add(
            BillingSchedule(
                quotation_id=quotation.id,
                schedule_type=BillingScheduleType.ONE_TIME,
                status=BillingScheduleStatus.SCHEDULED,
                due_date=today,
                amount=amount,
                created_by=actor_id,
            )
        )

    subscription_lines = [
        line for line in quotation.lines if line.line_type == ItemType.SUBSCRIPTION
    ]
    if subscription_lines:
        plan_ids = {line.subscription_plan_id for line in subscription_lines}
        plan_rows = await session.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id.in_(plan_ids))
        )
        plans = {plan.id: plan for plan in plan_rows.scalars()}
        for line in subscription_lines:
            plan = plans[line.subscription_plan_id]
            cycle_start = today
            cycle_end = add_billing_interval(
                cycle_start, plan.billing_interval, plan.interval_count
            )

            subscription = Subscription(
                quotation_line_id=line.id,
                subscription_plan_id=plan.id,
                customer_id=quotation.customer_id,
                status=SubscriptionStatus.ACTIVE,
                quantity=line.quantity,
                unit_amount=plan.unit_amount,
                current_cycle_start=cycle_start,
                current_cycle_end=cycle_end,
                started_at=datetime.now(UTC),
                created_by=actor_id,
            )
            session.add(subscription)
            await session.flush()  # need subscription.id for the schedule row below

            session.add(
                BillingSchedule(
                    quotation_id=quotation.id,
                    subscription_id=subscription.id,
                    schedule_type=BillingScheduleType.RECURRING,
                    status=BillingScheduleStatus.SCHEDULED,
                    due_date=cycle_start,
                    amount=_money(plan.unit_amount * line.quantity),
                    cycle_start=cycle_start,
                    cycle_end=cycle_end,
                    created_by=actor_id,
                )
            )

    await session.flush()
    await session.refresh(quotation, attribute_names=["billing_schedules"])
    return quotation.billing_schedules


def _clamp_to_cycle(when: date, subscription: Subscription) -> date:
    """A modify/cancel action is expected to happen mid-cycle, but defends
    against the boundary case where a cycle has technically elapsed and
    nothing has rolled it over yet (no renewal job exists — Known Issues)."""
    return min(max(when, subscription.current_cycle_start), subscription.current_cycle_end)


async def modify_subscription(
    session: AsyncSession,
    subscription: Subscription,
    *,
    new_quantity: Decimal | None,
    new_plan_id: int | None,
    actor_id: int,
) -> ProrationRecord:
    """PRD B7 mid-cycle quantity or plan change, priced with the locked
    proration formula.

    `old_amount` is what the current cycle was already sized for
    (quantity x unit_amount); `new_amount` is the same shape recomputed with
    whichever of quantity/plan changed. The subscription settles back to
    ACTIVE immediately once the proration is recorded — MODIFIED is a
    transient state, not a place it waits.
    """
    if new_quantity is None and new_plan_id is None:
        raise BillingError("Provide a new quantity, a new plan, or both.")

    assert_transition(
        "Subscription", SubscriptionStatus(subscription.status), SubscriptionStatus.MODIFIED
    )

    plan = subscription.plan
    if new_plan_id is not None and new_plan_id != subscription.subscription_plan_id:
        plan_row = await session.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == new_plan_id)
        )
        plan = plan_row.scalar_one_or_none()
        if plan is None or not plan.is_active:
            raise BillingError("Unknown or inactive subscription plan.")

    old_amount = _money(subscription.quantity * subscription.unit_amount)
    quantity = _qty(new_quantity) if new_quantity is not None else subscription.quantity
    new_amount = _money(quantity * plan.unit_amount)

    change_date = _clamp_to_cycle(datetime.now(UTC).date(), subscription)
    calc = compute_proration(
        old_amount=old_amount,
        new_amount=new_amount,
        cycle_start=subscription.current_cycle_start,
        cycle_end=subscription.current_cycle_end,
        change_date=change_date,
    )

    record = ProrationRecord(
        subscription_id=subscription.id,
        change_date=calc.change_date,
        cycle_start=calc.cycle_start,
        cycle_end=calc.cycle_end,
        cycle_days=calc.cycle_days,
        remaining_days=calc.remaining_days,
        old_quantity=subscription.quantity,
        new_quantity=quantity,
        old_amount=calc.old_amount,
        new_amount=calc.new_amount,
        credit_amount=calc.credit_amount,
        charge_amount=calc.charge_amount,
        proration_amount=calc.proration_amount,
        created_by=actor_id,
    )
    session.add(record)

    # One BillingSchedule row records the adjustment itself. A downgrade
    # yields a negative proration_amount, stored as-is, per the model's own
    # comment on `is_credit_note` — a positive amount bills, a negative one
    # is the credit note PRD B7 requires on a downgrade.
    session.add(
        BillingSchedule(
            quotation_id=subscription.quotation_line.quotation_id,
            subscription_id=subscription.id,
            schedule_type=BillingScheduleType.RECURRING,
            status=BillingScheduleStatus.SCHEDULED,
            due_date=change_date,
            amount=calc.proration_amount,
            cycle_start=calc.cycle_start,
            cycle_end=calc.cycle_end,
            is_credit_note=calc.proration_amount < 0,
            created_by=actor_id,
        )
    )

    subscription.subscription_plan_id = plan.id
    subscription.plan = plan
    subscription.quantity = quantity
    subscription.unit_amount = plan.unit_amount
    subscription.status = SubscriptionStatus.MODIFIED
    await session.flush()

    # MODIFIED -> ACTIVE is itself a checked transition (state_machine.py
    # allows it), not a second bare assignment — same standard as every other
    # status change in this codebase.
    assert_transition("Subscription", SubscriptionStatus.MODIFIED, SubscriptionStatus.ACTIVE)
    subscription.status = SubscriptionStatus.ACTIVE
    await session.flush()

    # `record` and the adjustment schedule above were both added via
    # `session.add(...)`, not `subscription.proration_records.append(...)` /
    # `.billing_schedules.append(...)`. Worse than the usual version of this
    # bug (see "Do Not Change"): `subscription` here is already in this
    # session's identity map from the caller's own lookup, with those two
    # collections eager-loaded and cached BEFORE this function ran. A second
    # `SELECT ... selectinload(...)` in the same session does not re-fetch an
    # already-loaded collection on an identity-mapped object, so a caller
    # that "reloads" the subscription afterward would still see the stale,
    # pre-modification collections despite the commit having succeeded. The
    # explicit refresh below is what actually invalidates them.
    await session.refresh(subscription, attribute_names=["proration_records", "billing_schedules"])
    return record


async def cancel_subscription(
    session: AsyncSession, subscription: Subscription, *, actor_id: int
) -> ProrationRecord | None:
    """PRD B7: cancelling triggers "an automatic partial refund or credit
    note", governed by the plan's `refund_policy` (PRD A5).

    - `none`: no credit, no ProrationRecord.
    - `prorated`: the locked formula with new_amount=0 — a pure credit for
      the unused remainder of the current cycle.
    - `full`: the entire amount already committed for the current cycle is
      credited back, regardless of how many days remain.
    """
    try:
        assert_transition(
            "Subscription", SubscriptionStatus(subscription.status), SubscriptionStatus.CANCELLED
        )
    except InvalidStateTransition as exc:
        raise BillingError(str(exc)) from exc

    record: ProrationRecord | None = None
    policy = subscription.plan.refund_policy
    if policy != RefundPolicy.NONE:
        old_amount = _money(subscription.quantity * subscription.unit_amount)
        change_date = _clamp_to_cycle(datetime.now(UTC).date(), subscription)

        if policy == RefundPolicy.FULL:
            cycle_days = (subscription.current_cycle_end - subscription.current_cycle_start).days
            calc = ProrationResult(
                change_date=change_date,
                cycle_start=subscription.current_cycle_start,
                cycle_end=subscription.current_cycle_end,
                cycle_days=cycle_days,
                remaining_days=cycle_days,
                old_amount=old_amount,
                new_amount=Decimal("0"),
                credit_amount=old_amount,
                charge_amount=Decimal("0"),
                proration_amount=_money(-old_amount),
            )
        else:  # PRORATED
            calc = compute_proration(
                old_amount=old_amount,
                new_amount=Decimal("0"),
                cycle_start=subscription.current_cycle_start,
                cycle_end=subscription.current_cycle_end,
                change_date=change_date,
            )

        if calc.proration_amount != 0:
            record = ProrationRecord(
                subscription_id=subscription.id,
                change_date=calc.change_date,
                cycle_start=calc.cycle_start,
                cycle_end=calc.cycle_end,
                cycle_days=calc.cycle_days,
                remaining_days=calc.remaining_days,
                old_quantity=subscription.quantity,
                new_quantity=Decimal("0"),
                old_amount=calc.old_amount,
                new_amount=calc.new_amount,
                credit_amount=calc.credit_amount,
                charge_amount=calc.charge_amount,
                proration_amount=calc.proration_amount,
                created_by=actor_id,
            )
            session.add(record)
            session.add(
                BillingSchedule(
                    quotation_id=subscription.quotation_line.quotation_id,
                    subscription_id=subscription.id,
                    schedule_type=BillingScheduleType.RECURRING,
                    status=BillingScheduleStatus.SCHEDULED,
                    due_date=change_date,
                    amount=calc.proration_amount,
                    cycle_start=calc.cycle_start,
                    cycle_end=calc.cycle_end,
                    is_credit_note=True,
                    created_by=actor_id,
                )
            )

    subscription.status = SubscriptionStatus.CANCELLED
    subscription.cancelled_at = datetime.now(UTC)
    await session.flush()

    # Same identity-map staleness as `modify_subscription` above — refresh
    # unconditionally, even when `record` ended up None (a no-op refresh is
    # cheap; a caller silently getting a stale collection is not).
    await session.refresh(subscription, attribute_names=["proration_records", "billing_schedules"])
    return record


async def issue_invoice(session: AsyncSession, schedule: BillingSchedule, *, actor_id: int) -> None:
    """SCHEDULED -> INVOICED. Assigns the human-readable invoice number."""
    try:
        assert_transition(
            "BillingSchedule",
            BillingScheduleStatus(schedule.status),
            BillingScheduleStatus.INVOICED,
        )
    except InvalidStateTransition as exc:
        raise BillingError(str(exc)) from exc

    schedule.invoice_number = await next_invoice_number(session)
    schedule.invoiced_at = datetime.now(UTC)
    schedule.status = BillingScheduleStatus.INVOICED
    await session.flush()


async def record_payment(
    session: AsyncSession,
    schedule: BillingSchedule,
    *,
    amount: Decimal,
    method: PaymentMethod,
    reference: str | None,
    notes: str | None,
    actor_id: int,
) -> Payment:
    """Record a payment and settle the invoice.

    Full-payment model: this build does not track partial payments against
    `amount` (PLAN.md's own quick-test flow is "record a payment, check the
    invoice status updates" — a single settling payment, not an instalment
    ledger). Any recorded payment marks the schedule PAID once it is at least
    INVOICED; only INVOICED -> PAID is a legal transition, so a payment
    recorded before invoicing is rejected rather than silently accepted.
    """
    try:
        assert_transition(
            "BillingSchedule", BillingScheduleStatus(schedule.status), BillingScheduleStatus.PAID
        )
    except InvalidStateTransition as exc:
        raise BillingError(str(exc)) from exc

    payment = Payment(
        billing_schedule_id=schedule.id,
        amount=amount,
        method=method,
        paid_at=datetime.now(UTC),
        reference=reference,
        notes=notes,
        created_by=actor_id,
    )
    session.add(payment)
    schedule.status = BillingScheduleStatus.PAID
    await session.flush()

    # Same identity-map staleness documented in `modify_subscription`: the
    # caller's own earlier lookup already loaded `.payments` (as empty) on
    # this exact object, so a plain re-query afterward would not see it.
    await session.refresh(schedule, attribute_names=["payments"])
    return payment


async def next_invoice_number(session: AsyncSession) -> str:
    """Mirrors `quotation.next_quote_number`'s shape and rationale."""
    rows = await session.execute(
        select(BillingSchedule.id).where(BillingSchedule.invoice_number.is_not(None))
    )
    count = rows.scalars().all()
    return f"INV-{1000 + len(count) + 1}"
