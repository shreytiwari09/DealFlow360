"""Dashboard KPIs and recent activity - FRONTEND.md Screen 2."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep, has_permission
from app.models.approval import ApprovalRequest
from app.models.audit import AuditLog
from app.models.enums import ApprovalStatus, QuotationStatus, RoleCode
from app.models.quotation import Quotation
from app.schemas.api import AuditEntryResponse, DashboardResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_OPEN_STATUSES = (
    QuotationStatus.DRAFT,
    QuotationStatus.PENDING_APPROVAL,
    QuotationStatus.APPROVED,
    QuotationStatus.SENT,
    QuotationStatus.UNDER_NEGOTIATION,
)


@router.get("", response_model=DashboardResponse)
async def summary(session: SessionDep, user: CurrentUser) -> DashboardResponse:
    """KPI counts, scoped the same way the list screens are.

    FRONTEND.md Section 9 item 11 flags per-role scoping as TBD; the default
    applied here is the one proposed there - a rep sees their own deals, every
    other internal role sees org-wide.
    """
    scoped = not (has_permission(user, "deal.read_all") or has_permission(user, "deal.read_team"))

    open_stmt = select(func.count(Quotation.id)).where(Quotation.status.in_(_OPEN_STATUSES))
    pending_stmt = (
        select(func.count(ApprovalRequest.id))
        .join(Quotation, Quotation.id == ApprovalRequest.quotation_id)
        .where(ApprovalRequest.status == ApprovalStatus.PENDING)
    )
    at_risk_stmt = select(func.count(Quotation.id)).where(
        Quotation.status.in_(_OPEN_STATUSES), Quotation.max_line_excess > 0
    )

    if user.role.code == RoleCode.CUSTOMER:
        open_stmt = open_stmt.where(Quotation.customer_id == user.customer_id)
        pending_stmt = pending_stmt.where(Quotation.customer_id == user.customer_id)
        at_risk_stmt = at_risk_stmt.where(Quotation.customer_id == user.customer_id)
    elif scoped:
        open_stmt = open_stmt.where(Quotation.owner_id == user.id)
        pending_stmt = pending_stmt.where(Quotation.owner_id == user.id)
        at_risk_stmt = at_risk_stmt.where(Quotation.owner_id == user.id)

    activity = (
        (
            await session.execute(
                select(AuditLog)
                .options(selectinload(AuditLog.user))
                .where(AuditLog.resource == "quotation")
                .order_by(AuditLog.created_at.desc())
                .limit(8)
            )
        )
        .scalars()
        .all()
    )

    return DashboardResponse(
        pending_approvals=(await session.execute(pending_stmt)).scalar_one(),
        open_quotations=(await session.execute(open_stmt)).scalar_one(),
        at_risk_deals=(await session.execute(at_risk_stmt)).scalar_one(),
        recent_activity=[
            AuditEntryResponse(
                user_name=entry.user.full_name if entry.user else None,
                action=entry.action,
                created_at=entry.created_at,
                reason=entry.reason,
            )
            for entry in activity
        ],
    )
