"""Quotation endpoints — FRONTEND.md Screens 3 and 4."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import (
    CurrentUser,
    SessionDep,
    assert_can_edit_quotation,
    assert_can_view_quotation,
    can_edit_quotation,
    require_permission,
    user_permissions,
)
from app.models.audit import AuditAction
from app.models.catalog import Product
from app.models.customer import Customer
from app.models.enums import ItemType, QuotationStatus, RoleCode
from app.models.quotation import Quotation, QuotationLine
from app.models.rbac import User
from app.schemas.api import (
    CreateQuotationRequest,
    OrderDiscountRequest,
    QuotationLineResponse,
    QuotationResponse,
    QuotationSummaryResponse,
    ReplaceLinesRequest,
    RiskLineBreakdown,
    RiskPreviewResponse,
)
from app.services import audit
from app.services.approval import raise_approval_request, risk_band
from app.services.quotation import load_quotation, next_quote_number, recalculate
from app.services.state_machine import InvalidStateTransition, assert_transition

router = APIRouter(prefix="/quotations", tags=["quotations"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quotation not found.")

# Annotated aliases rather than `= Depends(...)` in a signature: keeping the
# call out of an argument default is what ruff B008 is about, and naming them
# here makes the permission each route demands readable at a glance.
CanReadOwn = Annotated[User, Depends(require_permission("deal.read_own"))]
CanCreate = Annotated[User, Depends(require_permission("deal.create"))]


def _line_response(line: QuotationLine) -> QuotationLineResponse:
    return QuotationLineResponse(
        id=line.id,
        line_number=line.line_number,
        product_id=line.product_id,
        product_name=line.product.name,
        product_sku=line.product.sku,
        quantity=line.quantity,
        unit_list_price=line.unit_list_price,
        discount_percent=line.discount_percent,
        allowed_discount_percent=line.allowed_discount_percent,
        line_excess_points=line.line_excess_points,
        is_over_limit=line.line_excess_points > 0,
        line_type=line.line_type,
        line_subtotal=line.line_subtotal,
        line_discount_amount=line.line_discount_amount,
        line_total=line.line_total,
        added_from_upsell=line.added_from_upsell,
    )


def _detail(quotation: Quotation, user: User) -> QuotationResponse:
    return QuotationResponse(
        id=quotation.id,
        quote_number=quotation.quote_number,
        customer_id=quotation.customer_id,
        customer_name=quotation.customer.name,
        customer_tier=quotation.customer.tier,
        owner_name=quotation.owner.full_name,
        status=quotation.status,
        subtotal_amount=quotation.subtotal_amount,
        discount_amount=quotation.discount_amount,
        tax_amount=quotation.tax_amount,
        total_amount=quotation.total_amount,
        margin_amount=quotation.margin_amount,
        margin_percent=quotation.margin_percent,
        currency=quotation.currency,
        blended_risk_score=quotation.blended_risk_score,
        max_line_excess=quotation.max_line_excess,
        requires_approval=quotation.max_line_excess > 0,
        requires_finance_approval=quotation.requires_finance_approval,
        valid_until=quotation.valid_until,
        version=quotation.version,
        updated_at=quotation.updated_at,
        lines=[_line_response(line) for line in quotation.lines],
        can_edit=can_edit_quotation(user, quotation),
    )


@router.get("", response_model=list[QuotationSummaryResponse])
async def list_quotations(
    session: SessionDep,
    user: CanReadOwn,
) -> list[QuotationSummaryResponse]:
    """Screen 3, internal only. Scoped server-side — never by a client filter.

    Portal users cannot reach this endpoint at all: the `deal.read_own`
    requirement above excludes them, because the customer role holds only
    `portal.*` permissions. That is deliberate — FRONTEND.md Section 2.2
    requires the portal to be a genuinely separate restricted view, not the
    internal list with rows filtered out. The portal's own "My Quotations"
    endpoint is Phase 3 step 7, and is not built yet.
    """
    statement = (
        select(Quotation)
        .options(selectinload(Quotation.customer), selectinload(Quotation.owner))
        .order_by(Quotation.updated_at.desc())
    )

    # A rep sees only what they own. Anyone with a broader read permission
    # sees everything — the scope comes from the permission, not the request.
    if not ({"deal.read_all", "deal.read_team"} & user_permissions(user)):
        statement = statement.where(Quotation.owner_id == user.id)

    rows = (await session.execute(statement)).scalars().all()
    return [
        QuotationSummaryResponse(
            id=q.id,
            quote_number=q.quote_number,
            customer_id=q.customer_id,
            customer_name=q.customer.name,
            owner_name=q.owner.full_name,
            status=q.status,
            total_amount=q.total_amount,
            currency=q.currency,
            blended_risk_score=q.blended_risk_score,
            updated_at=q.updated_at,
        )
        for q in rows
    ]


@router.post("", response_model=QuotationResponse, status_code=status.HTTP_201_CREATED)
async def create_quotation(
    request: Request,
    payload: CreateQuotationRequest,
    session: SessionDep,
    user: CanCreate,
) -> QuotationResponse:
    customer = (
        await session.execute(select(Customer).where(Customer.id == payload.customer_id))
    ).scalar_one_or_none()
    if customer is None or not customer.is_active:
        raise HTTPException(status_code=422, detail="Unknown customer.")

    quotation = Quotation(
        quote_number=await next_quote_number(session),
        customer_id=customer.id,
        # Derived from the authenticated session, NEVER from the payload.
        owner_id=user.id,
        created_by=user.id,
        status=QuotationStatus.DRAFT,
        currency=customer.currency,
        valid_until=payload.valid_until,
    )
    session.add(quotation)
    await session.flush()

    await audit.record(
        session,
        action=AuditAction.QUOTATION_CREATED,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason=f"created for {customer.name}",
        request=request,
    )
    await session.commit()

    loaded = await load_quotation(session, quotation.id)
    return _detail(loaded, user)


@router.get("/{quotation_id}", response_model=QuotationResponse)
async def get_quotation(
    request: Request, quotation_id: int, session: SessionDep, user: CurrentUser
) -> QuotationResponse:
    quotation = await load_quotation(session, quotation_id)
    if quotation is None:
        raise _NOT_FOUND
    # Ownership, not just permission — this is the IDOR check.
    await assert_can_view_quotation(request, session, user, quotation)
    return _detail(quotation, user)


@router.put("/{quotation_id}/lines", response_model=QuotationResponse)
async def replace_lines(
    request: Request,
    quotation_id: int,
    payload: ReplaceLinesRequest,
    session: SessionDep,
    user: CurrentUser,
) -> QuotationResponse:
    """Replace the whole line set and recompute totals, margin and risk.

    Whole-set replacement rather than per-line PATCH: there is no intermediate
    state where stored totals disagree with the lines, which is the property
    that keeps the live risk score trustworthy.
    """
    quotation = await load_quotation(session, quotation_id)
    if quotation is None:
        raise _NOT_FOUND
    await assert_can_edit_quotation(request, session, user, quotation)

    if quotation.status not in (QuotationStatus.DRAFT, QuotationStatus.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a draft quotation can be edited.",
        )

    product_ids = {item.product_id for item in payload.lines}
    products: dict[int, Product] = {}
    if product_ids:
        rows = (await session.execute(select(Product).where(Product.id.in_(product_ids)))).scalars()
        products = {product.id: product for product in rows}
    missing = product_ids - set(products)
    if missing:
        raise HTTPException(status_code=422, detail="Unknown product on one or more lines.")

    for line in list(quotation.lines):
        await session.delete(line)
    await session.flush()

    for index, item in enumerate(payload.lines, start=1):
        product = products[item.product_id]
        session.add(
            QuotationLine(
                quotation_id=quotation.id,
                line_number=index,
                product_id=product.id,
                quantity=item.quantity,
                # Prices snapshotted from master data at quoting time.
                unit_list_price=product.list_price,
                unit_cost_price=product.cost_price,
                tax_rate=product.tax_rate,
                discount_percent=item.discount_percent,
                line_type=product.item_type,
                subscription_plan_id=None
                if product.item_type == ItemType.ONE_TIME
                else _default_plan_id(product),
                added_from_upsell=item.added_from_upsell,
                created_by=user.id,
            )
        )
    await session.flush()

    await recalculate(session, quotation)
    quotation.last_activity_at = datetime.now(UTC)

    await audit.record(
        session,
        action=AuditAction.QUOTATION_UPDATED,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason=f"{len(payload.lines)} line(s); risk {quotation.blended_risk_score}",
        request=request,
    )
    await session.commit()

    return _detail(await load_quotation(session, quotation.id), user)


def _default_plan_id(product: Product) -> int | None:
    """Subscription lines need a plan (database CHECK enforces it).

    Wiring product-to-plan selection into the builder is Phase 3 step 6 work;
    until then a subscription product cannot be added, and returning None here
    surfaces that as a clear 422 from the constraint rather than a silent
    half-built line. FRONTEND.md Screen 4 does not yet specify a plan picker.
    """
    return None


@router.post("/{quotation_id}/order-discount", response_model=QuotationResponse)
async def apply_order_discount(
    request: Request,
    quotation_id: int,
    payload: OrderDiscountRequest,
    session: SessionDep,
    user: CurrentUser,
) -> QuotationResponse:
    """Locked Business Rules #4: distribute onto every line, overwriting.

    The caller is responsible for warning the user first — FRONTEND.md's
    builder requirement — because this discards manually-set line discounts.
    """
    quotation = await load_quotation(session, quotation_id)
    if quotation is None:
        raise _NOT_FOUND
    await assert_can_edit_quotation(request, session, user, quotation)

    for line in quotation.lines:
        line.discount_percent = payload.discount_percent
    await session.flush()
    await recalculate(session, quotation)

    await audit.record(
        session,
        action=AuditAction.QUOTATION_UPDATED,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason=f"order-level discount {payload.discount_percent}% distributed to all lines",
        request=request,
    )
    await session.commit()
    return _detail(await load_quotation(session, quotation.id), user)


@router.get("/{quotation_id}/risk", response_model=RiskPreviewResponse)
async def get_risk(
    request: Request, quotation_id: int, session: SessionDep, user: CurrentUser
) -> RiskPreviewResponse:
    """The live risk indicator, and Screen 6's "why flagged" breakdown."""
    quotation = await load_quotation(session, quotation_id)
    if quotation is None:
        raise _NOT_FOUND
    await assert_can_view_quotation(request, session, user, quotation)

    assessment = await recalculate(session, quotation)
    steps = await raise_approval_request(session, quotation, assessment, dry_run=True)
    await session.commit()

    return RiskPreviewResponse(
        blended_risk_score=assessment.blended_score,
        max_line_excess=assessment.max_line_excess,
        requires_approval=assessment.requires_approval,
        finance_gate_tripped=assessment.finance_gate_tripped,
        risk_band=risk_band(assessment),
        lines=[
            RiskLineBreakdown(
                line_number=line.line_number,
                product_name=line.product.name,
                discount_percent=line.discount_percent,
                allowed_discount_percent=line.allowed_discount_percent,
                excess_points=line.line_excess_points,
            )
            for line in quotation.lines
        ],
        required_steps=[step.role_code for step in steps],
    )


@router.post("/{quotation_id}/submit", response_model=QuotationResponse)
async def submit_for_approval(
    request: Request, quotation_id: int, session: SessionDep, user: CurrentUser
) -> QuotationResponse:
    """Screen 4's primary action.

    The rep does not choose whether approval is needed — the score decides, and
    a quotation with no breach skips approval entirely (PRD B3).
    """
    quotation = await load_quotation(session, quotation_id)
    if quotation is None:
        raise _NOT_FOUND
    await assert_can_edit_quotation(request, session, user, quotation)

    if not quotation.lines:
        raise HTTPException(status_code=422, detail="Add at least one line before submitting.")

    assessment = await recalculate(session, quotation)
    steps = await raise_approval_request(session, quotation, assessment)

    target = QuotationStatus.PENDING_APPROVAL if steps else QuotationStatus.SENT
    try:
        assert_transition("Quotation", QuotationStatus(quotation.status), target)
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    quotation.status = target
    quotation.requires_finance_approval = any(
        step.role_code == RoleCode.FINANCE_OPS for step in steps
    )
    quotation.last_activity_at = datetime.now(UTC)

    await audit.record(
        session,
        action=AuditAction.DISCOUNT_APPROVAL_REQUESTED
        if steps
        else AuditAction.QUOTATION_STATUS_CHANGED,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason=(
            f"submitted; blended risk {assessment.blended_score}, "
            f"max line excess {assessment.max_line_excess} -> "
            + (", ".join(step.role_code for step in steps) if steps else "no approval required")
        ),
        request=request,
    )
    await session.commit()
    return _detail(await load_quotation(session, quotation.id), user)


@router.get("/meta/next-number", response_model=dict[str, str])
async def peek_next_number(session: SessionDep, user: CurrentUser) -> dict[str, str]:
    return {"quote_number": await next_quote_number(session)}


@router.post("/{quotation_id}/confirm", response_model=QuotationResponse)
async def confirm_quotation(
    request: Request, quotation_id: int, session: SessionDep, user: CurrentUser
) -> QuotationResponse:
    """Move a quotation to `confirmed`, unlocking fulfillment.

    This is a deliberate, temporary stand-in. PRD B8 gives the CUSTOMER the
    "Confirm Quotation" action on the portal negotiation screen, which is not
    built yet (PROJECT_CONTEXT.md backlog item 3). Until it exists, an
    internal user records that the customer has confirmed by some other
    channel (a call, an email) and this endpoint performs the same state
    transition the portal button will eventually call. It is intentionally
    NOT restricted to the owning rep only - any internal user who can view
    the quotation may record a confirmation, since "the customer said yes on
    a call" is not something only the original rep witnesses.

    Superseded once the portal screen exists: at that point the customer's
    own action becomes the only path to `confirmed` for non-customer-facing
    exceptions, and this endpoint can be retired or restricted to Admin.
    """
    quotation = await load_quotation(session, quotation_id)
    if quotation is None:
        raise _NOT_FOUND
    await assert_can_view_quotation(request, session, user, quotation)

    try:
        assert_transition("Quotation", QuotationStatus(quotation.status), QuotationStatus.CONFIRMED)
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    quotation.status = QuotationStatus.CONFIRMED
    quotation.last_activity_at = datetime.now(UTC)

    await audit.record(
        session,
        action=AuditAction.QUOTATION_STATUS_CHANGED,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason="confirmed (internal stand-in for customer portal confirmation)",
        request=request,
    )
    await session.commit()
    return _detail(await load_quotation(session, quotation.id), user)
