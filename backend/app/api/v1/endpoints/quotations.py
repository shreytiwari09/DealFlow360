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
from app.models.billing import SubscriptionPlan
from app.models.catalog import Product
from app.models.customer import Customer
from app.models.enums import ItemType, QuotationStatus, RoleCode
from app.models.quotation import Quotation, QuotationLine
from app.models.rbac import Role, User
from app.models.upsell import UpsellRule
from app.schemas.api import (
    AssignableUserResponse,
    CreateQuotationRequest,
    OrderDiscountRequest,
    QuotationLineResponse,
    QuotationResponse,
    QuotationSummaryResponse,
    ReassignQuotationRequest,
    ReplaceLinesRequest,
    RiskLineBreakdown,
    RiskPreviewResponse,
    UpsellSuggestionResponse,
)
from app.services import audit
from app.services.approval import raise_approval_request, risk_band
from app.services.quotation import (
    confirm,
    load_quotation,
    next_quote_number,
    quantize_percent,
    recalculate,
)
from app.services.risk import LineRiskInput, assess_lines
from app.services.state_machine import InvalidStateTransition, assert_transition
from app.services.upsell import (
    UpsellCandidate,
    margin_delta_if_added,
    product_margin_percent,
    rank_suggestions,
)

router = APIRouter(prefix="/quotations", tags=["quotations"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quotation not found.")

# Annotated aliases rather than `= Depends(...)` in a signature: keeping the
# call out of an argument default is what ruff B008 is about, and naming them
# here makes the permission each route demands readable at a glance.
CanReadOwn = Annotated[User, Depends(require_permission("deal.read_own"))]
CanCreate = Annotated[User, Depends(require_permission("deal.create"))]
# Admin-only in practice: nobody else is seeded with it (Locked Business #8).
CanConfirmOverride = Annotated[User, Depends(require_permission("deal.confirm_override"))]
CanAssign = Annotated[User, Depends(require_permission("deal.assign"))]


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
        subscription_plan_id=line.subscription_plan_id,
        subscription_plan_name=line.subscription_plan.name if line.subscription_plan else None,
    )


def _detail(quotation: Quotation, user: User) -> QuotationResponse:
    return QuotationResponse(
        id=quotation.id,
        quote_number=quotation.quote_number,
        customer_id=quotation.customer_id,
        customer_name=quotation.customer.name,
        customer_tier=quotation.customer.tier,
        owner_id=quotation.owner_id,
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
    list is `GET /portal/quotations`.
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
            owner_id=q.owner_id,
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


@router.get("/assignable-users", response_model=list[AssignableUserResponse])
async def list_assignable_users(
    session: SessionDep, user: CanAssign
) -> list[AssignableUserResponse]:
    """The reassign picker's options: every active internal (non-customer)
    user — deliberately not `GET /admin/users` (that needs `user.manage`,
    a different, broader permission `deal.assign` does not imply).

    Registered ABOVE `GET /{quotation_id}` on purpose: FastAPI matches routes
    in registration order, and `quotation_id: int`'s own type validation
    would otherwise 422 on the literal string "assignable-users" before this
    route ever got a chance to match.
    """
    rows = (
        (
            await session.execute(
                select(User)
                .join(Role, User.role_id == Role.id)
                .where(User.is_active.is_(True), Role.code != RoleCode.CUSTOMER)
                .options(selectinload(User.role))
                .order_by(User.full_name)
            )
        )
        .scalars()
        .all()
    )
    return [
        AssignableUserResponse(id=u.id, full_name=u.full_name, role_name=u.role.name) for u in rows
    ]


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


@router.patch("/{quotation_id}/assign", response_model=QuotationResponse)
async def reassign_quotation(
    request: Request,
    quotation_id: int,
    payload: ReassignQuotationRequest,
    session: SessionDep,
    user: CanAssign,
) -> QuotationResponse:
    """PRD Section 3: Sales Manager "Reassigns a quotation to another rep."

    Not ownership-gated like editing a quotation's lines is — `deal.assign`
    is the whole authorization here, the same flat-permission shape as
    `config.manage`/`user.manage` elsewhere in this app: whoever holds it may
    reassign any quotation, not only ones on their own team (no per-team
    scoping exists anywhere else in this codebase's permission model either,
    so inventing one just for this action would be inconsistent, not safer).
    """
    quotation = await load_quotation(session, quotation_id)
    if quotation is None:
        raise _NOT_FOUND

    new_owner = (
        await session.execute(
            select(User).where(User.id == payload.new_owner_id).options(selectinload(User.role))
        )
    ).scalar_one_or_none()
    if new_owner is None or not new_owner.is_active or new_owner.role.code == RoleCode.CUSTOMER:
        raise HTTPException(status_code=422, detail="Unknown or ineligible user.")

    old_owner_name = quotation.owner.full_name
    # Assigning the RELATIONSHIP, not just `owner_id`: this quotation is
    # already in the session's identity map with `owner` eagerly loaded from
    # the fetch above, and setting only the FK scalar leaves that relationship
    # attribute stale (still pointing at the old owner object) for the rest
    # of this request - `_detail()` below would report the wrong name even
    # though the database write was correct. Setting `.owner` keeps both the
    # FK and the in-memory relationship consistent in one step.
    quotation.owner = new_owner

    await audit.record(
        session,
        action=AuditAction.QUOTATION_REASSIGNED,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason=f"reassigned from {old_owner_name} to {new_owner.full_name}",
        request=request,
    )
    await session.commit()

    loaded = await load_quotation(session, quotation.id)
    return _detail(loaded, user)


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

    plan_ids = {item.subscription_plan_id for item in payload.lines if item.subscription_plan_id}
    plans: dict[int, SubscriptionPlan] = {}
    if plan_ids:
        rows = (
            await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.id.in_(plan_ids)))
        ).scalars()
        plans = {plan.id: plan for plan in rows if plan.is_active}

    for item in payload.lines:
        product = products[item.product_id]
        if product.item_type == ItemType.SUBSCRIPTION:
            if item.subscription_plan_id is None or item.subscription_plan_id not in plans:
                raise HTTPException(
                    status_code=422,
                    detail=f"'{product.name}' is a subscription product and requires a valid "
                    "subscription_plan_id.",
                )
        elif item.subscription_plan_id is not None:
            raise HTTPException(
                status_code=422,
                detail=f"'{product.name}' is a one-time product and must not specify a "
                "subscription_plan_id.",
            )

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
                discount_percent=quantize_percent(item.discount_percent),
                line_type=product.item_type,
                subscription_plan_id=item.subscription_plan_id
                if product.item_type == ItemType.SUBSCRIPTION
                else None,
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

    # Real bug, found by an in-depth pass over this file and confirmed live:
    # `assert_can_edit_quotation` checks permission and ownership only, never
    # status (see `deps.py::can_edit_quotation`'s own docstring - "Only the
    # owning rep may edit, and only their own", nothing about WHEN). Unlike
    # `replace_lines` just above, this endpoint had no equivalent status
    # gate, so the owning rep could apply a fresh discount to a quotation
    # that had already been CONFIRMED - after `generate_billing_for_quotation`
    # had already written a `BillingSchedule` row for the ORIGINAL total.
    # Reproduced live: confirming a ₹29,500 order, then applying a 40% order
    # discount to it, left the quotation reporting ₹17,700 while the invoice
    # already on file still said ₹29,500 - a real, silent money mismatch
    # between what the quotation claims and what was actually billed.
    if quotation.status not in (QuotationStatus.DRAFT, QuotationStatus.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a draft quotation can be edited.",
        )

    order_discount = quantize_percent(payload.discount_percent)
    for line in quotation.lines:
        line.discount_percent = order_discount
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
    """The live risk indicator, and Screen 6's "why flagged" breakdown.

    Related bug, found alongside the order-discount one above: this is a GET
    endpoint, but it called `recalculate()` (which WRITES the quotation's
    derived fields and flushes) unconditionally, on every view, regardless
    of status. `recalculate()`'s own docstring on `allowed_discount_percent`
    says the per-line ceiling is "snapshotted onto the row so a later change
    to policy cannot rewrite what was approved" - but simply opening this
    tab on an already-decided quotation silently re-derived and persisted
    that same "snapshot" from WHATEVER the discount ceilings happen to be
    today, contradicting the very invariant that comment describes. An Admin
    editing a discount tier months after a deal closed could retroactively
    change a closed quotation's own record of why it was flagged, just by
    someone opening its risk tab.

    Fixed the same way as the order-discount bug: once a quotation has left
    draft/rejected, its risk numbers are a historical record, not a live
    computation - build the preview from the lines' own already-stored
    values (a pure, read-only call into `risk.py`) instead of recomputing
    and persisting. Still fully live and recalculated for an editable quote,
    where that behavior is exactly what the builder screen needs.
    """
    quotation = await load_quotation(session, quotation_id)
    if quotation is None:
        raise _NOT_FOUND
    await assert_can_view_quotation(request, session, user, quotation)

    editable = quotation.status in (QuotationStatus.DRAFT, QuotationStatus.REJECTED)
    if editable:
        assessment = await recalculate(session, quotation)
        await session.commit()
    else:
        assessment = assess_lines(
            [
                LineRiskInput(
                    line_number=line.line_number,
                    quantity=line.quantity,
                    unit_list_price=line.unit_list_price,
                    discount_percent=line.discount_percent,
                    allowed_discount_percent=line.allowed_discount_percent,
                )
                for line in quotation.lines
            ]
        )
    steps = await raise_approval_request(session, quotation, assessment, dry_run=True)

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


@router.get("/{quotation_id}/upsell", response_model=list[UpsellSuggestionResponse])
async def get_upsell_suggestions(
    request: Request, quotation_id: int, session: SessionDep, user: CurrentUser
) -> list[UpsellSuggestionResponse]:
    """PRD B5's Upsell & Cross-Sell panel: ranked suggestions for the products
    already on this quote, with each one's live margin impact if added.

    Seeded `upsell_rules` map a trigger product to a suggested one
    (`app/models/upsell.py`). A product already on the quote, or with no rule
    at all, is never suggested — there is no fallback to "just show something"
    the way the old promoted-products stand-in did.
    """
    quotation = await load_quotation(session, quotation_id)
    if quotation is None:
        raise _NOT_FOUND
    await assert_can_view_quotation(request, session, user, quotation)

    on_quote_ids = {line.product_id for line in quotation.lines}
    if not on_quote_ids:
        return []

    rows = (
        await session.execute(
            select(UpsellRule, Product)
            .join(Product, Product.id == UpsellRule.suggested_product_id)
            .where(
                UpsellRule.trigger_product_id.in_(on_quote_ids),
                UpsellRule.suggested_product_id.notin_(on_quote_ids),
                UpsellRule.is_active.is_(True),
                Product.is_active.is_(True),
            )
        )
    ).all()

    # A product can be suggested by more than one line already on the quote
    # (two triggers both pointing at the same accessory) - keep only the
    # highest-scoring rule per suggested product rather than showing it twice.
    best_rule: dict[int, UpsellRule] = {}
    product_by_id: dict[int, Product] = {}
    for rule, product in rows:
        product_by_id[product.id] = product
        current = best_rule.get(product.id)
        if current is None or rule.co_purchase_score > current.co_purchase_score:
            best_rule[product.id] = rule

    current_net_revenue = quotation.subtotal_amount - quotation.discount_amount
    current_margin_amount = quotation.margin_amount

    candidates = []
    for product_id, rule in best_rule.items():
        product = product_by_id[product_id]
        delta = margin_delta_if_added(
            current_net_revenue=current_net_revenue,
            current_margin_amount=current_margin_amount,
            added_list_price=product.list_price,
            added_cost_price=product.cost_price,
        )
        candidates.append(
            UpsellCandidate(
                suggested_product_id=product_id,
                is_promoted=product.is_promoted,
                co_purchase_score=rule.co_purchase_score,
                min_margin_percent=rule.min_margin_percent,
                product_margin_percent=product_margin_percent(
                    product.list_price, product.cost_price
                ),
                margin_delta_percent=delta,
            )
        )

    ranked = rank_suggestions(candidates)
    return [
        UpsellSuggestionResponse(
            product_id=c.suggested_product_id,
            product_name=product_by_id[c.suggested_product_id].name,
            product_sku=product_by_id[c.suggested_product_id].sku,
            list_price=product_by_id[c.suggested_product_id].list_price,
            is_promoted=c.is_promoted,
            margin_delta_percent=c.margin_delta_percent,
        )
        for c in ranked
    ]


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
    request: Request, quotation_id: int, session: SessionDep, user: CanConfirmOverride
) -> QuotationResponse:
    """Confirm a quotation on the customer's behalf — an Admin override.

    The customer's own "Confirm Quotation" (PRD B8) now lives on the portal at
    `POST /portal/quotations/{id}/confirm`, and that is the normal path. This
    endpoint began as a stand-in while the portal did not exist; it survives
    only for the case the PRD does not cover — the customer confirmed by phone
    or email — and is now restricted to `deal.confirm_override`, which only
    Admin holds (Locked Business Rules #7 and #8).

    It is deliberately NOT restricted to the owning rep: "the customer said
    yes on a call" is not something only the original rep can witness. But it
    IS restricted to one permission, because an unrestricted second route to
    `confirmed` would let any internal user bypass the customer's own
    confirmation entirely.
    """
    quotation = await load_quotation(session, quotation_id)
    if quotation is None:
        raise _NOT_FOUND
    await assert_can_view_quotation(request, session, user, quotation)

    # One shared implementation with the portal's confirm — transition,
    # then billing — so the two paths cannot drift.
    try:
        schedules = await confirm(session, quotation, actor_id=user.id)
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await audit.record(
        session,
        action=AuditAction.QUOTATION_STATUS_CHANGED,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason="confirmed by an administrator on the customer's behalf",
        request=request,
    )
    if schedules:
        await audit.record(
            session,
            action=AuditAction.BILLING_SCHEDULE_GENERATED,
            user_id=user.id,
            resource="quotation",
            resource_id=quotation.id,
            reason=f"{len(schedules)} billing schedule row(s) generated",
            request=request,
        )

    await session.commit()
    return _detail(await load_quotation(session, quotation.id), user)
