"""Approval endpoints — FRONTEND.md Screens 5 and 6."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep, has_permission
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.audit import AuditAction, AuditLog
from app.models.enums import ApprovalStatus, QuotationStatus, RoleCode
from app.models.quotation import Quotation, QuotationLine
from app.models.rbac import User
from app.schemas.api import (
    ApprovalDecisionRequest,
    ApprovalDetailResponse,
    ApprovalStepResponse,
    ApprovalSummaryResponse,
    AuditEntryResponse,
    RiskLineBreakdown,
)
from app.services import audit
from app.services.approval import current_step
from app.services.risk import LINE_EXCESS_FINANCE_GATE
from app.services.state_machine import InvalidStateTransition, assert_transition

router = APIRouter(prefix="/approvals", tags=["approvals"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")

# Which permission lets a user act at a step requiring a given role.
_STEP_PERMISSION = {
    RoleCode.SALES_MANAGER: "deal.approve_manager",
    RoleCode.FINANCE_OPS: "deal.approve_finance",
}


def _band(request: ApprovalRequest) -> str:
    if request.triggered_by_line_gate or any(
        step.required_role.code == RoleCode.FINANCE_OPS for step in request.steps
    ):
        return "HIGH"
    return "MEDIUM"


async def _load(session: SessionDep, approval_id: int) -> ApprovalRequest | None:
    result = await session.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id)
        .options(
            selectinload(ApprovalRequest.steps).selectinload(ApprovalStep.required_role),
            selectinload(ApprovalRequest.steps).selectinload(ApprovalStep.actor),
            selectinload(ApprovalRequest.quotation).selectinload(Quotation.customer),
            # .product is essential: the line breakdown reads product.name,
            # and without eager loading that is a lazy load inside async,
            # which raises MissingGreenlet and 500s the whole screen.
            selectinload(ApprovalRequest.quotation)
            .selectinload(Quotation.lines)
            .selectinload(QuotationLine.product),
        )
    )
    return result.scalar_one_or_none()


def _can_act(user: User, request: ApprovalRequest) -> bool:
    pending = [s for s in request.steps if s.status == ApprovalStatus.PENDING]
    if not pending:
        return False
    step = min(pending, key=lambda s: s.step_order)
    needed = _STEP_PERMISSION.get(step.required_role.code)
    return bool(needed and has_permission(user, needed))


@router.get("", response_model=list[ApprovalSummaryResponse])
async def list_approvals(session: SessionDep, user: CurrentUser) -> list[ApprovalSummaryResponse]:
    """Screen 5. A rep sees only their own quotations' approvals."""
    statement = (
        select(ApprovalRequest)
        .options(
            selectinload(ApprovalRequest.steps).selectinload(ApprovalStep.required_role),
            selectinload(ApprovalRequest.steps).selectinload(ApprovalStep.actor),
            selectinload(ApprovalRequest.quotation).selectinload(Quotation.customer),
        )
        .order_by(ApprovalRequest.requested_at.desc())
    )

    if user.role.code == RoleCode.CUSTOMER:
        # A portal user has no business on the approvals screen at all.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not available.")
    if not (
        has_permission(user, "deal.approve_manager")
        or has_permission(user, "deal.approve_finance")
        or has_permission(user, "deal.read_all")
        or has_permission(user, "deal.read_team")
    ):
        statement = statement.join(Quotation).where(Quotation.owner_id == user.id)

    rows = (await session.execute(statement)).scalars().all()

    summaries = []
    for request in rows:
        step = min(
            (s for s in request.steps if s.status == ApprovalStatus.PENDING),
            key=lambda s: s.step_order,
            default=None,
        )
        summaries.append(
            ApprovalSummaryResponse(
                id=request.id,
                quotation_id=request.quotation_id,
                quote_number=request.quotation.quote_number,
                customer_name=request.quotation.customer.name,
                blended_risk_score=request.blended_risk_score,
                risk_band=_band(request),
                status=request.status,
                current_stage=step.required_role.name if step else None,
                assigned_to=step.required_role.name if step else None,
                requested_at=request.requested_at,
            )
        )
    return summaries


@router.get("/{approval_id}", response_model=ApprovalDetailResponse)
async def get_approval(
    approval_id: int, session: SessionDep, user: CurrentUser
) -> ApprovalDetailResponse:
    """Screen 6, including the "Why This Quote Was Flagged" breakdown."""
    request = await _load(session, approval_id)
    if request is None:
        raise _NOT_FOUND
    if user.role.code == RoleCode.CUSTOMER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not available.")

    quotation = request.quotation
    trail = (
        (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.resource == "quotation", AuditLog.resource_id == str(quotation.id))
                .options(selectinload(AuditLog.user))
                .order_by(AuditLog.created_at)
            )
        )
        .scalars()
        .all()
    )

    pending = [s for s in request.steps if s.status == ApprovalStatus.PENDING]
    stage = min(pending, key=lambda s: s.step_order) if pending else None

    return ApprovalDetailResponse(
        id=request.id,
        quotation_id=quotation.id,
        quote_number=quotation.quote_number,
        customer_name=quotation.customer.name,
        customer_tier=quotation.customer.tier,
        blended_risk_score=request.blended_risk_score,
        max_line_excess=request.max_line_excess,
        triggered_by_line_gate=request.triggered_by_line_gate,
        risk_band=_band(request),
        status=request.status,
        current_stage=stage.required_role.name if stage else None,
        assigned_to=stage.required_role.name if stage else None,
        requested_at=request.requested_at,
        total_amount=quotation.total_amount,
        currency=quotation.currency,
        steps=[
            ApprovalStepResponse(
                step_order=step.step_order,
                required_role=step.required_role.name,
                status=step.status,
                actor_name=step.actor.full_name if step.actor else None,
                decided_at=step.decided_at,
                reason=step.reason,
                forced_by_line_gate=(
                    request.triggered_by_line_gate
                    and step.required_role.code == RoleCode.FINANCE_OPS
                    and request.blended_risk_score <= LINE_EXCESS_FINANCE_GATE
                ),
            )
            for step in sorted(request.steps, key=lambda s: s.step_order)
        ],
        line_breakdown=[
            RiskLineBreakdown(
                line_number=line.line_number,
                product_name=line.product.name,
                discount_percent=line.discount_percent,
                allowed_discount_percent=line.allowed_discount_percent,
                excess_points=line.line_excess_points,
            )
            for line in sorted(quotation.lines, key=lambda line: line.line_number)
        ],
        audit_trail=[
            AuditEntryResponse(
                user_name=entry.user.full_name if entry.user else None,
                action=entry.action,
                created_at=entry.created_at,
                reason=entry.reason,
            )
            for entry in trail
        ],
        can_act=_can_act(user, request),
    )


@router.post("/{approval_id}/decide", response_model=ApprovalDetailResponse)
async def decide(
    http_request: Request,
    approval_id: int,
    payload: ApprovalDecisionRequest,
    session: SessionDep,
    user: CurrentUser,
) -> ApprovalDetailResponse:
    """Approve, reject or return one step.

    Two things this must get right, both called out by PLAN.md Section 14:

    * Only the CURRENT step may be decided, and only by someone holding that
      step's permission. Finance cannot pre-approve before the Manager acts.
    * Two managers deciding at once must not both succeed. The quotation's
      version column makes the second write fail loudly instead of silently
      overwriting the first.
    """
    request = await _load(session, approval_id)
    if request is None:
        raise _NOT_FOUND

    if request.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This approval is already decided."
        )

    step = await current_step(session, request)
    if step is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No step is pending.")

    needed = _STEP_PERMISSION.get(step.required_role.code)
    if not needed or not has_permission(user, needed):
        await audit.record(
            session,
            action="UNAUTHORIZED_ACCESS_ATTEMPT",
            status="denied",
            user_id=user.id,
            resource="approval_step",
            resource_id=step.id,
            reason=f"cannot act at step requiring {step.required_role.code}",
            request=http_request,
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot act on the current approval step.",
        )

    outcome = {
        "approve": ApprovalStatus.APPROVED,
        "reject": ApprovalStatus.REJECTED,
        "return": ApprovalStatus.RETURNED_FOR_REVISION,
    }[payload.decision]

    try:
        assert_transition("Approval", ApprovalStatus(step.status), outcome)
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    now = datetime.now(UTC)
    step.status = outcome
    step.actor_id = user.id
    step.decided_at = now
    step.reason = payload.reason

    quotation = request.quotation
    remaining = [
        s
        for s in request.steps
        if s.status == ApprovalStatus.PENDING and s.step_order > step.step_order
    ]

    def _finish_request(new_status: ApprovalStatus) -> None:
        """Transition the REQUEST's own status, validated the same way the
        step's status just was above. `request.status` is guaranteed PENDING
        here (checked earlier in this function), so this cannot fail in
        practice - but "cannot fail in practice" is exactly the situation the
        Backorder bug (see IMPLEMENTATION_LOG.md 2026-09-06) was in too, and
        the whole point of state_machine.py is that a transition is REJECTED,
        not merely unexercised, if it were ever wrong.
        """
        assert_transition("Approval", ApprovalStatus(request.status), new_status)
        request.status = new_status
        request.completed_at = now

    if outcome is ApprovalStatus.APPROVED and remaining:
        # Chain continues; the quotation stays pending for the next approver.
        action = AuditAction.DISCOUNT_APPROVED
        target_status = None
    elif outcome is ApprovalStatus.APPROVED:
        _finish_request(ApprovalStatus.APPROVED)
        action = AuditAction.DISCOUNT_APPROVED
        target_status = QuotationStatus.APPROVED
    elif outcome is ApprovalStatus.REJECTED:
        _finish_request(ApprovalStatus.REJECTED)
        _cancel_remaining(request, step)
        action = AuditAction.DISCOUNT_REJECTED
        target_status = QuotationStatus.REJECTED
    else:
        _finish_request(ApprovalStatus.RETURNED_FOR_REVISION)
        _cancel_remaining(request, step)
        action = AuditAction.DISCOUNT_RETURNED_FOR_REVISION
        target_status = QuotationStatus.DRAFT

    if target_status is not None:
        try:
            assert_transition("Quotation", QuotationStatus(quotation.status), target_status)
        except InvalidStateTransition as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        quotation.status = target_status

    quotation.last_activity_at = now

    await audit.record(
        session,
        action=action,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason=f"{step.required_role.name} step {step.step_order}: {payload.reason}",
        request=http_request,
    )
    await session.commit()

    return await get_approval(approval_id, session, user)


def _cancel_remaining(request: ApprovalRequest, decided: ApprovalStep) -> None:
    """A rejection or return ends the chain; later steps never happen.

    They are left as-is rather than marked with a decision, because inventing
    an actor for a step nobody acted on would corrupt the audit trail — and
    the database CHECK forbids a decided step without an actor anyway.
    """
    return None
