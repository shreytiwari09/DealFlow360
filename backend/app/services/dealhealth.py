"""Deal health and anomaly monitoring (PRD B9).

PROJECT_CONTEXT.md Locked Business Rules #9 is authoritative for the
thresholds; this module is their implementation. Pure calculation first
(`is_stalled`, `discount_anomaly`, `delivery_slippage`), mirroring risk.py's
and fulfillment.py's shape, then the DB orchestration that reads live
quotation/fulfillment state and writes a snapshot row.

No scheduled job exists yet (`PROJECT_CONTEXT.md` "Background Jobs" — still
"not yet implemented"), so `refresh_dashboard()` is called on every dashboard
view rather than by a cron-equivalent process — the same "compute lazily on
the read that needs it" pattern `fulfillment.py` uses for its auto-generated
split.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.dealhealth import DealHealthSnapshot
from app.models.enums import QuotationStatus
from app.models.inventory import Fulfillment
from app.models.quotation import Quotation

# Locked Business Rules #9.
STALLED_THRESHOLD_DAYS = 7
DISCOUNT_ANOMALY_THRESHOLD_POINTS = Decimal("10")
REP_AVERAGE_SAMPLE_SIZE = 20

# A quotation past one of these has nothing left to stall or flag.
_TERMINAL_STATUSES = (
    QuotationStatus.CONFIRMED,
    QuotationStatus.FULFILLED,
    QuotationStatus.REJECTED,
    QuotationStatus.CANCELLED,
)

_PERCENT = Decimal("0.01")


def _percent(value: Decimal) -> Decimal:
    return value.quantize(_PERCENT, rounding=ROUND_HALF_UP)


# --- Pure calculation --------------------------------------------------------


def is_stalled(last_activity_at: datetime, *, now: datetime) -> tuple[bool, int]:
    """PRD B9: "quotations inactive for more than a configured number of
    days." Returns (flagged, days_inactive)."""
    days_inactive = (now.date() - last_activity_at.date()).days
    return days_inactive >= STALLED_THRESHOLD_DAYS, max(0, days_inactive)


def effective_discount_percent(subtotal_amount: Decimal, discount_amount: Decimal) -> Decimal:
    if subtotal_amount <= 0:
        return Decimal("0")
    return _percent(discount_amount / subtotal_amount * Decimal("100"))


def discount_anomaly(
    current_effective_discount: Decimal, rep_average: Decimal | None
) -> tuple[bool, Decimal]:
    """PRD B9: "a discount well above a rep's historical average."

    `rep_average` is `None` when the rep has no other non-draft quotations
    yet — insufficient history to call anything an anomaly, so this always
    returns `(False, 0)` rather than comparing against a fabricated baseline
    of zero (which would flag every rep's very first discounted quote).
    """
    if rep_average is None:
        return False, Decimal("0")
    delta = _percent(current_effective_discount - rep_average)
    return delta > DISCOUNT_ANOMALY_THRESHOLD_POINTS, delta


def delivery_slippage(promised_date: date | None, *, today: date) -> tuple[bool, int]:
    """PRD B9: "delivery promise slippage indicators." No promise, no
    slippage — a quotation with no fulfillment yet (or none with a promised
    date set) cannot have missed one."""
    if promised_date is None or today <= promised_date:
        return False, 0
    return True, (today - promised_date).days


# --- Database orchestration --------------------------------------------------


@dataclass(frozen=True)
class HealthResult:
    quotation: Quotation
    is_stalled: bool
    days_inactive: int
    has_discount_anomaly: bool
    discount_vs_rep_average: Decimal
    has_delivery_slippage: bool
    days_slipped: int


async def _rep_average_discount(
    session: AsyncSession, owner_id: int, *, exclude_quotation_id: int
) -> Decimal | None:
    """The rep's own average effective discount across their most recent
    `REP_AVERAGE_SAMPLE_SIZE` non-draft quotations, excluding the one being
    evaluated. `None` if there is no other history yet."""
    rows = (
        await session.execute(
            select(Quotation.subtotal_amount, Quotation.discount_amount)
            .where(
                Quotation.owner_id == owner_id,
                Quotation.status != QuotationStatus.DRAFT,
                Quotation.id != exclude_quotation_id,
            )
            .order_by(Quotation.created_at.desc())
            .limit(REP_AVERAGE_SAMPLE_SIZE)
        )
    ).all()
    if not rows:
        return None

    discounts = [effective_discount_percent(subtotal, discount) for subtotal, discount in rows]
    return _percent(sum(discounts, Decimal("0")) / len(discounts))


async def _latest_promised_date(session: AsyncSession, quotation_id: int) -> date | None:
    """The most recent fulfillment attempt's promise, if any and if not yet
    fulfilled — a completed fulfillment cannot still be "at risk"."""
    result = await session.execute(
        select(Fulfillment.promised_date, Fulfillment.status)
        .where(Fulfillment.quotation_id == quotation_id)
        .order_by(Fulfillment.id.desc())
        .limit(1)
    )
    row = result.first()
    if row is None or row.status == "fulfilled":
        return None
    return row.promised_date


async def refresh_dashboard(session: AsyncSession, *, owner_id: int | None) -> list[HealthResult]:
    """Recompute health for every open quotation and write one snapshot row
    each. `owner_id` scopes to one rep's own deals (mirrors the quotations
    list's own ownership scoping); `None` means "every open quotation" for a
    manager/finance/admin view.
    """
    now = datetime.now(UTC)
    statement = (
        select(Quotation)
        .where(Quotation.status.notin_(_TERMINAL_STATUSES))
        .options(selectinload(Quotation.customer), selectinload(Quotation.owner))
    )
    if owner_id is not None:
        statement = statement.where(Quotation.owner_id == owner_id)

    quotations = (await session.execute(statement)).scalars().all()

    results: list[HealthResult] = []
    for quotation in quotations:
        stalled, days_inactive = is_stalled(quotation.last_activity_at, now=now)

        anomaly = False
        vs_average = Decimal("0")
        if quotation.status != QuotationStatus.DRAFT:
            rep_average = await _rep_average_discount(
                session, quotation.owner_id, exclude_quotation_id=quotation.id
            )
            current = effective_discount_percent(
                quotation.subtotal_amount, quotation.discount_amount
            )
            anomaly, vs_average = discount_anomaly(current, rep_average)

        promised = await _latest_promised_date(session, quotation.id)
        slipped, days_slipped = delivery_slippage(promised, today=now.date())

        if not (stalled or anomaly or slipped):
            continue  # only alerts are worth a snapshot row and a dashboard entry

        session.add(
            DealHealthSnapshot(
                quotation_id=quotation.id,
                snapshot_at=now,
                is_stalled=stalled,
                days_inactive=days_inactive,
                has_discount_anomaly=anomaly,
                discount_vs_rep_average=vs_average,
                has_delivery_slippage=slipped,
                days_slipped=days_slipped,
                created_by=quotation.owner_id,
            )
        )
        results.append(
            HealthResult(
                quotation=quotation,
                is_stalled=stalled,
                days_inactive=days_inactive,
                has_discount_anomaly=anomaly,
                discount_vs_rep_average=vs_average,
                has_delivery_slippage=slipped,
                days_slipped=days_slipped,
            )
        )

    await session.flush()
    return results
