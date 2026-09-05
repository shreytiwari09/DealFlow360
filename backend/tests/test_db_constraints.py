"""Database constraint tests.

PLAN.md Section 7 requires proof that "constraints behave correctly (test
invalid input is rejected)". These run against the real PostgreSQL schema on
purpose: the claim under test is that the *database* refuses bad data, which
is only meaningful against the engine we actually ship.

Each test writes inside a savepoint that is rolled back afterwards.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ApprovalChain,
    ApprovalRequest,
    ApprovalStep,
    BillingSchedule,
    Customer,
    DiscountTier,
    Product,
    ProductCategory,
    ProrationRecord,
    Quotation,
    QuotationLine,
    Role,
    StockLevel,
    Subscription,
    SubscriptionPlan,
    UpsellRule,
    User,
    Warehouse,
)
from app.models.enums import (
    ApprovalStatus,
    BillingScheduleType,
    CustomerTier,
    ItemType,
    RoleCode,
    SubscriptionStatus,
)

NOW = datetime.now(UTC)


# --- Fixtures building the minimum graph a quotation needs -----------------


@pytest.fixture
async def role(db_session: AsyncSession) -> Role:
    """Reuse the seeded role if the seed has been run.

    `roles.code` is UNIQUE over a fixed enum, so unlike the other fixtures this
    one cannot sidestep collisions with a generated code - it has to adopt the
    existing row.
    """
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
        email=f"rep-{NOW.timestamp()}@example.test",
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
async def product(db_session: AsyncSession, category: ProductCategory) -> Product:
    product = Product(
        sku=f"SKU-{NOW.timestamp()}",
        name="Laptop",
        category_id=category.id,
        list_price=Decimal("100000.00"),
        cost_price=Decimal("70000.00"),
    )
    db_session.add(product)
    await db_session.flush()
    return product


@pytest.fixture
async def quotation(db_session: AsyncSession, customer: Customer, user: User) -> Quotation:
    quotation = Quotation(
        quote_number=f"Q-{NOW.timestamp()}",
        customer_id=customer.id,
        owner_id=user.id,
    )
    db_session.add(quotation)
    await db_session.flush()
    return quotation


@pytest.fixture
async def plan(db_session: AsyncSession) -> SubscriptionPlan:
    plan = SubscriptionPlan(
        code=f"PLAN-{NOW.timestamp()}",
        name="Monthly Support",
        billing_interval="monthly",
        unit_amount=Decimal("1200.00"),
    )
    db_session.add(plan)
    await db_session.flush()
    return plan


async def _expect_integrity_error(session: AsyncSession) -> str:
    """Flush, requiring the database to reject it. Returns the error text."""
    with pytest.raises(IntegrityError) as exc:
        await session.flush()
    await session.rollback()
    return str(exc.value)


# --- Discount governance ---------------------------------------------------


async def test_discount_ceiling_above_100_percent_is_rejected(
    db_session: AsyncSession, category: ProductCategory
) -> None:
    db_session.add(
        DiscountTier(
            customer_tier=CustomerTier.GOLD,
            category_id=category.id,
            max_discount_percent=Decimal("150.00"),
        )
    )

    assert "max_discount_percentage_range" in await _expect_integrity_error(db_session)


async def test_duplicate_ceiling_for_tier_and_category_is_rejected(
    db_session: AsyncSession, category: ProductCategory
) -> None:
    """Two ceilings for one (tier, category) would make the risk score
    ambiguous - which limit did the line breach?"""
    for _ in range(2):
        db_session.add(
            DiscountTier(
                customer_tier=CustomerTier.GOLD,
                category_id=category.id,
                max_discount_percent=Decimal("15.00"),
            )
        )

    assert "uq_discount_tiers_tier_category" in await _expect_integrity_error(db_session)


async def test_approval_band_must_be_ordered(db_session: AsyncSession, role: Role) -> None:
    db_session.add(
        ApprovalChain(
            min_score=Decimal("25.00"),
            max_score=Decimal("10.00"),
            required_role_id=role.id,
            step_order=1,
        )
    )

    assert "score_band_ordered" in await _expect_integrity_error(db_session)


async def test_approval_step_order_must_be_positive(db_session: AsyncSession, role: Role) -> None:
    db_session.add(ApprovalChain(min_score=Decimal("0.01"), required_role_id=role.id, step_order=0))

    assert "step_order_positive" in await _expect_integrity_error(db_session)


# --- Quotation lines -------------------------------------------------------


def _line(quotation: Quotation, product: Product, **overrides) -> QuotationLine:
    values = {
        "quotation_id": quotation.id,
        "line_number": 1,
        "product_id": product.id,
        "quantity": Decimal("1"),
        "unit_list_price": Decimal("100000.00"),
        "unit_cost_price": Decimal("70000.00"),
    }
    values.update(overrides)
    return QuotationLine(**values)


async def test_zero_quantity_line_is_rejected(
    db_session: AsyncSession, quotation: Quotation, product: Product
) -> None:
    db_session.add(_line(quotation, product, quantity=Decimal("0")))

    assert "quantity_positive" in await _expect_integrity_error(db_session)


async def test_discount_above_100_percent_is_rejected(
    db_session: AsyncSession, quotation: Quotation, product: Product
) -> None:
    db_session.add(_line(quotation, product, discount_percent=Decimal("120.00")))

    assert "discount_percentage_range" in await _expect_integrity_error(db_session)


async def test_duplicate_line_number_on_one_quotation_is_rejected(
    db_session: AsyncSession, quotation: Quotation, product: Product
) -> None:
    db_session.add(_line(quotation, product, line_number=1))
    db_session.add(_line(quotation, product, line_number=1))

    error = await _expect_integrity_error(db_session)
    assert "uq_quotation_lines_quotation_line_no" in error


async def test_subscription_line_without_a_plan_is_rejected(
    db_session: AsyncSession, quotation: Quotation, product: Product
) -> None:
    """A subscription line with no plan could never generate a billing
    schedule, so the database refuses to store one."""
    db_session.add(
        _line(
            quotation,
            product,
            line_type=ItemType.SUBSCRIPTION,
            subscription_plan_id=None,
        )
    )

    assert "subscription_line_requires_plan" in await _expect_integrity_error(db_session)


async def test_one_time_line_carrying_a_plan_is_rejected(
    db_session: AsyncSession,
    quotation: Quotation,
    product: Product,
    plan: SubscriptionPlan,
) -> None:
    db_session.add(
        _line(
            quotation,
            product,
            line_type=ItemType.ONE_TIME,
            subscription_plan_id=plan.id,
        )
    )

    assert "subscription_line_requires_plan" in await _expect_integrity_error(db_session)


async def test_valid_hybrid_quotation_is_accepted(
    db_session: AsyncSession,
    quotation: Quotation,
    product: Product,
    plan: SubscriptionPlan,
) -> None:
    """The positive case: one-time and subscription lines coexisting on a
    single quotation is exactly what hybrid billing requires."""
    db_session.add(_line(quotation, product, line_number=1, line_type=ItemType.ONE_TIME))
    db_session.add(
        _line(
            quotation,
            product,
            line_number=2,
            line_type=ItemType.SUBSCRIPTION,
            subscription_plan_id=plan.id,
        )
    )

    await db_session.flush()  # must not raise


# --- Stock -----------------------------------------------------------------


async def test_reserved_stock_cannot_exceed_stock_on_hand(
    db_session: AsyncSession, product: Product
) -> None:
    warehouse = Warehouse(code=f"WH-{NOW.timestamp()}", name="Main Warehouse")
    db_session.add(warehouse)
    await db_session.flush()

    db_session.add(
        StockLevel(
            warehouse_id=warehouse.id,
            product_id=product.id,
            quantity_on_hand=Decimal("5"),
            quantity_reserved=Decimal("9"),
        )
    )

    assert "reserved_within_on_hand" in await _expect_integrity_error(db_session)


async def test_duplicate_stock_row_is_rejected_even_with_null_variant(
    db_session: AsyncSession, product: Product
) -> None:
    """The NULLS NOT DISTINCT case.

    PostgreSQL treats NULLs as distinct in a normal UNIQUE index, so without
    `postgresql_nulls_not_distinct` this would silently allow two stock rows
    for the same product in the same warehouse - and the warehouse split
    would then read only one of them and under-count available stock.
    """
    warehouse = Warehouse(code=f"WH2-{NOW.timestamp()}", name="East Depot")
    db_session.add(warehouse)
    await db_session.flush()

    for _ in range(2):
        db_session.add(
            StockLevel(
                warehouse_id=warehouse.id,
                product_id=product.id,
                variant_id=None,
                quantity_on_hand=Decimal("10"),
            )
        )

    error = await _expect_integrity_error(db_session)
    assert "uq_stock_levels_warehouse_product_variant" in error


# --- Approvals -------------------------------------------------------------


async def test_decided_approval_step_must_record_actor_and_timestamp(
    db_session: AsyncSession, quotation: Quotation, role: Role
) -> None:
    """An approval with no approver is exactly the hole the audit trail
    exists to close."""
    request = ApprovalRequest(
        quotation_id=quotation.id,
        blended_risk_score=Decimal("8.00"),
        max_line_excess=Decimal("8.00"),
        requested_at=NOW,
    )
    db_session.add(request)
    await db_session.flush()

    db_session.add(
        ApprovalStep(
            request_id=request.id,
            step_order=1,
            required_role_id=role.id,
            status=ApprovalStatus.APPROVED,
            actor_id=None,
            decided_at=None,
        )
    )

    error = await _expect_integrity_error(db_session)
    assert "decided_step_has_actor_and_timestamp" in error


async def test_pending_approval_step_must_not_claim_a_decision(
    db_session: AsyncSession, quotation: Quotation, role: Role, user: User
) -> None:
    request = ApprovalRequest(
        quotation_id=quotation.id,
        blended_risk_score=Decimal("8.00"),
        max_line_excess=Decimal("8.00"),
        requested_at=NOW,
    )
    db_session.add(request)
    await db_session.flush()

    db_session.add(
        ApprovalStep(
            request_id=request.id,
            step_order=1,
            required_role_id=role.id,
            status=ApprovalStatus.PENDING,
            actor_id=user.id,
            decided_at=NOW,
        )
    )

    error = await _expect_integrity_error(db_session)
    assert "decided_step_has_actor_and_timestamp" in error


# --- Billing ---------------------------------------------------------------


async def test_recurring_billing_row_requires_a_subscription(
    db_session: AsyncSession, quotation: Quotation
) -> None:
    db_session.add(
        BillingSchedule(
            quotation_id=quotation.id,
            subscription_id=None,
            schedule_type=BillingScheduleType.RECURRING,
            due_date=date(2026, 10, 1),
            amount=Decimal("1200.00"),
        )
    )

    error = await _expect_integrity_error(db_session)
    assert "recurring_schedule_requires_subscription" in error


async def test_proration_remaining_days_cannot_exceed_the_cycle(
    db_session: AsyncSession,
    quotation: Quotation,
    product: Product,
    plan: SubscriptionPlan,
    customer: Customer,
) -> None:
    line = _line(
        quotation,
        product,
        line_type=ItemType.SUBSCRIPTION,
        subscription_plan_id=plan.id,
    )
    db_session.add(line)
    await db_session.flush()

    subscription = Subscription(
        quotation_line_id=line.id,
        subscription_plan_id=plan.id,
        customer_id=customer.id,
        status=SubscriptionStatus.ACTIVE,
        quantity=Decimal("1"),
        unit_amount=Decimal("1200.00"),
        current_cycle_start=date(2026, 9, 1),
        current_cycle_end=date(2026, 10, 1),
        started_at=NOW,
    )
    db_session.add(subscription)
    await db_session.flush()

    db_session.add(
        ProrationRecord(
            subscription_id=subscription.id,
            change_date=date(2026, 9, 10),
            cycle_start=date(2026, 9, 1),
            cycle_end=date(2026, 10, 1),
            cycle_days=30,
            remaining_days=45,  # impossible
            old_quantity=Decimal("1"),
            new_quantity=Decimal("2"),
            old_amount=Decimal("1200.00"),
            new_amount=Decimal("1800.00"),
            credit_amount=Decimal("800.04"),
            charge_amount=Decimal("1200.06"),
            proration_amount=Decimal("400.02"),
        )
    )

    assert "remaining_days_within_cycle" in await _expect_integrity_error(db_session)


# --- Upsell ----------------------------------------------------------------


async def test_product_cannot_upsell_itself(db_session: AsyncSession, product: Product) -> None:
    db_session.add(
        UpsellRule(
            trigger_product_id=product.id,
            suggested_product_id=product.id,
            co_purchase_score=Decimal("5.00"),
        )
    )

    assert "trigger_differs_from_suggested" in await _expect_integrity_error(db_session)


# --- Audit columns and optimistic locking ----------------------------------


async def test_audit_timestamps_are_populated_by_the_database(
    db_session: AsyncSession, quotation: Quotation
) -> None:
    """created_at/updated_at come from server defaults, so a row inserted by
    raw SQL or a migration still gets them."""
    await db_session.refresh(quotation)

    assert quotation.created_at is not None
    assert quotation.updated_at is not None


async def test_quotation_version_column_supports_optimistic_locking(
    db_session: AsyncSession, quotation: Quotation
) -> None:
    """PLAN.md Section 14: two managers approving the same quote at once must
    not silently last-write-win. SQLAlchemy bumps `version` on every update
    and refuses a write whose version is stale."""
    await db_session.refresh(quotation)
    assert quotation.version == 1

    quotation.status = "pending_approval"
    await db_session.flush()

    assert quotation.version == 2
