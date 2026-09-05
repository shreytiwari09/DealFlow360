"""Warehouse split and backorder tests.

Two layers, matching risk.py's testing style:

  * `compute_split()` is pure - tested in isolation with hand-built
    candidates, no database at all.
  * The orchestration functions (`generate_fulfillment`, `accept_fulfillment`,
    `override_fulfillment`, `consolidate_backorder`) are tested against the
    real PostgreSQL schema, because the property under test - that stock
    reservation is atomic and the CHECK constraints hold - is only meaningful
    against the engine actually shipped.
"""

from datetime import UTC, datetime
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
    User,
    Warehouse,
)
from app.models.enums import CustomerTier, QuotationStatus, RoleCode
from app.models.inventory import StockLevel
from app.services.fulfillment import (
    FulfillmentError,
    LineAllocation,
    WarehouseCandidate,
    accept_fulfillment,
    compute_split,
    estimate_shipping_cost,
    generate_fulfillment,
    override_fulfillment,
)

NOW = datetime.now(UTC)


def _candidate(warehouse_id: int, weight: str, available: str) -> WarehouseCandidate:
    return WarehouseCandidate(
        warehouse_id=warehouse_id,
        shipping_cost_weight=Decimal(weight),
        available=Decimal(available),
    )


# ---------------------------------------------------------------------------
# Pure algorithm
# ---------------------------------------------------------------------------


def test_single_warehouse_fully_covers() -> None:
    result = compute_split(Decimal("5"), [_candidate(1, "1", "10")])

    assert result.is_fully_covered
    assert result.allocations == (LineAllocation(warehouse_id=1, quantity=Decimal("5")),)
    assert result.backordered_quantity == Decimal("0")


def test_the_staged_demo_scenario_exactly() -> None:
    """The seed's own numbers: Main has 6, East has 3, order is for 10."""
    result = compute_split(
        Decimal("10"),
        [_candidate(1, "1.00", "6"), _candidate(2, "1.50", "3")],
    )

    assert result.allocations == (
        LineAllocation(warehouse_id=1, quantity=Decimal("6")),
        LineAllocation(warehouse_id=2, quantity=Decimal("3")),
    )
    assert result.backordered_quantity == Decimal("1")
    assert not result.is_fully_covered


def test_cheapest_warehouse_is_preferred_even_with_less_stock() -> None:
    """Shipping weight is the PRIMARY sort key, not stock quantity."""
    result = compute_split(
        Decimal("4"),
        [_candidate(1, "5.00", "100"), _candidate(2, "1.00", "4")],
    )

    assert result.allocations == (LineAllocation(warehouse_id=2, quantity=Decimal("4")),)


def test_tie_break_by_available_stock_when_weights_equal() -> None:
    """Equal weight -> prefer whichever warehouse has more stock (fewer
    warehouses touched -> fewer shipments, PRD A4's stated goal)."""
    result = compute_split(
        Decimal("3"),
        [_candidate(1, "1.00", "5"), _candidate(2, "1.00", "20")],
    )

    assert result.allocations == (LineAllocation(warehouse_id=2, quantity=Decimal("3")),)


def test_tie_break_by_warehouse_id_is_the_final_deterministic_key() -> None:
    """Equal weight AND equal stock -> lowest id wins.

    This is the property that keeps a demo's split identical across repeated
    runs; without it, two ties resolve arbitrarily.
    """
    result = compute_split(
        Decimal("2"),
        [_candidate(5, "1.00", "10"), _candidate(2, "1.00", "10"), _candidate(3, "1.00", "10")],
    )

    assert result.allocations[0].warehouse_id == 2


def test_zero_candidates_is_fully_backordered() -> None:
    result = compute_split(Decimal("5"), [])

    assert result.allocations == ()
    assert result.backordered_quantity == Decimal("5")


def test_zero_stock_everywhere_is_fully_backordered() -> None:
    result = compute_split(Decimal("5"), [_candidate(1, "1", "0"), _candidate(2, "1", "0")])

    assert result.backordered_quantity == Decimal("5")
    assert result.allocations == ()


def test_negative_available_is_treated_as_nothing_available() -> None:
    """Defensive: available should never be negative given the CHECK
    constraint `reserved <= on_hand`, but the pure function must not misbehave
    if it somehow is (e.g. a stale read)."""
    result = compute_split(Decimal("3"), [_candidate(1, "1", "-2")])

    assert result.backordered_quantity == Decimal("3")


def test_exact_match_leaves_nothing_available_and_no_backorder() -> None:
    result = compute_split(Decimal("6"), [_candidate(1, "1", "6")])

    assert result.is_fully_covered
    assert result.allocations[0].quantity == Decimal("6")


def test_three_warehouses_needed() -> None:
    result = compute_split(
        Decimal("10"),
        [_candidate(1, "1", "3"), _candidate(2, "2", "3"), _candidate(3, "3", "3")],
    )

    assert [a.quantity for a in result.allocations] == [Decimal("3"), Decimal("3"), Decimal("3")]
    assert result.backordered_quantity == Decimal("1")


def test_estimate_shipping_cost_sums_quantity_times_weight() -> None:
    allocations = (
        LineAllocation(warehouse_id=1, quantity=Decimal("6")),
        LineAllocation(warehouse_id=2, quantity=Decimal("3")),
    )
    cost = estimate_shipping_cost(allocations, {1: Decimal("1.00"), 2: Decimal("1.50")})

    assert cost == Decimal("6.00") + Decimal("4.50")


def test_estimate_shipping_cost_of_no_allocations_is_zero() -> None:
    assert estimate_shipping_cost((), {}) == Decimal("0")


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
        email=f"fulfil-{NOW.timestamp()}@example.test",
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
        name="Test Laptop",
        category_id=category.id,
        list_price=Decimal("100000.00"),
        cost_price=Decimal("70000.00"),
    )
    db_session.add(product)
    await db_session.flush()
    return product


@pytest.fixture
async def two_warehouses(db_session: AsyncSession) -> tuple[Warehouse, Warehouse]:
    main = Warehouse(code=f"MAIN-{NOW.timestamp()}", name="Main", shipping_cost_weight=Decimal("1"))
    east = Warehouse(
        code=f"EAST-{NOW.timestamp()}", name="East", shipping_cost_weight=Decimal("1.5")
    )
    db_session.add_all([main, east])
    await db_session.flush()
    return main, east


@pytest.fixture
async def stocked_product(
    db_session: AsyncSession,
    product: Product,
    two_warehouses: tuple[Warehouse, Warehouse],
) -> Product:
    """The product from `product`, stocked 6 in the first warehouse, 3 in the
    second - the exact staged demo numbers, reused here against a real
    isolated fixture rather than the shared seed data."""
    main, east = two_warehouses
    db_session.add_all(
        [
            StockLevel(warehouse_id=main.id, product_id=product.id, quantity_on_hand=Decimal("6")),
            StockLevel(warehouse_id=east.id, product_id=product.id, quantity_on_hand=Decimal("3")),
        ]
    )
    await db_session.flush()
    return product


@pytest.fixture
async def confirmed_quotation(
    db_session: AsyncSession, customer: Customer, user: User, stocked_product: Product
) -> Quotation:
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
            product_id=stocked_product.id,
            quantity=Decimal("10"),
            unit_list_price=stocked_product.list_price,
            unit_cost_price=stocked_product.cost_price,
        )
    )
    await db_session.flush()
    await db_session.refresh(quotation, attribute_names=["lines"])
    return quotation


async def test_generate_requires_confirmed_status(
    db_session: AsyncSession, customer: Customer, user: User
) -> None:
    draft = Quotation(
        quote_number=f"Q-DRAFT-{NOW.timestamp()}",
        customer_id=customer.id,
        owner_id=user.id,
        status=QuotationStatus.DRAFT,
    )
    db_session.add(draft)
    await db_session.flush()

    with pytest.raises(FulfillmentError, match="confirmed"):
        await generate_fulfillment(db_session, draft, actor_id=user.id)


async def test_generate_reproduces_the_staged_demo_split(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    fulfillment = await generate_fulfillment(db_session, confirmed_quotation, actor_id=user.id)

    quantities = sorted(split.quantity for split in fulfillment.splits)
    assert quantities == [Decimal("3"), Decimal("6")]
    assert len(fulfillment.backorders) == 1
    assert fulfillment.backorders[0].quantity_outstanding == Decimal("1")
    assert fulfillment.shipment_count == 2


async def test_generate_actually_reserves_stock(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User, two_warehouses
) -> None:
    await generate_fulfillment(db_session, confirmed_quotation, actor_id=user.id)

    main, east = two_warehouses
    main_stock = (
        await db_session.execute(select(StockLevel).where(StockLevel.warehouse_id == main.id))
    ).scalar_one()
    east_stock = (
        await db_session.execute(select(StockLevel).where(StockLevel.warehouse_id == east.id))
    ).scalar_one()

    assert main_stock.quantity_reserved == Decimal("6")
    assert east_stock.quantity_reserved == Decimal("3")


async def test_cannot_generate_twice_for_the_same_quotation(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    await generate_fulfillment(db_session, confirmed_quotation, actor_id=user.id)

    with pytest.raises(FulfillmentError, match="already exists"):
        await generate_fulfillment(db_session, confirmed_quotation, actor_id=user.id)


async def test_accept_moves_to_partially_fulfilled_when_backorder_remains(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User
) -> None:
    fulfillment = await generate_fulfillment(db_session, confirmed_quotation, actor_id=user.id)

    await accept_fulfillment(db_session, fulfillment)

    assert fulfillment.status == "partially_fulfilled"
    # The quotation itself must NOT jump to fulfilled while a unit is still owed.
    await db_session.refresh(confirmed_quotation)
    assert confirmed_quotation.status == QuotationStatus.CONFIRMED


async def test_accept_moves_to_fulfilled_when_fully_covered(
    db_session: AsyncSession,
    customer: Customer,
    user: User,
    category: ProductCategory,
    two_warehouses,
) -> None:
    main, _east = two_warehouses
    product = Product(
        sku=f"SKU-PLENTY-{NOW.timestamp()}",
        name="Plentiful Widget",
        category_id=category.id,
        list_price=Decimal("100.00"),
        cost_price=Decimal("50.00"),
    )
    db_session.add(product)
    await db_session.flush()
    db_session.add(
        StockLevel(warehouse_id=main.id, product_id=product.id, quantity_on_hand=Decimal("50"))
    )

    quotation = Quotation(
        quote_number=f"Q-PLENTY-{NOW.timestamp()}",
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
            product_id=product.id,
            quantity=Decimal("5"),
            unit_list_price=product.list_price,
            unit_cost_price=product.cost_price,
        )
    )
    await db_session.flush()
    await db_session.refresh(quotation, attribute_names=["lines"])

    fulfillment = await generate_fulfillment(db_session, quotation, actor_id=user.id)
    assert not fulfillment.backorders

    await accept_fulfillment(db_session, fulfillment)

    assert fulfillment.status == "fulfilled"
    await db_session.refresh(quotation)
    assert quotation.status == QuotationStatus.FULFILLED


async def test_non_stocked_product_produces_no_splits_or_backorders(
    db_session: AsyncSession, customer: Customer, user: User, category: ProductCategory
) -> None:
    """A Service with no stock_levels rows at all needs no warehouse."""
    service = Product(
        sku=f"SVC-{NOW.timestamp()}",
        name="Consulting Hour",
        category_id=category.id,
        list_price=Decimal("5000.00"),
        cost_price=Decimal("2000.00"),
    )
    db_session.add(service)
    await db_session.flush()

    quotation = Quotation(
        quote_number=f"Q-SVC-{NOW.timestamp()}",
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
            product_id=service.id,
            quantity=Decimal("1"),
            unit_list_price=service.list_price,
            unit_cost_price=service.cost_price,
        )
    )
    await db_session.flush()
    await db_session.refresh(quotation, attribute_names=["lines"])

    fulfillment = await generate_fulfillment(db_session, quotation, actor_id=user.id)

    assert fulfillment.splits == []
    assert fulfillment.backorders == []
    assert fulfillment.shipment_count == 0


async def test_override_releases_old_reservation_before_reserving_new(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User, two_warehouses
) -> None:
    main, east = two_warehouses
    fulfillment = await generate_fulfillment(db_session, confirmed_quotation, actor_id=user.id)
    line_id = confirmed_quotation.lines[0].id

    # Override the East allocation (3 units) down to only 1, freeing up 2.
    await override_fulfillment(
        db_session,
        fulfillment,
        lines=[
            (line_id, main.id, Decimal("6")),
            (line_id, east.id, Decimal("1")),
        ],
        actor_id=user.id,
    )

    east_stock = (
        await db_session.execute(select(StockLevel).where(StockLevel.warehouse_id == east.id))
    ).scalar_one()
    assert east_stock.quantity_reserved == Decimal("1")

    # The 3 units no longer covered by the override (10 - 6 - 1 = 3) must
    # appear as a backorder rather than silently vanishing.
    await db_session.refresh(fulfillment, attribute_names=["backorders"])
    assert sum(b.quantity_outstanding for b in fulfillment.backorders) == Decimal("3")


async def test_override_rejects_a_quantity_the_warehouse_does_not_have(
    db_session: AsyncSession, confirmed_quotation: Quotation, user: User, two_warehouses
) -> None:
    main, _east = two_warehouses
    fulfillment = await generate_fulfillment(db_session, confirmed_quotation, actor_id=user.id)
    line_id = confirmed_quotation.lines[0].id

    with pytest.raises(FulfillmentError, match="available"):
        await override_fulfillment(
            db_session,
            fulfillment,
            lines=[(line_id, main.id, Decimal("999"))],
            actor_id=user.id,
        )
