"""Hybrid billing and proration tests (PRD B7).

Two layers, matching risk.py's and fulfillment.py's testing style:

  * `compute_proration()` and `add_billing_interval()` are pure - tested in
    isolation, no database. `compute_proration` is checked against the
    locked worked example from PROJECT_CONTEXT.md exactly.
  * `generate_billing_for_quotation`, `modify_subscription` and
    `cancel_subscription` are tested against the real PostgreSQL schema,
    because what matters - that a subscription line actually gets a plan,
    that a proration record captures every input, that the state machine
    guards are real - is only meaningful against the engine actually shipped.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Customer,
    Product,
    ProductCategory,
    Quotation,
    QuotationLine,
    Role,
    Subscription,
    SubscriptionPlan,
    User,
)
from app.models.enums import (
    BillingInterval,
    BillingScheduleStatus,
    CustomerTier,
    ItemType,
    PaymentMethod,
    QuotationStatus,
    RefundPolicy,
    RoleCode,
    SubscriptionStatus,
)
from app.services.billing import (
    BillingError,
    add_billing_interval,
    cancel_subscription,
    compute_proration,
    generate_billing_for_quotation,
    issue_invoice,
    load_subscription,
    modify_subscription,
    record_payment,
)

NOW = datetime.now(UTC)

# ---------------------------------------------------------------------------
# Pure math
# ---------------------------------------------------------------------------


def test_locked_worked_example_exactly() -> None:
    """1200/month upgraded to 1800/month on day 10 of a 30-day cycle, 20 days
    remaining: credit 1200 x 2/3 = 800.00 exactly, charge 1800 x 2/3 =
    1200.00 exactly, proration +400.00.

    PROJECT_CONTEXT.md's original worked example quoted 800.04 / 1200.06 /
    400.02 — those came from hand-rounding 20/30 to "0.6667" before
    multiplying. The locked FORMULA does not say to round the day-fraction;
    it says to round only the final `proration` figure. Full-precision
    `Decimal` division (2/3 to 28 significant digits) times 1200 or 1800
    lands on an exact cent value here, so there is nothing left to round away
    — the doc's numbers were a documentation arithmetic error, corrected
    alongside this test. See PROJECT_CONTEXT.md Locked Business Rules #3.
    """
    result = compute_proration(
        old_amount=Decimal("1200"),
        new_amount=Decimal("1800"),
        cycle_start=date(2026, 1, 1),
        cycle_end=date(2026, 1, 31),
        change_date=date(2026, 1, 11),
    )

    assert result.cycle_days == 30
    assert result.remaining_days == 20
    assert result.credit_amount == Decimal("800.00")
    assert result.charge_amount == Decimal("1200.00")
    assert result.proration_amount == Decimal("400.00")


def test_downgrade_yields_a_negative_proration() -> None:
    """A downgrade is the credit note PRD B7 requires."""
    result = compute_proration(
        old_amount=Decimal("1800"),
        new_amount=Decimal("1200"),
        cycle_start=date(2026, 1, 1),
        cycle_end=date(2026, 1, 31),
        change_date=date(2026, 1, 11),
    )

    assert result.proration_amount == Decimal("-400.00")


def test_rounding_is_half_up_not_bankers_rounding() -> None:
    """17 x 1/8 = 2.125 exactly - a genuine tie at the third decimal place.
    `ROUND_HALF_UP` must give 2.13; Python's builtin `round()` (banker's
    rounding, `ROUND_HALF_EVEN`) would give 2.12. This is the case the
    "never use `round()`" rule in PROJECT_CONTEXT.md Locked Business Rules #3
    actually protects against - the earlier exact-thirds example above
    has no tie to round at all.
    """
    result = compute_proration(
        old_amount=Decimal("17"),
        new_amount=Decimal("0"),
        cycle_start=date(2026, 1, 1),
        cycle_end=date(2026, 1, 9),  # 8-day cycle
        change_date=date(2026, 1, 8),  # 1 day remaining
    )

    assert result.cycle_days == 8
    assert result.remaining_days == 1
    assert result.credit_amount == Decimal("2.13")


def test_change_on_the_first_day_prorates_the_full_cycle() -> None:
    result = compute_proration(
        old_amount=Decimal("100"),
        new_amount=Decimal("200"),
        cycle_start=date(2026, 1, 1),
        cycle_end=date(2026, 1, 31),
        change_date=date(2026, 1, 1),
    )

    assert result.remaining_days == 30
    assert result.credit_amount == Decimal("100.00")
    assert result.charge_amount == Decimal("200.00")


def test_change_on_the_last_day_prorates_nothing() -> None:
    result = compute_proration(
        old_amount=Decimal("100"),
        new_amount=Decimal("200"),
        cycle_start=date(2026, 1, 1),
        cycle_end=date(2026, 1, 31),
        change_date=date(2026, 1, 31),
    )

    assert result.remaining_days == 0
    assert result.credit_amount == Decimal("0.00")
    assert result.proration_amount == Decimal("0.00")


def test_change_date_outside_the_cycle_is_rejected() -> None:
    with pytest.raises(BillingError, match="within the cycle"):
        compute_proration(
            old_amount=Decimal("100"),
            new_amount=Decimal("200"),
            cycle_start=date(2026, 1, 1),
            cycle_end=date(2026, 1, 31),
            change_date=date(2026, 2, 1),
        )


def test_cycle_end_before_cycle_start_is_rejected() -> None:
    with pytest.raises(BillingError, match="after cycle_start"):
        compute_proration(
            old_amount=Decimal("100"),
            new_amount=Decimal("200"),
            cycle_start=date(2026, 1, 31),
            cycle_end=date(2026, 1, 1),
            change_date=date(2026, 1, 15),
        )


def test_add_billing_interval_monthly() -> None:
    assert add_billing_interval(date(2026, 1, 15), BillingInterval.MONTHLY, 1) == date(2026, 2, 15)


def test_add_billing_interval_quarterly_with_count() -> None:
    """interval_count lets "every 2 quarters" (6 months) be expressed."""
    assert add_billing_interval(date(2026, 1, 15), BillingInterval.QUARTERLY, 2) == date(
        2026, 7, 15
    )


def test_add_billing_interval_yearly() -> None:
    assert add_billing_interval(date(2026, 1, 15), BillingInterval.YEARLY, 1) == date(2027, 1, 15)


def test_add_billing_interval_clamps_short_months() -> None:
    """Jan 31 + 1 month must land on Feb 28 (2026 is not a leap year), not
    overflow into March - naive `+30 days` would drift; this must not."""
    assert add_billing_interval(date(2026, 1, 31), BillingInterval.MONTHLY, 1) == date(2026, 2, 28)


def test_add_billing_interval_respects_leap_years() -> None:
    assert add_billing_interval(date(2028, 1, 31), BillingInterval.MONTHLY, 1) == date(2028, 2, 29)


# ---------------------------------------------------------------------------
# Database orchestration
# ---------------------------------------------------------------------------


@pytest.fixture
async def role(db_session: AsyncSession) -> Role:
    existing = (
        await db_session.execute(select(Role).where(Role.code == RoleCode.SALES_REP))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    role = Role(code=RoleCode.SALES_REP, name="Sales Rep")
    db_session.add(role)
    await db_session.flush()
    return role


@pytest.fixture
async def user(db_session: AsyncSession, role: Role) -> User:
    user = User(
        email=f"billing-{NOW.timestamp()}@example.test",
        password_hash="not-a-real-hash",
        full_name="Test Rep",
        role_id=role.id,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def customer(db_session: AsyncSession) -> Customer:
    customer = Customer(code=f"CUST-{NOW.timestamp()}", name="Acme Corp", tier=CustomerTier.GOLD)
    db_session.add(customer)
    await db_session.flush()
    return customer


@pytest.fixture
async def category(db_session: AsyncSession) -> ProductCategory:
    category = ProductCategory(code=f"HW-{NOW.timestamp()}", name="Hardware")
    db_session.add(category)
    await db_session.flush()
    return category


@pytest.fixture
async def one_time_product(db_session: AsyncSession, category: ProductCategory) -> Product:
    product = Product(
        sku=f"HW-{NOW.timestamp()}",
        name="Test Laptop",
        category_id=category.id,
        list_price=Decimal("1000.00"),
        cost_price=Decimal("700.00"),
        item_type=ItemType.ONE_TIME,
    )
    db_session.add(product)
    await db_session.flush()
    return product


@pytest.fixture
async def subscription_product(db_session: AsyncSession, category: ProductCategory) -> Product:
    product = Product(
        sku=f"SUB-{NOW.timestamp()}",
        name="Premium Support",
        category_id=category.id,
        list_price=Decimal("0"),
        cost_price=Decimal("0"),
        item_type=ItemType.SUBSCRIPTION,
    )
    db_session.add(product)
    await db_session.flush()
    return product


@pytest.fixture
async def plan(db_session: AsyncSession) -> SubscriptionPlan:
    plan = SubscriptionPlan(
        code=f"PLAN-{NOW.timestamp()}",
        name="Premium Support Monthly",
        billing_interval=BillingInterval.MONTHLY,
        interval_count=1,
        unit_amount=Decimal("1200.00"),
        refund_policy=RefundPolicy.PRORATED,
    )
    db_session.add(plan)
    await db_session.flush()
    return plan


@pytest.fixture
async def confirmed_quotation(
    db_session: AsyncSession,
    customer: Customer,
    user: User,
    one_time_product: Product,
    subscription_product: Product,
    plan: SubscriptionPlan,
) -> Quotation:
    """A hybrid order: one one-time line, one subscription line - exactly the
    "single order mixing hardware and subscriptions" PRD B7 requires."""
    quotation = Quotation(
        quote_number=f"Q-TEST-{NOW.timestamp()}",
        customer_id=customer.id,
        owner_id=user.id,
        status=QuotationStatus.CONFIRMED,
    )
    db_session.add(quotation)
    await db_session.flush()

    db_session.add(
        QuotationLine(
            quotation_id=quotation.id,
            line_number=1,
            product_id=one_time_product.id,
            quantity=Decimal("2"),
            unit_list_price=one_time_product.list_price,
            unit_cost_price=one_time_product.cost_price,
            line_type=ItemType.ONE_TIME,
            line_total=Decimal("2000.00"),
        )
    )
    db_session.add(
        QuotationLine(
            quotation_id=quotation.id,
            line_number=2,
            product_id=subscription_product.id,
            quantity=Decimal("1"),
            unit_list_price=subscription_product.list_price,
            unit_cost_price=subscription_product.cost_price,
            line_type=ItemType.SUBSCRIPTION,
            subscription_plan_id=plan.id,
        )
    )
    await db_session.flush()
    await db_session.refresh(quotation, attribute_names=["lines"])
    return quotation


async def test_generate_creates_one_time_and_recurring_rows(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    schedules = await generate_billing_for_quotation(
        db_session, confirmed_quotation, actor_id=user.id
    )

    by_type = {s.schedule_type for s in schedules}
    assert by_type == {"one_time", "recurring"}

    one_time = next(s for s in schedules if s.schedule_type == "one_time")
    assert one_time.amount == Decimal("2000.00")
    assert one_time.subscription_id is None

    recurring = next(s for s in schedules if s.schedule_type == "recurring")
    assert recurring.amount == Decimal("1200.00")
    assert recurring.subscription_id is not None


async def test_generate_creates_a_subscription_with_the_first_cycle(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    await generate_billing_for_quotation(db_session, confirmed_quotation, actor_id=user.id)

    subscription = (
        await db_session.execute(
            select(Subscription).where(Subscription.customer_id == confirmed_quotation.customer_id)
        )
    ).scalar_one()

    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.quantity == Decimal("1")
    assert subscription.unit_amount == Decimal("1200.00")
    assert subscription.current_cycle_end > subscription.current_cycle_start


async def test_generate_is_idempotent(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    first = await generate_billing_for_quotation(db_session, confirmed_quotation, actor_id=user.id)
    second = await generate_billing_for_quotation(db_session, confirmed_quotation, actor_id=user.id)

    assert len(first) == len(second) == 2


async def test_generate_skips_one_time_schedule_when_no_one_time_lines(
    db_session: AsyncSession,
    customer: Customer,
    user: User,
    subscription_product: Product,
    plan: SubscriptionPlan,
) -> None:
    quotation = Quotation(
        quote_number=f"Q-SUBONLY-{NOW.timestamp()}",
        customer_id=customer.id,
        owner_id=user.id,
        status=QuotationStatus.CONFIRMED,
    )
    db_session.add(quotation)
    await db_session.flush()
    db_session.add(
        QuotationLine(
            quotation_id=quotation.id,
            line_number=1,
            product_id=subscription_product.id,
            quantity=Decimal("1"),
            unit_list_price=subscription_product.list_price,
            unit_cost_price=subscription_product.cost_price,
            line_type=ItemType.SUBSCRIPTION,
            subscription_plan_id=plan.id,
        )
    )
    await db_session.flush()
    await db_session.refresh(quotation, attribute_names=["lines"])

    schedules = await generate_billing_for_quotation(db_session, quotation, actor_id=user.id)

    assert len(schedules) == 1
    assert schedules[0].schedule_type == "recurring"


async def test_modify_quantity_produces_a_proration_record(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    await generate_billing_for_quotation(db_session, confirmed_quotation, actor_id=user.id)
    subscription = (
        await db_session.execute(
            select(Subscription).where(Subscription.customer_id == confirmed_quotation.customer_id)
        )
    ).scalar_one()
    subscription = await load_subscription(db_session, subscription.id)

    record = await modify_subscription(
        db_session, subscription, new_quantity=Decimal("2"), new_plan_id=None, actor_id=user.id
    )

    assert record.old_quantity == Decimal("1")
    assert record.new_quantity == Decimal("2")
    assert record.proration_amount > 0  # doubling quantity mid-cycle is always a net charge
    assert subscription.status == SubscriptionStatus.ACTIVE  # settles back, not left MODIFIED
    assert subscription.quantity == Decimal("2")

    # Regression guard: `subscription` here is the SAME object `_load_subscription
    # _authorized` would have already cached in the session's identity map with
    # both collections eager-loaded as empty. Reading them straight off this
    # object (not via a second fetch) is exactly what the API's re-fetch-in-the-
    # -same-session pattern does, and it must see the fresh rows, not the stale
    # ones from before `modify_subscription` ran.
    assert len(subscription.proration_records) == 1
    assert subscription.proration_records[0] is record
    assert len(subscription.billing_schedules) == 2


async def test_modify_with_neither_field_is_rejected(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    await generate_billing_for_quotation(db_session, confirmed_quotation, actor_id=user.id)
    subscription = (
        await db_session.execute(
            select(Subscription).where(Subscription.customer_id == confirmed_quotation.customer_id)
        )
    ).scalar_one()
    subscription = await load_subscription(db_session, subscription.id)

    with pytest.raises(BillingError, match="Provide a new quantity"):
        await modify_subscription(
            db_session, subscription, new_quantity=None, new_plan_id=None, actor_id=user.id
        )


async def test_cancel_with_prorated_policy_credits_the_unused_remainder(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    await generate_billing_for_quotation(db_session, confirmed_quotation, actor_id=user.id)
    subscription = (
        await db_session.execute(
            select(Subscription).where(Subscription.customer_id == confirmed_quotation.customer_id)
        )
    ).scalar_one()
    subscription = await load_subscription(db_session, subscription.id)

    record = await cancel_subscription(db_session, subscription, actor_id=user.id)

    assert record is not None
    assert record.proration_amount < 0  # a credit
    assert subscription.status == SubscriptionStatus.CANCELLED
    assert subscription.cancelled_at is not None
    assert len(subscription.proration_records) == 1  # same identity-map guard as modify's test


async def test_cancel_with_none_policy_produces_no_credit(
    db_session: AsyncSession,
    confirmed_quotation: Quotation,
    user: User,
    plan: SubscriptionPlan,
) -> None:
    plan.refund_policy = RefundPolicy.NONE
    await db_session.flush()
    await generate_billing_for_quotation(db_session, confirmed_quotation, actor_id=user.id)
    subscription = (
        await db_session.execute(
            select(Subscription).where(Subscription.customer_id == confirmed_quotation.customer_id)
        )
    ).scalar_one()
    subscription = await load_subscription(db_session, subscription.id)

    record = await cancel_subscription(db_session, subscription, actor_id=user.id)

    assert record is None
    assert subscription.status == SubscriptionStatus.CANCELLED


async def test_cancel_with_full_policy_credits_the_entire_cycle(
    db_session: AsyncSession,
    confirmed_quotation: Quotation,
    user: User,
    plan: SubscriptionPlan,
) -> None:
    plan.refund_policy = RefundPolicy.FULL
    await db_session.flush()
    await generate_billing_for_quotation(db_session, confirmed_quotation, actor_id=user.id)
    subscription = (
        await db_session.execute(
            select(Subscription).where(Subscription.customer_id == confirmed_quotation.customer_id)
        )
    ).scalar_one()
    subscription = await load_subscription(db_session, subscription.id)

    record = await cancel_subscription(db_session, subscription, actor_id=user.id)

    assert record is not None
    assert record.proration_amount == Decimal("-1200.00")


async def test_cancelling_twice_is_rejected(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    await generate_billing_for_quotation(db_session, confirmed_quotation, actor_id=user.id)
    subscription = (
        await db_session.execute(
            select(Subscription).where(Subscription.customer_id == confirmed_quotation.customer_id)
        )
    ).scalar_one()
    subscription = await load_subscription(db_session, subscription.id)
    await cancel_subscription(db_session, subscription, actor_id=user.id)

    with pytest.raises(BillingError):
        await cancel_subscription(db_session, subscription, actor_id=user.id)


async def test_issue_then_pay_settles_the_invoice(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    schedules = await generate_billing_for_quotation(
        db_session, confirmed_quotation, actor_id=user.id
    )
    one_time = next(s for s in schedules if s.schedule_type == "one_time")

    await issue_invoice(db_session, one_time, actor_id=user.id)
    assert one_time.status == BillingScheduleStatus.INVOICED
    assert one_time.invoice_number is not None

    payment = await record_payment(
        db_session,
        one_time,
        amount=one_time.amount,
        method=PaymentMethod.BANK_TRANSFER,
        reference="TXN-1",
        notes=None,
        actor_id=user.id,
    )

    assert payment.amount == one_time.amount
    assert one_time.status == BillingScheduleStatus.PAID
    assert len(one_time.payments) == 1  # same identity-map guard as modify_subscription's test
    assert one_time.payments[0] is payment


async def test_payment_before_invoicing_is_rejected(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    schedules = await generate_billing_for_quotation(
        db_session, confirmed_quotation, actor_id=user.id
    )
    one_time = next(s for s in schedules if s.schedule_type == "one_time")
    assert one_time.status == BillingScheduleStatus.SCHEDULED

    with pytest.raises(BillingError):
        await record_payment(
            db_session,
            one_time,
            amount=one_time.amount,
            method=PaymentMethod.CASH,
            reference=None,
            notes=None,
            actor_id=user.id,
        )


async def test_invoice_numbers_are_sequential_and_human_readable(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    schedules = await generate_billing_for_quotation(
        db_session, confirmed_quotation, actor_id=user.id
    )
    for schedule in schedules:
        await issue_invoice(db_session, schedule, actor_id=user.id)

    numbers = {s.invoice_number for s in schedules}
    assert all(n.startswith("INV-") for n in numbers)
    assert len(numbers) == 2  # both got distinct numbers
