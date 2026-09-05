"""Multi-warehouse fulfillment splitting and backorders (PRD B6).

PROJECT_CONTEXT.md "Locked Business Rules" is authoritative for the warehouse
selection tie-break and the trigger point (a quotation must be CONFIRMED
before a split can be generated). This module is their implementation.

Split into two halves, mirroring risk.py's shape:

  * `compute_split()` is pure - no database, no I/O. It takes a requested
    quantity and a list of candidate warehouses and returns which warehouse
    supplies how much, plus whatever is left over as a backorder. Kept pure
    so the algorithm itself is unit-testable without a database.

  * The `generate_fulfillment` / `accept_fulfillment` / `override_fulfillment`
    functions are the database-touching orchestration layer: they lock stock
    rows, call the pure function, and persist the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import BackorderStatus, FulfillmentStatus, QuotationStatus
from app.models.inventory import Backorder, Fulfillment, FulfillmentSplit, StockLevel, Warehouse
from app.models.quotation import Quotation, QuotationLine
from app.services.state_machine import InvalidStateTransition, assert_transition

# --- Pure algorithm ---------------------------------------------------------


@dataclass(frozen=True)
class WarehouseCandidate:
    warehouse_id: int
    shipping_cost_weight: Decimal
    # quantity_on_hand - quantity_reserved, as of the moment this was read.
    available: Decimal


@dataclass(frozen=True)
class LineAllocation:
    warehouse_id: int
    quantity: Decimal


@dataclass(frozen=True)
class SplitResult:
    allocations: tuple[LineAllocation, ...]
    # Whatever could not be sourced from any candidate warehouse.
    backordered_quantity: Decimal

    @property
    def is_fully_covered(self) -> bool:
        return self.backordered_quantity == 0


def compute_split(requested_quantity: Decimal, candidates: list[WarehouseCandidate]) -> SplitResult:
    """Greedy warehouse fill.

    Tie-break order (PROJECT_CONTEXT.md Known Issues, the warehouse selection
    rule): lowest shipping cost weight first, then highest available stock
    (fewer warehouses touched -> fewer shipments, which is the whole point of
    the weight PRD A4 asks for), then lowest warehouse id as the final,
    purely mechanical tiebreak. That last key is not cosmetic - without it the
    split is non-deterministic across runs whenever two warehouses tie
    exactly on the first two keys, and a split that differs between two
    otherwise-identical demo runs is worse than a merely suboptimal one.
    """
    ordered = sorted(
        candidates,
        key=lambda c: (c.shipping_cost_weight, -c.available, c.warehouse_id),
    )

    remaining = requested_quantity
    allocations: list[LineAllocation] = []

    for candidate in ordered:
        if remaining <= 0:
            break
        if candidate.available <= 0:
            continue
        take = min(remaining, candidate.available)
        allocations.append(LineAllocation(warehouse_id=candidate.warehouse_id, quantity=take))
        remaining -= take

    return SplitResult(
        allocations=tuple(allocations),
        backordered_quantity=max(Decimal("0"), remaining),
    )


def estimate_shipping_cost(
    allocations: tuple[LineAllocation, ...], weight_by_warehouse: dict[int, Decimal]
) -> Decimal:
    """A simple, explainable cost proxy: quantity x that warehouse's weight,
    summed. The PRD does not specify a real costing model, and the weight
    column is explicitly "used by the auto split logic to minimise shipments"
    (PRD A4) rather than defined as a currency figure - this keeps the number
    on screen consistent with the same weight driving the split decision,
    without inventing a shipping-rate table the PRD never asked for.
    """
    return sum(
        (weight_by_warehouse[a.warehouse_id] * a.quantity for a in allocations),
        start=Decimal("0"),
    )


# --- Database orchestration -------------------------------------------------


class FulfillmentError(Exception):
    """A fulfillment action was attempted in an invalid state."""


async def load_fulfillment(session: AsyncSession, quotation_id: int) -> Fulfillment | None:
    """The most recent fulfillment attempt for a quotation, if any.

    A quotation could in principle have more than one Fulfillment row over
    its life (a rejected/cancelled attempt followed by a fresh one), so this
    picks the latest rather than assuming exactly one.
    """
    result = await session.execute(
        select(Fulfillment)
        .where(Fulfillment.quotation_id == quotation_id)
        .options(
            selectinload(Fulfillment.splits).selectinload(FulfillmentSplit.warehouse),
            selectinload(Fulfillment.splits).selectinload(FulfillmentSplit.quotation_line),
            selectinload(Fulfillment.backorders).selectinload(Backorder.quotation_line),
        )
        .order_by(Fulfillment.id.desc())
    )
    return result.scalars().first()


async def _lock_stock_for_product(
    session: AsyncSession, product_id: int
) -> list[tuple[StockLevel, Decimal]]:
    """Row-lock every stock row for one product, across all warehouses.

    `ORDER BY warehouse_id` before `FOR UPDATE` gives every concurrent caller
    the same lock acquisition order for the same product, which is what
    prevents a classic deadlock: two transactions each holding one row and
    waiting on the other's row would deadlock if they locked in different
    orders. Locking is the entire reason this cannot be a single indexed
    read - two confirmations racing on the last unit of stock must not both
    read "1 available" and both reserve it.
    """
    result = await session.execute(
        select(StockLevel, Warehouse.shipping_cost_weight)
        .join(Warehouse, Warehouse.id == StockLevel.warehouse_id)
        .where(StockLevel.product_id == product_id, StockLevel.variant_id.is_(None))
        .order_by(StockLevel.warehouse_id)
        .with_for_update(of=StockLevel)
    )
    return list(result.all())


async def generate_fulfillment(
    session: AsyncSession, quotation: Quotation, *, actor_id: int
) -> Fulfillment:
    """Compute AND RESERVE a suggested warehouse split for a confirmed quotation.

    Reservation happens here, at generation time, inside the same locked
    transaction as the computation - not deferred to "accept". A suggestion
    that only reserved on accept would leave a window between "here is what
    we can offer" and "we actually hold it", during which a second
    confirmation could see the same nominally-available stock and also get
    offered it. Reserving immediately is what makes the suggestion binding.

    A line whose product has no `stock_levels` rows at all (a Service or a
    Subscription - nothing physical to ship) is skipped entirely: it needs no
    warehouse and cannot backorder.

    Raises `FulfillmentError` if the quotation is not in a state that may be
    fulfilled, or if a fulfillment already exists for it.
    """
    if quotation.status != QuotationStatus.CONFIRMED:
        raise FulfillmentError(
            f"Quotation must be confirmed before fulfillment; it is '{quotation.status}'."
        )

    existing = await load_fulfillment(session, quotation.id)
    if existing is not None:
        raise FulfillmentError("A fulfillment already exists for this quotation.")

    fulfillment = Fulfillment(
        quotation_id=quotation.id,
        status=FulfillmentStatus.PENDING,
        created_by=actor_id,
    )
    session.add(fulfillment)
    await session.flush()

    weight_by_warehouse: dict[int, Decimal] = {}
    all_allocations: list[LineAllocation] = []

    for line in quotation.lines:
        rows = await _lock_stock_for_product(session, line.product_id)
        if not rows:
            continue  # non-stocked line - nothing to fulfill from a warehouse

        candidates = [
            WarehouseCandidate(
                warehouse_id=stock.warehouse_id,
                shipping_cost_weight=weight,
                available=stock.quantity_on_hand - stock.quantity_reserved,
            )
            for stock, weight in rows
        ]
        stock_by_warehouse = {stock.warehouse_id: stock for stock, _ in rows}
        for stock, weight in rows:
            weight_by_warehouse[stock.warehouse_id] = weight

        result = compute_split(line.quantity, candidates)

        for allocation in result.allocations:
            stock_by_warehouse[allocation.warehouse_id].quantity_reserved += allocation.quantity
            session.add(
                FulfillmentSplit(
                    fulfillment_id=fulfillment.id,
                    quotation_line_id=line.id,
                    warehouse_id=allocation.warehouse_id,
                    quantity=allocation.quantity,
                    created_by=actor_id,
                )
            )
        all_allocations.extend(result.allocations)

        if result.backordered_quantity > 0:
            session.add(
                Backorder(
                    fulfillment_id=fulfillment.id,
                    quotation_line_id=line.id,
                    quantity_outstanding=result.backordered_quantity,
                    status=BackorderStatus.OPEN,
                    created_by=actor_id,
                )
            )

    fulfillment.shipment_count = len({a.warehouse_id for a in all_allocations})
    fulfillment.estimated_shipping_cost = estimate_shipping_cost(
        tuple(all_allocations), weight_by_warehouse
    )
    await session.flush()

    # Every split/backorder above was added via `session.add(...)`, not via
    # `fulfillment.splits.append(...)`, so the in-memory collection on this
    # object is still whatever it was when the row was created (empty). A
    # caller reading `.splits`/`.backorders` on the returned object without
    # this refresh would trigger a lazy load outside of a sync context and
    # raise MissingGreenlet - the same failure class fixed earlier in
    # auth.py's `_USER_LOADS`. The API layer happens to re-query afterward
    # and never hit this, which is exactly how it stayed hidden.
    await session.refresh(fulfillment, attribute_names=["splits", "backorders"])
    return fulfillment


def _resolve_status(fulfillment: Fulfillment) -> FulfillmentStatus:
    """What the fulfillment's status should become once finalized.

    Fully covered (no open backorder anywhere) -> FULFILLED.
    Nothing at all was allocated (every unit backordered) -> BACKORDERED.
    Some allocated, some backordered -> PARTIALLY_FULFILLED.
    """
    has_open_backorder = any(b.status == BackorderStatus.OPEN for b in fulfillment.backorders)
    if not has_open_backorder:
        return FulfillmentStatus.FULFILLED
    if not fulfillment.splits:
        return FulfillmentStatus.BACKORDERED
    return FulfillmentStatus.PARTIALLY_FULFILLED


async def accept_fulfillment(session: AsyncSession, fulfillment: Fulfillment) -> None:
    """Confirm the suggested (or overridden) split as final.

    Stock was already reserved at generation time, so this is a pure status
    transition - no stock movement happens here. The quotation only moves to
    `fulfilled` when the fulfillment itself is fully covered; a partial split
    leaves the quotation at `confirmed` until any backorder is consolidated.
    """
    target = _resolve_status(fulfillment)
    try:
        assert_transition("Fulfillment", FulfillmentStatus(fulfillment.status), target)
    except InvalidStateTransition as exc:
        raise FulfillmentError(str(exc)) from exc

    fulfillment.status = target
    if target == FulfillmentStatus.FULFILLED:
        fulfillment.completed_at = datetime.now(UTC)
        quotation = await session.get(Quotation, fulfillment.quotation_id)
        assert_transition("Quotation", QuotationStatus(quotation.status), QuotationStatus.FULFILLED)
        quotation.status = QuotationStatus.FULFILLED
        quotation.last_activity_at = datetime.now(UTC)

    await session.flush()


async def override_fulfillment(
    session: AsyncSession,
    fulfillment: Fulfillment,
    *,
    lines: list[tuple[int, int, Decimal]],  # (quotation_line_id, warehouse_id, quantity)
    actor_id: int,
) -> None:
    """Replace the split with a manually chosen distribution.

    Releases every reservation this fulfillment currently holds, then
    re-reserves according to the caller's chosen distribution - both inside
    the same locked transaction, so the release-then-reserve is atomic from
    any other transaction's point of view; nobody else's concurrent read can
    observe the stock in the brief moment between "released" and
    "re-reserved".

    Any quantity in the affected lines not covered by the override becomes
    (or remains) a backorder.
    """
    if fulfillment.status not in (FulfillmentStatus.PENDING, FulfillmentStatus.PARTIALLY_FULFILLED):
        raise FulfillmentError("Only a pending or partially fulfilled split can be overridden.")

    touched_line_ids = {line_id for line_id, _, _ in lines}

    # Release existing reservations for the lines being overridden.
    for split in list(fulfillment.splits):
        if split.quotation_line_id not in touched_line_ids:
            continue
        stock = (
            await session.execute(
                select(StockLevel)
                .where(
                    StockLevel.warehouse_id == split.warehouse_id,
                    StockLevel.product_id
                    == (await session.get(QuotationLine, split.quotation_line_id)).product_id,
                    StockLevel.variant_id.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one()
        stock.quantity_reserved -= split.quantity
        await session.delete(split)

    for backorder in list(fulfillment.backorders):
        if backorder.quotation_line_id in touched_line_ids:
            await session.delete(backorder)

    await session.flush()

    # Re-reserve per the caller's chosen distribution, validating live stock
    # under lock so an override cannot itself oversell.
    requested_by_line: dict[int, Decimal] = {}
    for line_id, warehouse_id, quantity in lines:
        if quantity <= 0:
            continue
        stock = (
            await session.execute(
                select(StockLevel)
                .where(
                    StockLevel.warehouse_id == warehouse_id,
                    StockLevel.product_id == (await session.get(QuotationLine, line_id)).product_id,
                    StockLevel.variant_id.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if stock is None:
            raise FulfillmentError(f"Warehouse {warehouse_id} does not stock this product.")
        available = stock.quantity_on_hand - stock.quantity_reserved
        if quantity > available:
            raise FulfillmentError(
                f"Only {available} available at warehouse {warehouse_id}, requested {quantity}."
            )
        stock.quantity_reserved += quantity
        session.add(
            FulfillmentSplit(
                fulfillment_id=fulfillment.id,
                quotation_line_id=line_id,
                warehouse_id=warehouse_id,
                quantity=quantity,
                is_manual_override=True,
                created_by=actor_id,
            )
        )
        requested_by_line[line_id] = requested_by_line.get(line_id, Decimal("0")) + quantity

    # Any shortfall against the line's actual ordered quantity is a backorder.
    for line_id in touched_line_ids:
        line = await session.get(QuotationLine, line_id)
        covered = requested_by_line.get(line_id, Decimal("0"))
        shortfall = line.quantity - covered
        if shortfall > 0:
            session.add(
                Backorder(
                    fulfillment_id=fulfillment.id,
                    quotation_line_id=line_id,
                    quantity_outstanding=shortfall,
                    status=BackorderStatus.OPEN,
                    created_by=actor_id,
                )
            )

    fulfillment.is_manual_override = True
    await session.flush()

    await session.refresh(fulfillment, attribute_names=["splits", "backorders"])
    fulfillment.shipment_count = len({split.warehouse_id for split in fulfillment.splits})
    await session.flush()


async def consolidate_backorder(
    session: AsyncSession, fulfillment: Fulfillment, backorder: Backorder, *, actor_id: int
) -> None:
    """PRD B6: "If stock arrives mid fulfillment, a Consolidate Remaining
    Backorder prompt appears automatically."

    The "appears automatically" half (detecting a restock and prompting
    without a user checking) needs a background job and is not built yet -
    see PROJECT_CONTEXT.md Known Issues. This function is the action the
    prompt would trigger: given a still-open backorder, check whether enough
    stock now exists anywhere to cover it, and if so, allocate it.

    All-or-nothing: a partial restock that cannot fully cover the backorder
    leaves it open rather than silently shrinking it, so `quantity_outstanding`
    always means exactly what it says.
    """
    if backorder.status != BackorderStatus.OPEN:
        raise FulfillmentError("This backorder is not open.")

    line = await session.get(QuotationLine, backorder.quotation_line_id)
    rows = await _lock_stock_for_product(session, line.product_id)
    if not rows:
        raise FulfillmentError("This product is not stocked in any warehouse.")

    candidates = [
        WarehouseCandidate(
            warehouse_id=stock.warehouse_id,
            shipping_cost_weight=weight,
            available=stock.quantity_on_hand - stock.quantity_reserved,
        )
        for stock, weight in rows
    ]
    result = compute_split(backorder.quantity_outstanding, candidates)
    if not result.is_fully_covered:
        raise FulfillmentError(f"Not enough stock yet: still short {result.backordered_quantity}.")

    stock_by_warehouse = {stock.warehouse_id: stock for stock, _ in rows}
    for allocation in result.allocations:
        stock_by_warehouse[allocation.warehouse_id].quantity_reserved += allocation.quantity
        session.add(
            FulfillmentSplit(
                fulfillment_id=fulfillment.id,
                quotation_line_id=line.id,
                warehouse_id=allocation.warehouse_id,
                quantity=allocation.quantity,
                created_by=actor_id,
            )
        )

    assert_transition("Backorder", BackorderStatus(backorder.status), BackorderStatus.CONSOLIDATED)
    backorder.status = BackorderStatus.CONSOLIDATED
    await session.flush()

    await session.refresh(fulfillment, attribute_names=["splits", "backorders"])
    fulfillment.shipment_count = len({split.warehouse_id for split in fulfillment.splits})
    # If every unit is now accounted for, a consolidated backorder graduates
    # straight to fulfilled in the same action - CONSOLIDATED -> FULFILLED is
    # itself a checked transition, not a second bare assignment, so this is
    # exactly as guarded as the OPEN -> CONSOLIDATED step above.
    if _resolve_status(fulfillment) == FulfillmentStatus.FULFILLED:
        for b in fulfillment.backorders:
            if b.status == BackorderStatus.CONSOLIDATED:
                assert_transition("Backorder", BackorderStatus(b.status), BackorderStatus.FULFILLED)
                b.status = BackorderStatus.FULFILLED
    await session.flush()
