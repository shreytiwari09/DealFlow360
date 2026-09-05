"""Billing endpoints — FRONTEND.md Screens 9, 10, 12 and 13 (PRD B7).

Viewing follows the fulfillment screens' role split (FRONTEND.md's own "Roles"
line for each screen): Finance/Operations and Admin act (modify, cancel,
invoice, record payment); Sales Manager and Sales Rep may only view, scoped
the same way the quotations list is — a rep sees their own orders' billing,
anyone holding a broader read permission sees everything. A customer has no
business here at all; the portal gets its own screens later.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep, assert_can_view_quotation, has_permission
from app.models.audit import AuditAction
from app.models.billing import BillingSchedule, Subscription
from app.models.enums import PaymentMethod, RoleCode
from app.models.quotation import Quotation, QuotationLine
from app.schemas.api import (
    BillingScheduleResponse,
    InvoiceDetailResponse,
    ModifySubscriptionRequest,
    PaymentResponse,
    ProrationRecordResponse,
    RecordPaymentRequest,
    SubscriptionDetailResponse,
    SubscriptionSummaryResponse,
)
from app.services import audit
from app.services.billing import (
    BillingError,
    cancel_subscription,
    issue_invoice,
    load_billing_schedule,
    load_subscription,
    modify_subscription,
    record_payment,
)
from app.services.quotation import load_quotation

router = APIRouter(prefix="/billing", tags=["billing"])

_CAN_ACT_PERMISSION = "billing.manage"


def _can_act(user) -> bool:
    return has_permission(user, _CAN_ACT_PERMISSION)


def _reject_customer(user) -> None:
    if user.role.code == RoleCode.CUSTOMER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not available.")


def _require_act(user) -> None:
    if not _can_act(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted.")


# --- Subscriptions (Screens 9-10) -------------------------------------------


def _subscription_summary(s: Subscription) -> SubscriptionSummaryResponse:
    quotation = s.quotation_line.quotation
    return SubscriptionSummaryResponse(
        id=s.id,
        quotation_id=quotation.id,
        quote_number=quotation.quote_number,
        customer_name=quotation.customer.name,
        product_name=s.quotation_line.product.name,
        plan_name=s.plan.name,
        status=s.status,
        quantity=s.quantity,
        unit_amount=s.unit_amount,
        current_cycle_start=s.current_cycle_start,
        current_cycle_end=s.current_cycle_end,
    )


@router.get("/subscriptions", response_model=list[SubscriptionSummaryResponse])
async def list_subscriptions(
    session: SessionDep, user: CurrentUser
) -> list[SubscriptionSummaryResponse]:
    """Screen 9."""
    _reject_customer(user)

    statement = (
        select(Subscription)
        .join(QuotationLine, QuotationLine.id == Subscription.quotation_line_id)
        .join(Quotation, Quotation.id == QuotationLine.quotation_id)
        .options(
            selectinload(Subscription.plan),
            selectinload(Subscription.quotation_line)
            .selectinload(QuotationLine.quotation)
            .selectinload(Quotation.customer),
            selectinload(Subscription.quotation_line).selectinload(QuotationLine.product),
        )
        .order_by(Subscription.id.desc())
    )
    if not (has_permission(user, "deal.read_all") or has_permission(user, "deal.read_team")):
        statement = statement.where(Quotation.owner_id == user.id)

    rows = (await session.execute(statement)).scalars().all()
    return [_subscription_summary(s) for s in rows]


async def _load_subscription_authorized(
    request: Request, session: SessionDep, user: CurrentUser, subscription_id: int
) -> Subscription:
    _reject_customer(user)
    subscription = await load_subscription(session, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found.")
    quotation = await load_quotation(session, subscription.quotation_line.quotation_id)
    await assert_can_view_quotation(request, session, user, quotation)
    return subscription


def _subscription_detail(s: Subscription, user) -> SubscriptionDetailResponse:
    summary = _subscription_summary(s)
    return SubscriptionDetailResponse(
        **summary.model_dump(),
        plan_id=s.subscription_plan_id,
        billing_schedules=[_schedule_response(bs) for bs in s.billing_schedules],
        proration_history=[
            ProrationRecordResponse(
                id=p.id,
                change_date=p.change_date,
                cycle_start=p.cycle_start,
                cycle_end=p.cycle_end,
                cycle_days=p.cycle_days,
                remaining_days=p.remaining_days,
                old_quantity=p.old_quantity,
                new_quantity=p.new_quantity,
                old_amount=p.old_amount,
                new_amount=p.new_amount,
                credit_amount=p.credit_amount,
                charge_amount=p.charge_amount,
                proration_amount=p.proration_amount,
            )
            for p in sorted(s.proration_records, key=lambda p: p.change_date)
        ],
        can_act=_can_act(user),
    )


def _schedule_response(bs: BillingSchedule) -> BillingScheduleResponse:
    return BillingScheduleResponse(
        id=bs.id,
        quotation_id=bs.quotation_id,
        quote_number=bs.quotation.quote_number if bs.quotation is not None else "",
        subscription_id=bs.subscription_id,
        schedule_type=bs.schedule_type,
        status=bs.status,
        due_date=bs.due_date,
        amount=bs.amount,
        cycle_start=bs.cycle_start,
        cycle_end=bs.cycle_end,
        invoice_number=bs.invoice_number,
        invoiced_at=bs.invoiced_at,
        is_credit_note=bs.is_credit_note,
    )


@router.get("/subscriptions/{subscription_id}", response_model=SubscriptionDetailResponse)
async def get_subscription(
    request: Request, subscription_id: int, session: SessionDep, user: CurrentUser
) -> SubscriptionDetailResponse:
    """Screen 10."""
    subscription = await _load_subscription_authorized(request, session, user, subscription_id)
    return _subscription_detail(subscription, user)


@router.post("/subscriptions/{subscription_id}/modify", response_model=SubscriptionDetailResponse)
async def modify(
    request: Request,
    subscription_id: int,
    payload: ModifySubscriptionRequest,
    session: SessionDep,
    user: CurrentUser,
) -> SubscriptionDetailResponse:
    """PRD B7 mid-cycle quantity or plan change. Screen 9/10's
    "Modify Subscription" action."""
    subscription = await _load_subscription_authorized(request, session, user, subscription_id)
    _require_act(user)

    try:
        record = await modify_subscription(
            session,
            subscription,
            new_quantity=payload.new_quantity,
            new_plan_id=payload.new_plan_id,
            actor_id=user.id,
        )
    except BillingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await audit.record(
        session,
        action=AuditAction.SUBSCRIPTION_MODIFIED,
        user_id=user.id,
        resource="subscription",
        resource_id=subscription.id,
        reason=(
            f"proration {record.proration_amount} ({record.old_quantity} -> {record.new_quantity})"
        ),
        request=request,
    )
    await session.commit()
    subscription = await load_subscription(session, subscription_id)
    return _subscription_detail(subscription, user)


@router.post("/subscriptions/{subscription_id}/cancel", response_model=SubscriptionDetailResponse)
async def cancel(
    request: Request, subscription_id: int, session: SessionDep, user: CurrentUser
) -> SubscriptionDetailResponse:
    """PRD B7: "an automatic partial refund or credit note trigger" fires on
    cancel, per the plan's `refund_policy`. Screen 9/10's destructive
    "Cancel Subscription" action."""
    subscription = await _load_subscription_authorized(request, session, user, subscription_id)
    _require_act(user)

    try:
        record = await cancel_subscription(session, subscription, actor_id=user.id)
    except BillingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await audit.record(
        session,
        action=AuditAction.SUBSCRIPTION_CANCELLED,
        user_id=user.id,
        resource="subscription",
        resource_id=subscription.id,
        reason=f"credit {record.proration_amount}" if record else "no refund (policy: none)",
        request=request,
    )
    await session.commit()
    subscription = await load_subscription(session, subscription_id)
    return _subscription_detail(subscription, user)


# --- Invoices (Screens 12-13) -----------------------------------------------


@router.get("/invoices", response_model=list[BillingScheduleResponse])
async def list_invoices(session: SessionDep, user: CurrentUser) -> list[BillingScheduleResponse]:
    """Screen 12. Every one-time invoice, recurring instalment and proration
    adjustment across every order — one flat list, filtered the same way the
    quotations list is."""
    _reject_customer(user)

    statement = (
        select(BillingSchedule)
        .join(Quotation, Quotation.id == BillingSchedule.quotation_id)
        .options(selectinload(BillingSchedule.quotation))
        .order_by(BillingSchedule.due_date.desc())
    )
    if not (has_permission(user, "deal.read_all") or has_permission(user, "deal.read_team")):
        statement = statement.where(Quotation.owner_id == user.id)

    rows = (await session.execute(statement)).scalars().all()
    return [_schedule_response(bs) for bs in rows]


async def _load_invoice_authorized(
    request: Request, session: SessionDep, user: CurrentUser, schedule_id: int
) -> BillingSchedule:
    _reject_customer(user)
    schedule = await load_billing_schedule(session, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    quotation = await load_quotation(session, schedule.quotation_id)
    await assert_can_view_quotation(request, session, user, quotation)
    return schedule


def _invoice_detail(bs: BillingSchedule, user) -> InvoiceDetailResponse:
    base = _schedule_response(bs)
    return InvoiceDetailResponse(
        **base.model_dump(),
        customer_name=bs.quotation.customer.name,
        payments=[
            PaymentResponse(
                id=p.id,
                amount=p.amount,
                method=p.method,
                paid_at=p.paid_at,
                reference=p.reference,
                notes=p.notes,
            )
            for p in bs.payments
        ],
        can_act=_can_act(user),
    )


@router.get("/invoices/{schedule_id}", response_model=InvoiceDetailResponse)
async def get_invoice(
    request: Request, schedule_id: int, session: SessionDep, user: CurrentUser
) -> InvoiceDetailResponse:
    """Screen 13."""
    schedule = await _load_invoice_authorized(request, session, user, schedule_id)
    return _invoice_detail(schedule, user)


@router.post("/invoices/{schedule_id}/issue", response_model=InvoiceDetailResponse)
async def issue(
    request: Request, schedule_id: int, session: SessionDep, user: CurrentUser
) -> InvoiceDetailResponse:
    """SCHEDULED -> INVOICED. Assigns the invoice number Screen 13 displays."""
    schedule = await _load_invoice_authorized(request, session, user, schedule_id)
    _require_act(user)

    try:
        await issue_invoice(session, schedule, actor_id=user.id)
    except BillingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await audit.record(
        session,
        action=AuditAction.INVOICE_ISSUED,
        user_id=user.id,
        resource="billing_schedule",
        resource_id=schedule.id,
        reason=f"invoice {schedule.invoice_number}",
        request=request,
    )
    await session.commit()
    schedule = await load_billing_schedule(session, schedule_id)
    return _invoice_detail(schedule, user)


@router.post("/invoices/{schedule_id}/payments", response_model=InvoiceDetailResponse)
async def add_payment(
    request: Request,
    schedule_id: int,
    payload: RecordPaymentRequest,
    session: SessionDep,
    user: CurrentUser,
) -> InvoiceDetailResponse:
    """PRD Section 9's own quick test flow: "Confirm the order, record a
    payment, and check that the invoice status updates correctly."""
    schedule = await _load_invoice_authorized(request, session, user, schedule_id)
    _require_act(user)

    try:
        payment = await record_payment(
            session,
            schedule,
            amount=payload.amount,
            method=PaymentMethod(payload.method),
            reference=payload.reference,
            notes=payload.notes,
            actor_id=user.id,
        )
    except BillingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await audit.record(
        session,
        action=AuditAction.PAYMENT_RECORDED,
        user_id=user.id,
        resource="billing_schedule",
        resource_id=schedule.id,
        reason=f"{payment.amount} via {payment.method}",
        request=request,
    )
    await session.commit()
    schedule = await load_billing_schedule(session, schedule_id)
    return _invoice_detail(schedule, user)
