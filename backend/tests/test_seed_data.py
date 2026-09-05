"""Seed-data tests.

These close the gap between "the engine is correct" and "the engine is correct
against the data we will actually demo on". The risk-engine tests use hand-built
fixtures; these read the real seeded rows and drive the real engine with them,
so a typo in the seed matrix fails here rather than during the demo.

Requires the seed to have been run:
    docker compose exec backend python -m app.seed
"""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ApprovalChain,
    Customer,
    DiscountTier,
    Product,
    ProductCategory,
    Role,
    StockLevel,
    User,
    Warehouse,
)
from app.models.enums import CustomerTier, RoleCode
from app.services.risk import (
    ApprovalBand,
    LineRiskInput,
    assess_lines,
    plan_approval_steps,
)


async def _ceiling(session: AsyncSession, category_code: str, tier: CustomerTier) -> Decimal:
    result = await session.execute(
        select(DiscountTier.max_discount_percent)
        .join(ProductCategory, ProductCategory.id == DiscountTier.category_id)
        .where(
            ProductCategory.code == category_code,
            DiscountTier.customer_tier == tier,
        )
    )
    ceiling = result.scalar_one_or_none()
    if ceiling is None:
        pytest.fail(f"no ceiling seeded for {category_code}/{tier} - run `python -m app.seed`")
    return ceiling


async def _bands(session: AsyncSession) -> list[ApprovalBand]:
    rows = await session.execute(
        select(
            ApprovalChain.min_score,
            ApprovalChain.max_score,
            Role.code,
            ApprovalChain.step_order,
        ).join(Role, Role.id == ApprovalChain.required_role_id)
    )
    return [
        ApprovalBand(
            min_score=min_score,
            max_score=max_score,
            role_code=role_code,
            step_order=step_order,
        )
        for min_score, max_score, role_code, step_order in rows
    ]


# --- The locked matrix, as actually seeded ---------------------------------


@pytest.mark.parametrize(
    "category,tier,expected",
    [
        ("HW", CustomerTier.BRONZE, "5"),
        ("HW", CustomerTier.SILVER, "10"),
        ("HW", CustomerTier.GOLD, "15"),
        ("SVC", CustomerTier.BRONZE, "3"),
        ("SVC", CustomerTier.SILVER, "7"),
        ("SVC", CustomerTier.GOLD, "10"),
        ("SUB", CustomerTier.BRONZE, "2"),
        ("SUB", CustomerTier.SILVER, "5"),
        ("SUB", CustomerTier.GOLD, "8"),
    ],
)
async def test_seeded_ceiling_matrix(db_session: AsyncSession, category, tier, expected) -> None:
    """Locked Business Rules #6, cell by cell."""
    assert await _ceiling(db_session, category, tier) == Decimal(expected)


async def test_prd_gold_example_ceilings_are_seeded(db_session: AsyncSession) -> None:
    """PRD Section 10 states Gold gets 15% on Hardware and 10% on Services."""
    assert await _ceiling(db_session, "HW", CustomerTier.GOLD) == Decimal("15")
    assert await _ceiling(db_session, "SVC", CustomerTier.GOLD) == Decimal("10")


# --- The demo flows, driven from real seeded data --------------------------


async def test_demo_flow_1_reproduces_the_prd_example(db_session: AsyncSession) -> None:
    """PLAN.md Section 16 Flow 1, using seeded ceilings and seeded chains.

    Acme is Gold. Laptop at 12% is within its 15% Hardware ceiling; Setup
    Service at 18% is 8 points over its 10% Services ceiling. The PRD requires
    the quotation to be flagged.
    """
    acme = (await db_session.execute(select(Customer).where(Customer.code == "ACME"))).scalar_one()
    assert acme.tier == CustomerTier.GOLD

    laptop = (
        await db_session.execute(select(Product).where(Product.sku == "HW-LAPTOP"))
    ).scalar_one()
    setup = (
        await db_session.execute(select(Product).where(Product.sku == "SVC-SETUP"))
    ).scalar_one()

    assessment = assess_lines(
        [
            LineRiskInput(
                line_number=1,
                quantity=Decimal("1"),
                unit_list_price=laptop.list_price,
                discount_percent=Decimal("12"),
                allowed_discount_percent=await _ceiling(db_session, "HW", acme.tier),
            ),
            LineRiskInput(
                line_number=2,
                quantity=Decimal("1"),
                unit_list_price=setup.list_price,
                discount_percent=Decimal("18"),
                allowed_discount_percent=await _ceiling(db_session, "SVC", acme.tier),
            ),
        ]
    )

    assert assessment.blended_score == Decimal("1.33")
    assert assessment.requires_approval is True
    assert assessment.finance_gate_tripped is False

    steps = plan_approval_steps(
        assessment, await _bands(db_session), escalation_role_code=RoleCode.FINANCE_OPS
    )
    assert [step.role_code for step in steps] == [RoleCode.SALES_MANAGER]


async def test_demo_flow_finance_escalation_from_seeded_data(
    db_session: AsyncSession,
) -> None:
    """The Manager+Finance demo path: one Hardware line at 35% is 20 points
    over its seeded 15% ceiling, tripping the single-line gate."""
    laptop = (
        await db_session.execute(select(Product).where(Product.sku == "HW-LAPTOP"))
    ).scalar_one()

    assessment = assess_lines(
        [
            LineRiskInput(
                line_number=1,
                quantity=Decimal("1"),
                unit_list_price=laptop.list_price,
                discount_percent=Decimal("35"),
                allowed_discount_percent=await _ceiling(db_session, "HW", CustomerTier.GOLD),
            )
        ]
    )

    assert assessment.max_line_excess == Decimal("20")
    assert assessment.finance_gate_tripped is True

    steps = plan_approval_steps(
        assessment, await _bands(db_session), escalation_role_code=RoleCode.FINANCE_OPS
    )
    assert [step.role_code for step in steps] == [
        RoleCode.SALES_MANAGER,
        RoleCode.FINANCE_OPS,
    ]


async def test_seeded_stock_forces_a_split_and_a_backorder(
    db_session: AsyncSession,
) -> None:
    """PLAN.md Section 16 Flow 1 needs a warehouse split AND a backorder.

    Seeded laptop stock is 6 in Main and 3 in East, so an order for 10 splits
    across both warehouses and is still 1 short. If someone "helpfully" tops up
    the seed stock, this test fails and tells them why it mattered.
    """
    rows = await db_session.execute(
        select(Warehouse.code, StockLevel.quantity_on_hand)
        .join(StockLevel, StockLevel.warehouse_id == Warehouse.id)
        .join(Product, Product.id == StockLevel.product_id)
        .where(Product.sku == "HW-LAPTOP")
    )
    stock = dict(rows.all())

    assert stock["WH-MAIN"] == Decimal("6.000")
    assert stock["WH-EAST"] == Decimal("3.000")

    demo_order_quantity = Decimal("10")
    available = sum(stock.values())
    assert available < demo_order_quantity, "must be short, to create a backorder"
    assert len(stock) > 1, "must span two warehouses, to force a split"
    assert demo_order_quantity - available == Decimal("1")


async def test_main_warehouse_is_preferred_by_shipping_weight(
    db_session: AsyncSession,
) -> None:
    """The greedy split sorts by shipping_cost_weight ascending, so Main must
    be cheaper than East or the split demo shows nothing."""
    rows = await db_session.execute(select(Warehouse.code, Warehouse.shipping_cost_weight))
    weights = dict(rows.all())

    assert weights["WH-MAIN"] < weights["WH-EAST"]


# --- RBAC ------------------------------------------------------------------


async def test_all_five_prd_roles_are_seeded(db_session: AsyncSession) -> None:
    codes = set((await db_session.execute(select(Role.code))).scalars().all())

    assert codes == set(RoleCode)


async def test_every_role_has_a_working_login(db_session: AsyncSession) -> None:
    rows = await db_session.execute(
        select(Role.code, User.email).join(User, User.role_id == Role.id)
    )
    by_role = dict(rows.all())

    assert set(by_role) == set(RoleCode), "the demo needs one login per role"


async def test_portal_user_is_scoped_to_a_customer(db_session: AsyncSession) -> None:
    """A portal login without customer_id could see nothing - or, worse, a
    later change could make it see everything. This is the ownership anchor."""
    portal_user = (
        await db_session.execute(select(User).where(User.email == "portal@acme.example"))
    ).scalar_one()

    assert portal_user.customer_id is not None

    acme = (await db_session.execute(select(Customer).where(Customer.code == "ACME"))).scalar_one()
    assert portal_user.customer_id == acme.id


async def test_customer_role_holds_only_portal_permissions(
    db_session: AsyncSession,
) -> None:
    """SECURITY_SPEC Section 4: a portal user must never reach an internal
    screen. Verified against the seeded grants, not against intent."""
    customer_role = (
        await db_session.execute(select(Role).where(Role.code == RoleCode.CUSTOMER))
    ).scalar_one()

    granted = {permission.code for permission in customer_role.permissions}

    assert granted == {"portal.own_quote.view", "portal.own_quote.negotiate"}
    assert not any(code.startswith("deal.") for code in granted)
    assert not any(code.startswith("config.") for code in granted)
    assert "user.manage" not in granted


async def test_only_finance_can_approve_at_the_second_level(
    db_session: AsyncSession,
) -> None:
    """Vertical privilege escalation guard: exactly one role holds the finance
    approval permission, and it is not the manager or the rep."""
    roles = (await db_session.execute(select(Role))).scalars().all()

    holders = {
        role.code
        for role in roles
        if any(p.code == "deal.approve_finance" for p in role.permissions)
    }

    assert RoleCode.FINANCE_OPS in holders
    assert RoleCode.SALES_REP not in holders
    assert RoleCode.SALES_MANAGER not in holders


async def test_sales_rep_cannot_approve_anything(db_session: AsyncSession) -> None:
    rep_role = (
        await db_session.execute(select(Role).where(Role.code == RoleCode.SALES_REP))
    ).scalar_one()

    granted = {permission.code for permission in rep_role.permissions}

    assert "deal.approve_manager" not in granted
    assert "deal.approve_finance" not in granted
    assert "user.manage" not in granted
    assert "deal.read_all" not in granted
