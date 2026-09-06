"""Customer portal negotiation (PRD B8).

The customer's two actions — counter-offer and confirm — and nothing else.
Everything the customer can change goes through the same code paths an
internal user's equivalent action does: a counter-offer is an order-level
discount (Locked Business Rules #4 and #8a), re-scored by the same risk
engine, routed by the same approval router, and confirmed by the same
`quotation.confirm`. The portal is a different *audience*, not a second set of
business rules — that is what stops the two drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.approval import ApprovalRequest
from app.models.audit import AuditAction, AuditLog
from app.models.enums import ApprovalStatus, QuotationStatus, RoleCode
from app.models.quotation import Quotation, QuotationLine
from app.services.approval import raise_approval_request
from app.services.quotation import confirm as confirm_quotation
from app.services.quotation import recalculate
from app.services.risk import RiskAssessment
from app.services.state_machine import InvalidStateTransition, assert_transition


class PortalError(Exception):
    """A portal action was attempted against a quotation that cannot take it."""


_PERCENT = Decimal("0.01")


def _percent(value: Decimal) -> Decimal:
    """Matches `quotation_lines.discount_percent`'s Numeric(5, 2) scale.

    Without this, a counter of `20` (parsed from JSON as a bare `Decimal("20")`,
    not `"20.00"`) prints as "20" in the very same response that shows every
    DB-round-tripped discount as "20.00" — the same cosmetic inconsistency
    fixed for subscription quantity in `services/billing.py`."""
    return value.quantize(_PERCENT, rounding=ROUND_HALF_UP)


# The statuses a customer may act on. PRD B8 names exactly "Sent, Under
# Negotiation, Confirmed", but internally a quotation that needed approval
# from the start also reaches `approved` before it can ever be `sent` to
# anyone - and PRD B3's own flow never adds a separate "send to customer"
# action after that approval clears. So `approved` is exactly as negotiable
# as `sent`: it is the state a rep-approved quote is actually IN when it
# first becomes visible to the customer at all. See
# `state_machine.py`'s QUOTATION_TRANSITIONS for the corresponding
# `approved -> under_negotiation` edge this required.
NEGOTIABLE_STATUSES = (
    QuotationStatus.SENT,
    QuotationStatus.APPROVED,
    QuotationStatus.UNDER_NEGOTIATION,
)


@dataclass(frozen=True)
class ConfirmOutcome:
    """What happened when the customer pressed Confirm Quotation.

    PRD B8 gives exactly two outcomes, and the customer is told which one:
    the quote re-entered approval, or the order is confirmed.
    """

    re_entered_approval: bool
    required_steps: tuple[str, ...]
    assessment: RiskAssessment


async def load_customer_quotation(
    session: AsyncSession, quotation_id: int, *, customer_id: int
) -> Quotation | None:
    """Load a quotation **scoped by customer_id in the query itself**.

    The ownership check in `deps.can_view_quotation` would catch a mismatch
    anyway; scoping here as well means a portal handler cannot accidentally
    hold another customer's row in a local variable at all. Defence in depth
    for the one screen an untrusted party actually reaches (SECURITY_SPEC.md
    Section 4, IDOR/BOLA).
    """
    result = await session.execute(
        select(Quotation)
        .where(Quotation.id == quotation_id, Quotation.customer_id == customer_id)
        .options(
            selectinload(Quotation.lines).selectinload(QuotationLine.product),
            selectinload(Quotation.customer),
            selectinload(Quotation.owner),
        )
    )
    return result.scalar_one_or_none()


async def negotiation_history(session: AsyncSession, quotation_id: int) -> list[AuditLog]:
    """The customer-visible comment thread, read out of the audit trail.

    Locked Business Rules #8b: counter-offers are audit events, not rows in a
    separate comments table. Only the customer's own counter-offers are
    returned — never the internal trail (approvals, discount edits, who
    reviewed what), which Screen 11 is explicitly forbidden from exposing.
    """
    result = await session.execute(
        select(AuditLog)
        .where(
            AuditLog.resource == "quotation",
            AuditLog.resource_id == str(quotation_id),
            AuditLog.action == AuditAction.PORTAL_COUNTER_OFFER,
        )
        .options(selectinload(AuditLog.user))
        .order_by(AuditLog.created_at)
    )
    return list(result.scalars().all())


@dataclass(frozen=True)
class CustomerMessage:
    """One row of the portal's "Messages" screen — a past comment, tagged
    with which quotation it belongs to so the screen can link back to it."""

    quotation_id: int
    quote_number: str
    entry: AuditLog


async def customer_message_history(
    session: AsyncSession, *, customer_id: int
) -> list[CustomerMessage]:
    """Every counter-offer/comment the customer has ever sent, across ALL of
    their quotations, newest first — the aggregate view `negotiation_history`
    deliberately does not provide (that one is scoped to a single quotation).

    Same data source and same restriction as `negotiation_history`: only
    `PORTAL_COUNTER_OFFER` events, never the internal approval/discount trail.
    Scoped by `customer_id` in the query itself, not just by which quotation
    ids happen to get passed in — the same defence-in-depth reasoning as
    `load_customer_quotation`.
    """
    quotations = (
        await session.execute(
            select(Quotation.id, Quotation.quote_number).where(Quotation.customer_id == customer_id)
        )
    ).all()
    if not quotations:
        return []
    quote_numbers = {str(qid): number for qid, number in quotations}

    result = await session.execute(
        select(AuditLog)
        .where(
            AuditLog.resource == "quotation",
            AuditLog.resource_id.in_(quote_numbers.keys()),
            AuditLog.action == AuditAction.PORTAL_COUNTER_OFFER,
        )
        .options(selectinload(AuditLog.user))
        .order_by(AuditLog.created_at.desc())
    )
    return [
        CustomerMessage(
            quotation_id=int(entry.resource_id),
            quote_number=quote_numbers[entry.resource_id],
            entry=entry,
        )
        for entry in result.scalars().all()
    ]


async def submit_counter_offer(
    session: AsyncSession,
    quotation: Quotation,
    *,
    counter_discount_percent: Decimal | None,
) -> RiskAssessment:
    """PRD B8's `Submit Request`: comments, and optionally a counter discount.

    Sends the quotation into `under_negotiation` the first time, then leaves
    it there for subsequent rounds — the state machine has no
    `under_negotiation → under_negotiation` self-loop, and inventing one to
    make the code uniform would weaken a real rule for a cosmetic reason, so
    the transition is asserted only when it actually happens.

    A counter discount is applied exactly like an internal order-level
    discount: written onto every line, overwriting (Locked Business Rules #4).
    Scoring it any other way would reopen the loophole the blended score
    exists to close.
    """
    if quotation.status not in NEGOTIABLE_STATUSES:
        raise PortalError(f"This quotation cannot be negotiated while it is '{quotation.status}'.")

    if quotation.status != QuotationStatus.UNDER_NEGOTIATION:
        try:
            assert_transition(
                "Quotation",
                QuotationStatus(quotation.status),
                QuotationStatus.UNDER_NEGOTIATION,
            )
        except InvalidStateTransition as exc:
            raise PortalError(str(exc)) from exc
        quotation.status = QuotationStatus.UNDER_NEGOTIATION

    if counter_discount_percent is not None:
        counter = _percent(counter_discount_percent)
        for line in quotation.lines:
            line.discount_percent = counter
        await session.flush()

    assessment = await recalculate(session, quotation)
    quotation.last_activity_at = datetime.now(UTC)
    await session.flush()
    return assessment


async def terms_already_approved(
    session: AsyncSession, quotation: Quotation, assessment: RiskAssessment
) -> bool:
    """Has an approver already signed off on *these exact* terms?

    This is what stops the re-approval loop from becoming a trap. A quotation
    that was approved at 18% and then sent still scores as breaching when it
    is re-scored on confirmation — nothing about it changed. Routing on the
    score alone would send it back to the same manager who just approved it,
    forever, and the customer could never confirm anything that ever needed an
    approval in the first place.

    So the question is not "do these terms breach policy?" but "have these
    terms been approved?". An `ApprovalRequest` snapshots the score and the
    max line excess it was raised for, so matching both against a request that
    reached APPROVED answers it exactly. A counter-offer that changes any
    discount changes at least one of those two numbers, so it will not match
    and will correctly re-enter approval.

    Deliberately strict in one direction: a counter that is still over the
    ceiling but *less* over than what was approved (18% -> 16%, ceiling 10%)
    does NOT match, and goes back for approval. Those are different terms that
    still breach policy, and "the customer talked us down a bit" is not a
    reason to skip the control.
    """
    result = await session.execute(
        select(ApprovalRequest.id).where(
            ApprovalRequest.quotation_id == quotation.id,
            ApprovalRequest.status == ApprovalStatus.APPROVED,
            ApprovalRequest.blended_risk_score == assessment.blended_score,
            ApprovalRequest.max_line_excess == assessment.max_line_excess,
        )
    )
    return result.scalars().first() is not None


async def confirm_from_portal(
    session: AsyncSession, quotation: Quotation, *, actor_id: int
) -> ConfirmOutcome:
    """PRD B8's `Confirm Quotation`, including the automatic re-approval loop.

    "If final terms exceed approval thresholds, the quotation automatically re
    enters the approval flow from B4. Otherwise, the order moves directly to
    fulfillment." Both halves are decided here, from a fresh score of the
    terms as they now stand — not from whatever the score was when the quote
    was first sent, which is precisely the number a counter-offer invalidates —
    and filtered through `terms_already_approved` so that terms an approver has
    already signed off on are not sent back to them unchanged.

    A re-entry raises a NEW approval request rather than reopening the old
    one; decided approvals are terminal, and the previous approver's decision
    on different terms must stay in the record as its own event.
    """
    if quotation.status not in NEGOTIABLE_STATUSES:
        raise PortalError(f"This quotation cannot be confirmed while it is '{quotation.status}'.")

    assessment = await recalculate(session, quotation)
    steps = (
        []
        if await terms_already_approved(session, quotation, assessment)
        else await raise_approval_request(session, quotation, assessment)
    )

    if steps:
        try:
            assert_transition(
                "Quotation",
                QuotationStatus(quotation.status),
                QuotationStatus.PENDING_APPROVAL,
            )
        except InvalidStateTransition as exc:
            raise PortalError(str(exc)) from exc
        quotation.status = QuotationStatus.PENDING_APPROVAL
        quotation.requires_finance_approval = any(
            step.role_code == RoleCode.FINANCE_OPS for step in steps
        )
        quotation.last_activity_at = datetime.now(UTC)
        await session.flush()
        return ConfirmOutcome(
            re_entered_approval=True,
            required_steps=tuple(step.role_code for step in steps),
            assessment=assessment,
        )

    try:
        await confirm_quotation(session, quotation, actor_id=actor_id)
    except InvalidStateTransition as exc:
        raise PortalError(str(exc)) from exc

    return ConfirmOutcome(
        re_entered_approval=False,
        required_steps=(),
        assessment=assessment,
    )
