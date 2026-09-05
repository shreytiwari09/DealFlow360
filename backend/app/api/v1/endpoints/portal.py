"""Customer portal endpoints — FRONTEND.md Screen 11, PRD B8.

A genuinely separate, restricted surface, not the internal API with a filter
applied. PLAN.md Section 7 and the PRD's own technical guidelines both require
this explicitly ("must be a real, separate, restricted view, not just another
internal screen with a different label"), so:

  * every route requires a `portal.*` permission, which only the customer role
    holds — an internal user reaching these routes gets 403, not a filtered
    view;
  * every query is scoped by `customer_id` taken from the authenticated user,
    never from the request;
  * responses use the portal-only schemas, which have no field to leak.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import SessionDep, require_permission
from app.models.audit import AuditAction
from app.models.enums import QuotationStatus
from app.models.quotation import Quotation
from app.models.rbac import User
from app.schemas.api import (
    PortalCommentResponse,
    PortalConfirmResponse,
    PortalLineResponse,
    PortalNegotiateRequest,
    PortalQuotationDetailResponse,
    PortalQuotationSummaryResponse,
)
from app.services import audit
from app.services.portal import (
    NEGOTIABLE_STATUSES,
    PortalError,
    confirm_from_portal,
    load_customer_quotation,
    negotiation_history,
    submit_counter_offer,
)

router = APIRouter(prefix="/portal", tags=["portal"])

# The customer role holds these two and nothing else; every internal role
# holds neither. That is what makes this shell unreachable from inside.
PortalViewer = Annotated[User, Depends(require_permission("portal.own_quote.view"))]
PortalNegotiator = Annotated[User, Depends(require_permission("portal.own_quote.negotiate"))]

# Statuses a customer is allowed to know exist at all. A `draft` quotation is
# not theirs to see — it has not been sent to them yet.
_VISIBLE_STATUSES = (
    QuotationStatus.SENT,
    QuotationStatus.APPROVED,
    QuotationStatus.UNDER_NEGOTIATION,
    QuotationStatus.PENDING_APPROVAL,
    QuotationStatus.CONFIRMED,
    QuotationStatus.FULFILLED,
)

# PRD B8 gives the portal exactly three statuses: "Sent, Under Negotiation,
# Confirmed". The internal lifecycle has nine, so the extra ones are mapped
# down rather than leaked:
#
#   * `approved` -> `sent`. A quotation that needed approval before it could
#     ever reach the customer is, from the customer's side, simply now
#     available to review and confirm — exactly what "Sent" means to them.
#     Which internal gate it passed through to get there is not their concern
#     (see `services/portal.py`'s `NEGOTIABLE_STATUSES` for why this state is
#     negotiable at all).
#   * `pending_approval` -> `under_negotiation`. Once a customer's counter
#     sends a quote back for internal approval, the quote must not vanish
#     from their portal (they just acted on it) — but "Pending Approval" tells
#     them our approval machinery is mid-flight, which is internal detail they
#     have no business seeing. "Under Negotiation" is both non-leaky and, from
#     where the customer is standing, simply true: their counter is being
#     considered.
#   * `fulfilled` -> `confirmed`. Delivery tracking is not part of Screen 11.
_PORTAL_STATUS = {
    QuotationStatus.APPROVED: QuotationStatus.SENT,
    QuotationStatus.PENDING_APPROVAL: QuotationStatus.UNDER_NEGOTIATION,
    QuotationStatus.FULFILLED: QuotationStatus.CONFIRMED,
}

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quotation not found.")


def _no_customer(user: User) -> HTTPException:
    """A portal account with no `customer_id` is a misconfiguration, not a
    404 — but it must not be described in a way that helps someone probe."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This account is not linked to a customer.",
    )


def _summary(quotation: Quotation) -> PortalQuotationSummaryResponse:
    internal = QuotationStatus(quotation.status)
    return PortalQuotationSummaryResponse(
        id=quotation.id,
        quote_number=quotation.quote_number,
        status=_PORTAL_STATUS.get(internal, internal),
        total_amount=quotation.total_amount,
        currency=quotation.currency,
        updated_at=quotation.updated_at,
        valid_until=quotation.valid_until,
    )


def _detail(
    quotation: Quotation, comments: list[PortalCommentResponse]
) -> PortalQuotationDetailResponse:
    return PortalQuotationDetailResponse(
        **_summary(quotation).model_dump(),
        customer_name=quotation.customer.name,
        subtotal_amount=quotation.subtotal_amount,
        discount_amount=quotation.discount_amount,
        tax_amount=quotation.tax_amount,
        lines=[
            PortalLineResponse(
                line_number=line.line_number,
                product_name=line.product.name,
                quantity=line.quantity,
                unit_list_price=line.unit_list_price,
                discount_percent=line.discount_percent,
                line_total=line.line_total,
            )
            for line in sorted(quotation.lines, key=lambda line: line.line_number)
        ],
        comments=comments,
        can_negotiate=quotation.status in NEGOTIABLE_STATUSES,
    )


async def _comments(session: SessionDep, quotation_id: int) -> list[PortalCommentResponse]:
    return [
        PortalCommentResponse(
            created_at=entry.created_at,
            author_name=entry.user.full_name if entry.user else None,
            message=entry.reason or "",
        )
        for entry in await negotiation_history(session, quotation_id)
    ]


async def _load(session: SessionDep, user: User, quotation_id: int) -> Quotation:
    if user.customer_id is None:
        raise _no_customer(user)
    quotation = await load_customer_quotation(session, quotation_id, customer_id=user.customer_id)
    # A quotation that exists but is still a draft is reported as not found,
    # not as forbidden: "this quote number exists but you cannot see it yet"
    # is itself information the customer has no business having.
    if quotation is None or quotation.status not in _VISIBLE_STATUSES:
        raise _NOT_FOUND
    return quotation


@router.get("/quotations", response_model=list[PortalQuotationSummaryResponse])
async def list_my_quotations(
    session: SessionDep, user: PortalViewer
) -> list[PortalQuotationSummaryResponse]:
    """The portal shell's "My Quotations" list (FRONTEND.md Section 2.2)."""
    if user.customer_id is None:
        raise _no_customer(user)

    rows = (
        (
            await session.execute(
                select(Quotation)
                .where(
                    Quotation.customer_id == user.customer_id,
                    Quotation.status.in_(_VISIBLE_STATUSES),
                )
                .order_by(Quotation.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_summary(q) for q in rows]


@router.get("/quotations/{quotation_id}", response_model=PortalQuotationDetailResponse)
async def get_my_quotation(
    quotation_id: int, session: SessionDep, user: PortalViewer
) -> PortalQuotationDetailResponse:
    """Screen 11."""
    quotation = await _load(session, user, quotation_id)
    return _detail(quotation, await _comments(session, quotation_id))


@router.post("/quotations/{quotation_id}/negotiate", response_model=PortalQuotationDetailResponse)
async def negotiate(
    request: Request,
    quotation_id: int,
    payload: PortalNegotiateRequest,
    session: SessionDep,
    user: PortalNegotiator,
) -> PortalQuotationDetailResponse:
    """PRD B8's `Submit Request`: a comment, optionally with a counter discount.

    Requires `portal.own_quote.negotiate` separately from viewing, so a
    read-only portal account remains possible without code changes.
    """
    quotation = await _load(session, user, quotation_id)

    try:
        await submit_counter_offer(
            session,
            quotation,
            counter_discount_percent=payload.counter_discount_percent,
        )
    except PortalError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # Locked Business Rules #8b: the counter-offer IS the audit event. The
    # customer's own words are stored verbatim as the reason, with the counter
    # appended, so the thread on Screen 11 and the trail an approver reads on
    # Screen 6 are the same record rather than two that could disagree.
    counter = payload.counter_discount_percent
    reason = payload.comment if counter is None else f"{payload.comment} [counter: {counter}%]"
    await audit.record(
        session,
        action=AuditAction.PORTAL_COUNTER_OFFER,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason=reason,
        request=request,
    )
    await session.commit()

    quotation = await _load(session, user, quotation_id)
    return _detail(quotation, await _comments(session, quotation_id))


@router.post("/quotations/{quotation_id}/confirm", response_model=PortalConfirmResponse)
async def confirm(
    request: Request,
    quotation_id: int,
    session: SessionDep,
    user: PortalNegotiator,
) -> PortalConfirmResponse:
    """PRD B8's `Confirm Quotation` — the real one.

    Two outcomes, both from the PRD: terms that need approval send the quote
    back into the approval flow automatically; terms that do not confirm the
    order, which generates its billing schedule and unlocks fulfillment.
    """
    quotation = await _load(session, user, quotation_id)

    try:
        outcome = await confirm_from_portal(session, quotation, actor_id=user.id)
    except PortalError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if outcome.re_entered_approval:
        # The origin is recorded in the reason, which is what lets Screen 6
        # show "re-entered approval after a customer counter-offer" instead of
        # looking identical to a first-time submission (FRONTEND.md Screen 6).
        await audit.record(
            session,
            action=AuditAction.DISCOUNT_APPROVAL_REQUESTED,
            user_id=user.id,
            resource="quotation",
            resource_id=quotation.id,
            reason=(
                "customer confirmed negotiated terms; re-entered approval "
                f"(risk {outcome.assessment.blended_score}) -> " + ", ".join(outcome.required_steps)
            ),
            request=request,
        )
        message = (
            "Thank you. Your updated terms need internal approval before the order can be "
            "placed, and have been sent for review."
        )
    else:
        await audit.record(
            session,
            action=AuditAction.QUOTATION_STATUS_CHANGED,
            user_id=user.id,
            resource="quotation",
            resource_id=quotation.id,
            reason="confirmed by the customer from the portal",
            request=request,
        )
        message = "Thank you. Your order is confirmed and has been passed to our team."

    await session.commit()

    quotation = await _load(session, user, quotation_id)
    return PortalConfirmResponse(
        quotation=_detail(quotation, await _comments(session, quotation_id)),
        re_entered_approval=outcome.re_entered_approval,
        message=message,
    )
