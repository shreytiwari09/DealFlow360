"""Deal Health and Anomaly Dashboard — FRONTEND.md Screen 14, PRD B9."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep, has_permission
from app.models.audit import AuditAction
from app.models.enums import RoleCode
from app.models.quotation import Quotation
from app.schemas.api import DealHealthAlertResponse, DealHealthDashboardResponse
from app.services import audit
from app.services.dealhealth import refresh_dashboard

router = APIRouter(prefix="/deal-health", tags=["deal-health"])


@router.get("", response_model=DealHealthDashboardResponse)
async def dashboard(session: SessionDep, user: CurrentUser) -> DealHealthDashboardResponse:
    """Scoped the same way the quotations list and Screen 2's dashboard are:
    a rep sees only their own deals, everyone else sees every open deal
    (FRONTEND.md: "Sales Rep (view own deals, read-only)")."""
    if user.role.code == RoleCode.CUSTOMER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not available.")

    scoped = not (has_permission(user, "deal.read_all") or has_permission(user, "deal.read_team"))
    results = await refresh_dashboard(session, owner_id=user.id if scoped else None)
    await session.commit()

    alerts = [
        DealHealthAlertResponse(
            quotation_id=r.quotation.id,
            quote_number=r.quotation.quote_number,
            customer_name=r.quotation.customer.name,
            owner_name=r.quotation.owner.full_name,
            is_stalled=r.is_stalled,
            days_inactive=r.days_inactive,
            has_discount_anomaly=r.has_discount_anomaly,
            discount_vs_rep_average=r.discount_vs_rep_average,
            has_delivery_slippage=r.has_delivery_slippage,
            days_slipped=r.days_slipped,
            snapshot_at=r.quotation.last_activity_at,
        )
        for r in results
    ]
    # Worst-first: stalled+anomaly+slippage together outranks any single flag.
    alerts.sort(
        key=lambda a: (
            a.is_stalled + a.has_discount_anomaly + a.has_delivery_slippage,
            a.days_inactive,
        ),
        reverse=True,
    )

    return DealHealthDashboardResponse(
        stalled_count=sum(1 for a in alerts if a.is_stalled),
        anomaly_count=sum(1 for a in alerts if a.has_discount_anomaly),
        slippage_count=sum(1 for a in alerts if a.has_delivery_slippage),
        alerts=alerts,
    )


async def _load_and_authorize(
    session: SessionDep, user: CurrentUser, quotation_id: int
) -> Quotation:
    quotation = (
        await session.execute(select(Quotation).where(Quotation.id == quotation_id))
    ).scalar_one_or_none()
    if quotation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quotation not found.")
    if not (
        has_permission(user, "deal.read_all")
        or has_permission(user, "deal.read_team")
        or quotation.owner_id == user.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted.")
    return quotation


@router.post("/{quotation_id}/nudge")
async def nudge_rep(
    request: Request, quotation_id: int, session: SessionDep, user: CurrentUser
) -> dict[str, str]:
    """PRD B9: "an automated nudge or escalation action can be triggered from
    an alert." No email/notification channel exists to actually deliver a
    nudge (out of scope — see Known Issues), so this records the action
    itself, which is the auditable event a manager would point to either way.
    """
    quotation = await _load_and_authorize(session, user, quotation_id)
    await audit.record(
        session,
        action=AuditAction.DEAL_NUDGE_SENT,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason="nudge sent to rep from the Deal Health dashboard",
        request=request,
    )
    await session.commit()
    return {"status": "nudged"}


@router.post("/{quotation_id}/escalate")
async def escalate(
    request: Request, quotation_id: int, session: SessionDep, user: CurrentUser
) -> dict[str, str]:
    quotation = await _load_and_authorize(session, user, quotation_id)
    await audit.record(
        session,
        action=AuditAction.DEAL_NUDGE_SENT,
        user_id=user.id,
        resource="quotation",
        resource_id=quotation.id,
        reason="escalated to Sales Manager from the Deal Health dashboard",
        request=request,
    )
    await session.commit()
    return {"status": "escalated"}
