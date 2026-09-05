"""Quotation totals, margin and live risk recalculation.

One function recalculates everything derived from the lines, and it is the
only place that writes those fields. Totals, margin and risk score must never
disagree with the lines that produced them, and the way that happens is one
writer, called on every mutation.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Product
from app.models.customer import Customer
from app.models.enums import CustomerTier
from app.models.policy import DiscountTier
from app.models.quotation import Quotation, QuotationLine
from app.services.risk import LineRiskInput, RiskAssessment, assess_lines

_MONEY = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


async def ceilings_for_tier(session: AsyncSession, tier: CustomerTier) -> dict[int, Decimal]:
    """The discount ceiling for each product category, for one customer tier.

    Returned as a dict so a quotation with many lines costs one query, not one
    per line.
    """
    rows = await session.execute(
        select(DiscountTier.category_id, DiscountTier.max_discount_percent).where(
            DiscountTier.customer_tier == tier, DiscountTier.is_active.is_(True)
        )
    )
    return {category_id: ceiling for category_id, ceiling in rows.all()}


async def recalculate(session: AsyncSession, quotation: Quotation) -> RiskAssessment:
    """Recompute every derived field on a quotation from its lines.

    Call after ANY change to lines, discounts or the customer. Returns the risk
    assessment so callers that need to route on it do not recompute.
    """
    await session.refresh(quotation, attribute_names=["lines"])

    customer = (
        await session.execute(select(Customer).where(Customer.id == quotation.customer_id))
    ).scalar_one()
    ceilings = await ceilings_for_tier(session, customer.tier)

    product_ids = [line.product_id for line in quotation.lines]
    categories: dict[int, int] = {}
    if product_ids:
        rows = await session.execute(
            select(Product.id, Product.category_id).where(Product.id.in_(product_ids))
        )
        categories = dict(rows.all())

    subtotal = Decimal("0")
    discount_total = Decimal("0")
    tax_total = Decimal("0")
    cost_total = Decimal("0")

    risk_inputs: list[LineRiskInput] = []

    for line in quotation.lines:
        gross = line.quantity * line.unit_list_price
        discount_amount = _money(gross * line.discount_percent / Decimal("100"))
        net = gross - discount_amount
        tax = _money(net * line.tax_rate / Decimal("100"))

        # The ceiling that applies to THIS line, snapshotted onto the row so a
        # later change to policy cannot rewrite what was approved.
        category_id = categories.get(line.product_id)
        ceiling = ceilings.get(category_id, Decimal("0")) if category_id else Decimal("0")
        line.allowed_discount_percent = ceiling
        line.line_excess_points = max(Decimal("0"), line.discount_percent - ceiling)

        line.line_subtotal = _money(gross)
        line.line_discount_amount = discount_amount
        line.line_tax_amount = tax
        line.line_total = _money(net + tax)

        subtotal += gross
        discount_total += discount_amount
        tax_total += tax
        cost_total += line.quantity * line.unit_cost_price

        risk_inputs.append(
            LineRiskInput(
                line_number=line.line_number,
                quantity=line.quantity,
                unit_list_price=line.unit_list_price,
                discount_percent=line.discount_percent,
                allowed_discount_percent=ceiling,
            )
        )

    net_revenue = subtotal - discount_total
    margin = net_revenue - cost_total

    quotation.subtotal_amount = _money(subtotal)
    quotation.discount_amount = _money(discount_total)
    quotation.tax_amount = _money(tax_total)
    quotation.total_amount = _money(net_revenue + tax_total)
    quotation.margin_amount = _money(margin)
    quotation.margin_percent = (
        _money(margin / net_revenue * Decimal("100")) if net_revenue > 0 else Decimal("0")
    )
    quotation.currency = customer.currency

    assessment = assess_lines(risk_inputs)
    quotation.blended_risk_score = assessment.blended_score
    quotation.max_line_excess = assessment.max_line_excess

    await session.flush()
    return assessment


async def load_quotation(session: AsyncSession, quotation_id: int) -> Quotation | None:
    result = await session.execute(
        select(Quotation)
        .where(Quotation.id == quotation_id)
        .options(
            selectinload(Quotation.lines).selectinload(QuotationLine.product),
            selectinload(Quotation.customer),
            selectinload(Quotation.owner),
        )
    )
    return result.scalar_one_or_none()


async def next_quote_number(session: AsyncSession) -> str:
    """Human-readable quotation number.

    Derived from the row count rather than the sequence so the demo produces
    tidy consecutive numbers; uniqueness is still guaranteed by the UNIQUE
    constraint, and a collision under concurrency surfaces as an IntegrityError
    rather than a silently duplicated number.
    """
    count = (await session.execute(select(Quotation.id))).scalars().all()
    return f"Q-{1000 + len(count) + 1}"
