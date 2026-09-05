"""Fulfillment endpoints — FRONTEND.md Screens 7 and 8.

Viewing a confirmed quotation's fulfillment detail auto-generates the
suggested split on first view (PRD: "the system suggests a warehouse
fulfillment split") - there is no separate "compute" action for the rep to
remember to click.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep, assert_can_view_quotation, has_permission
from app.models.audit import AuditAction
from app.models.catalog import Product
from app.models.enums import BackorderStatus, QuotationStatus
from app.models.inventory import StockLevel, Warehouse
from app.models.quotation import Quotation
from app.schemas.api import (
    BackorderResponse,
    FulfillmentDetailResponse,
    FulfillmentSplitResponse,
    OrderAwaitingFulfillmentResponse,
    OverrideSplitRequest,
    StockLevelResponse,
)
from app.services import audit
from app.services.fulfillment import (
    FulfillmentError,
    accept_fulfillment,
    consolidate_backorder,
    generate_fulfillment,
    load_fulfillment,
    override_fulfillment,
)
from app.services.quotation import load_quotation

router = APIRouter(prefix="/fulfillment", tags=["fulfillment"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quotation not found.")

# Only these permissions may act (accept/override/consolidate). Everyone who
# can view the underlying quotation may still read the fulfillment screens.
_CAN_ACT_PERMISSION = "fulfillment.manage"

# A quotation is "in scope" for the fulfillment list once it has cleared
# confirmation and hasn't reached the terminal fulfilled/cancelled states.
_RELEVANT_STATUSES = (QuotationStatus.CONFIRMED, QuotationStatus.FULFILLED)


def _can_act(user) -> bool:
    return has_permission(user, _CAN_ACT_PERMISSION)


@router.get("", response_model=dict)
async def fulfillment_overview(session: SessionDep, user: CurrentUser) -> dict:
    """Screen 7: the live stock table plus every order awaiting fulfillment."""
    stock_rows = (
        (
            await session.execute(
                select(StockLevel)
                .options(selectinload(StockLevel.warehouse), selectinload(StockLevel.product))
                .join(Warehouse, Warehouse.id == StockLevel.warehouse_id)
                .join(Product, Product.id == StockLevel.product_id)
                .order_by(Product.name, Warehouse.name)
            )
        )
        .scalars()
        .all()
    )

    stock = [
        StockLevelResponse(
            warehouse_id=row.warehouse_id,
            warehouse_name=row.warehouse.name,
            product_id=row.product_id,
            product_name=row.product.name,
            quantity_on_hand=row.quantity_on_hand,
            quantity_reserved=row.quantity_reserved,
            available=row.quantity_on_hand - row.quantity_reserved,
        )
        for row in stock_rows
    ]

    statement = (
        select(Quotation)
        .where(Quotation.status.in_(_RELEVANT_STATUSES))
        .options(
            selectinload(Quotation.customer),
            selectinload(Quotation.fulfillments),
        )
        .order_by(Quotation.updated_at.desc())
    )
    if not (has_permission(user, "deal.read_all") or has_permission(user, "deal.read_team")):
        statement = statement.where(Quotation.owner_id == user.id)

    quotations = (await session.execute(statement)).scalars().all()

    orders = []
    for q in quotations:
        latest = max(q.fulfillments, key=lambda f: f.id, default=None)
        warehouse_names: list[str] = []
        if latest is not None:
            await session.refresh(latest, attribute_names=["splits"])
            for split in latest.splits:
                await session.refresh(split, attribute_names=["warehouse"])
                if split.warehouse.name not in warehouse_names:
                    warehouse_names.append(split.warehouse.name)
        orders.append(
            OrderAwaitingFulfillmentResponse(
                quotation_id=q.id,
                quote_number=q.quote_number,
                customer_name=q.customer.name,
                fulfillment_status=latest.status if latest else None,
                warehouse_names=warehouse_names,
            )
        )

    return {"stock": stock, "orders": orders}


async def _load_and_authorize(
    request: Request, session: SessionDep, user: CurrentUser, quotation_id: int
) -> Quotation:
    quotation = await load_quotation(session, quotation_id)
    if quotation is None:
        raise _NOT_FOUND
    await assert_can_view_quotation(request, session, user, quotation)
    return quotation


def _detail(quotation: Quotation, fulfillment, user) -> FulfillmentDetailResponse:
    return FulfillmentDetailResponse(
        id=fulfillment.id,
        quotation_id=quotation.id,
        quote_number=quotation.quote_number,
        customer_name=quotation.customer.name,
        status=fulfillment.status,
        shipment_count=fulfillment.shipment_count,
        estimated_shipping_cost=fulfillment.estimated_shipping_cost,
        is_manual_override=fulfillment.is_manual_override,
        splits=[
            FulfillmentSplitResponse(
                quotation_line_id=split.quotation_line_id,
                product_name=split.quotation_line.product.name,
                warehouse_id=split.warehouse_id,
                warehouse_name=split.warehouse.name,
                quantity=split.quantity,
                is_manual_override=split.is_manual_override,
            )
            for split in fulfillment.splits
        ],
        backorders=[
            BackorderResponse(
                id=b.id,
                quotation_line_id=b.quotation_line_id,
                product_name=b.quotation_line.product.name,
                quantity_outstanding=b.quantity_outstanding,
                status=b.status,
                # Computed lazily by the frontend calling the consolidate
                # endpoint and reading its error, would be wasteful here;
                # instead this is left False and Screen 8's "Consolidate"
                # action simply reports if it is not yet possible.
                can_consolidate=b.status == BackorderStatus.OPEN,
            )
            for b in fulfillment.backorders
        ],
        can_act=_can_act(user),
    )


@router.get("/{quotation_id}", response_model=FulfillmentDetailResponse)
async def get_fulfillment(
    request: Request, quotation_id: int, session: SessionDep, user: CurrentUser
) -> FulfillmentDetailResponse:
    """Screen 8. Auto-generates the suggested split on first view."""
    quotation = await _load_and_authorize(request, session, user, quotation_id)

    fulfillment = await load_fulfillment(session, quotation_id)
    if fulfillment is None:
        try:
            fulfillment = await generate_fulfillment(session, quotation, actor_id=user.id)
        except FulfillmentError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        await audit.record(
            session,
            action=AuditAction.FULFILLMENT_SPLIT_SUGGESTED,
            user_id=user.id,
            resource="quotation",
            resource_id=quotation.id,
            reason=f"suggested split across {fulfillment.shipment_count} warehouse(s)",
            request=request,
        )
        await session.commit()
        fulfillment = await load_fulfillment(session, quotation_id)

    return _detail(quotation, fulfillment, user)


@router.post("/{quotation_id}/accept", response_model=FulfillmentDetailResponse)
async def accept(
    request: Request, quotation_id: int, session: SessionDep, user: CurrentUser
) -> FulfillmentDetailResponse:
    quotation = await _load_and_authorize(request, session, user, quotation_id)
    if not _can_act(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted.")

    fulfillment = await load_fulfillment(session, quotation_id)
    if fulfillment is None:
        raise HTTPException(status_code=404, detail="No fulfillment to accept.")

    try:
        await accept_fulfillment(session, fulfillment)
    except FulfillmentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await audit.record(
        session,
        action=AuditAction.FULFILLMENT_SPLIT_ACCEPTED,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason=f"accepted; fulfillment now {fulfillment.status}",
        request=request,
    )
    await session.commit()
    fulfillment = await load_fulfillment(session, quotation_id)
    quotation = await load_quotation(session, quotation_id)
    return _detail(quotation, fulfillment, user)


@router.post("/{quotation_id}/override", response_model=FulfillmentDetailResponse)
async def override(
    request: Request,
    quotation_id: int,
    payload: OverrideSplitRequest,
    session: SessionDep,
    user: CurrentUser,
) -> FulfillmentDetailResponse:
    quotation = await _load_and_authorize(request, session, user, quotation_id)
    if not _can_act(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted.")

    fulfillment = await load_fulfillment(session, quotation_id)
    if fulfillment is None:
        raise HTTPException(status_code=404, detail="No fulfillment to override.")

    try:
        await override_fulfillment(
            session,
            fulfillment,
            lines=[
                (item.quotation_line_id, item.warehouse_id, item.quantity) for item in payload.lines
            ],
            actor_id=user.id,
        )
    except FulfillmentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await audit.record(
        session,
        action=AuditAction.FULFILLMENT_SPLIT_OVERRIDDEN,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason=f"manually redistributed {len(payload.lines)} line(s)",
        request=request,
    )
    await session.commit()
    fulfillment = await load_fulfillment(session, quotation_id)
    return _detail(quotation, fulfillment, user)


@router.post(
    "/{quotation_id}/backorders/{backorder_id}/consolidate",
    response_model=FulfillmentDetailResponse,
)
async def consolidate(
    request: Request,
    quotation_id: int,
    backorder_id: int,
    session: SessionDep,
    user: CurrentUser,
) -> FulfillmentDetailResponse:
    """PRD B6's "Consolidate Remaining Backorder" action.

    Manually triggered here rather than automatic - see FulfillmentDetailResponse
    and PROJECT_CONTEXT.md Known Issues for why the fully-automatic version
    needs a background job that is not built yet.
    """
    quotation = await _load_and_authorize(request, session, user, quotation_id)
    if not _can_act(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted.")

    fulfillment = await load_fulfillment(session, quotation_id)
    if fulfillment is None:
        raise HTTPException(status_code=404, detail="No fulfillment found.")
    backorder = next((b for b in fulfillment.backorders if b.id == backorder_id), None)
    if backorder is None:
        raise HTTPException(status_code=404, detail="Backorder not found on this fulfillment.")

    try:
        await consolidate_backorder(session, fulfillment, backorder, actor_id=user.id)
    except FulfillmentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await audit.record(
        session,
        action=AuditAction.FULFILLMENT_BACKORDER_CONSOLIDATED,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason=f"backorder #{backorder_id} consolidated",
        request=request,
    )
    await session.commit()
    fulfillment = await load_fulfillment(session, quotation_id)
    return _detail(quotation, fulfillment, user)
