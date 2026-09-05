"""`refresh_dashboard` orchestration tests — the DB-touching half of
dealhealth.py, separate from test_dealhealth.py's pure-logic tests."""

import itertools
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Product, ProductCategory, Quotation, QuotationLine, Role, User
from app.models.dealhealth import DealHealthSnapshot
from app.models.enums import CustomerTier, QuotationStatus, RoleCode
from app.services.dealhealth import refresh_dashboard

NOW = datetime.now(UTC)
_counter = itertools.count()


@pytest.fixture
async def rep_role(db_session: AsyncSession) -> Role:
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
async def rep(db_session: AsyncSession, rep_role: Role) -> User:
    user = User(
        email=f"health-rep-{NOW.timestamp()}@example.test",
        password_hash="not-a-real-hash",
        full_name="Test Rep",
        role_id=rep_role.id,
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
async def product(db_session: AsyncSession) -> Product:
    category = ProductCategory(code=f"CAT-{NOW.timestamp()}", name="Hardware")
    db_session.add(category)
    await db_session.flush()
    product = Product(
        sku=f"SKU-{NOW.timestamp()}",
        name="Test Laptop",
        category_id=category.id,
        list_price=Decimal("1000.00"),
        cost_price=Decimal("700.00"),
    )
    db_session.add(product)
    await db_session.flush()
    return product


async def _quotation(
    db_session: AsyncSession,
    customer: Customer,
    rep: User,
    product: Product,
    *,
    status: QuotationStatus,
    discount: str,
    last_activity_at: datetime,
) -> Quotation:
    quotation = Quotation(
        quote_number=f"Q-HEALTH-{NOW.timestamp()}-{next(_counter)}",
        customer_id=customer.id,
        owner_id=rep.id,
        status=status,
        subtotal_amount=Decimal("1000.00"),
        discount_amount=Decimal(discount),
        total_amount=Decimal("1000.00") - Decimal(discount),
        last_activity_at=last_activity_at,
    )
    db_session.add(quotation)
    await db_session.flush()
    db_session.add(
        QuotationLine(
            quotation_id=quotation.id,
            line_number=1,
            product_id=product.id,
            quantity=Decimal("1"),
            unit_list_price=product.list_price,
            unit_cost_price=product.cost_price,
        )
    )
    await db_session.flush()
    return quotation


async def test_stalled_quotation_is_flagged_and_snapshotted(
    db_session: AsyncSession, customer: Customer, rep: User, product: Product
) -> None:
    stale = await _quotation(
        db_session,
        customer,
        rep,
        product,
        status=QuotationStatus.SENT,
        discount="0",
        last_activity_at=NOW - timedelta(days=10),
    )

    results = await refresh_dashboard(db_session, owner_id=rep.id)

    assert len(results) == 1
    assert results[0].quotation.id == stale.id
    assert results[0].is_stalled
    assert results[0].days_inactive >= 7

    snapshot = (
        await db_session.execute(
            select(DealHealthSnapshot).where(DealHealthSnapshot.quotation_id == stale.id)
        )
    ).scalar_one()
    assert snapshot.is_stalled


async def test_fresh_quotation_produces_no_alert(
    db_session: AsyncSession, customer: Customer, rep: User, product: Product
) -> None:
    await _quotation(
        db_session,
        customer,
        rep,
        product,
        status=QuotationStatus.SENT,
        discount="0",
        last_activity_at=NOW,
    )

    results = await refresh_dashboard(db_session, owner_id=rep.id)

    assert results == []


async def test_terminal_status_is_never_flagged_even_if_stale(
    db_session: AsyncSession, customer: Customer, rep: User, product: Product
) -> None:
    """A confirmed order sitting untouched for a month is not "stalled" - it
    is finished. Locked Business Rules #9 excludes terminal statuses."""
    await _quotation(
        db_session,
        customer,
        rep,
        product,
        status=QuotationStatus.CONFIRMED,
        discount="0",
        last_activity_at=NOW - timedelta(days=30),
    )

    results = await refresh_dashboard(db_session, owner_id=rep.id)

    assert results == []


async def test_discount_anomaly_flagged_against_rep_average(
    db_session: AsyncSession, customer: Customer, rep: User, product: Product
) -> None:
    # Baseline: three quotations at a low, consistent discount.
    for _ in range(3):
        await _quotation(
            db_session,
            customer,
            rep,
            product,
            status=QuotationStatus.SENT,
            discount="50.00",  # 5% of 1000
            last_activity_at=NOW,
        )
    # The outlier: a much higher discount, still recently touched (so it is
    # flagged for the anomaly, not for staleness).
    outlier = await _quotation(
        db_session,
        customer,
        rep,
        product,
        status=QuotationStatus.SENT,
        discount="300.00",  # 30% of 1000
        last_activity_at=NOW,
    )

    results = await refresh_dashboard(db_session, owner_id=rep.id)

    outlier_result = next(r for r in results if r.quotation.id == outlier.id)
    assert outlier_result.has_discount_anomaly
    assert outlier_result.discount_vs_rep_average > Decimal("10")
    assert not outlier_result.is_stalled


async def test_owner_scoping_excludes_other_reps(
    db_session: AsyncSession, customer: Customer, rep: User, product: Product, rep_role: Role
) -> None:
    other_rep = User(
        email=f"other-health-rep-{NOW.timestamp()}@example.test",
        password_hash="x",
        full_name="Other Rep",
        role_id=rep_role.id,
    )
    db_session.add(other_rep)
    await db_session.flush()
    await _quotation(
        db_session,
        customer,
        other_rep,
        product,
        status=QuotationStatus.SENT,
        discount="0",
        last_activity_at=NOW - timedelta(days=30),
    )

    results = await refresh_dashboard(db_session, owner_id=rep.id)

    assert results == []
