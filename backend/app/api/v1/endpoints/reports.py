"""Reporting — FRONTEND.md Screen 15, PRD A7.

Filters match PRD A7's "Reporting Filters" section exactly: Period, Sales
Team/Rep, Approval Status, Product/Category. Scoped the same way every other
list in this app is: a rep sees only their own quotations; a permission that
grants a broader read (`deal.read_all`/`deal.read_team`) sees everything,
further narrowable by the same filters.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from starlette.responses import StreamingResponse

from app.api.deps import SessionDep, has_permission, require_permission
from app.models.rbac import User
from app.schemas.api import ReportResponse, ReportRow
from app.services.reports import ReportFilters, build_report, render_pdf, render_xlsx

router = APIRouter(prefix="/reports", tags=["reports"])

CanViewReports = Annotated[User, Depends(require_permission("report.view"))]

DateFrom = Annotated[date | None, Query()]
DateTo = Annotated[date | None, Query()]
OwnerId = Annotated[int | None, Query()]
StatusFilter = Annotated[str | None, Query()]
CategoryId = Annotated[int | None, Query()]


def _owner_scope(user: User) -> int | None:
    if has_permission(user, "deal.read_all") or has_permission(user, "deal.read_team"):
        return None
    return user.id


@router.get("", response_model=ReportResponse)
async def get_report(
    session: SessionDep,
    user: CanViewReports,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    owner_id: OwnerId = None,
    status: StatusFilter = None,
    category_id: CategoryId = None,
) -> ReportResponse:
    report = await build_report(
        session,
        ReportFilters(
            date_from=date_from,
            date_to=date_to,
            owner_id=owner_id,
            status=status,
            category_id=category_id,
        ),
        owner_scope=_owner_scope(user),
    )
    return ReportResponse(
        rows=[
            ReportRow(
                quote_number=r.quote_number,
                customer_name=r.customer_name,
                owner_name=r.owner_name,
                status=r.status,
                total_amount=r.total_amount,
                discount_amount=r.discount_amount,
                blended_risk_score=r.blended_risk_score,
                created_at=r.created_at,
            )
            for r in report.rows
        ],
        total_amount=report.total_amount,
        total_discount=report.total_discount,
        count=len(report.rows),
    )


@router.get("/export")
async def export_report(
    session: SessionDep,
    user: CanViewReports,
    format: Literal["xlsx", "pdf"],
    date_from: DateFrom = None,
    date_to: DateTo = None,
    owner_id: OwnerId = None,
    status: StatusFilter = None,
    category_id: CategoryId = None,
) -> Response:
    """PRD A7: `Export PDF`, `Export XLS`. Same filters, same scoping as the
    JSON view — an export must never show a rep data the screen itself would
    have hidden from them."""
    report = await build_report(
        session,
        ReportFilters(
            date_from=date_from,
            date_to=date_to,
            owner_id=owner_id,
            status=status,
            category_id=category_id,
        ),
        owner_scope=_owner_scope(user),
    )

    if format == "xlsx":
        content = render_xlsx(report)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "dealflow360-report.xlsx"
    else:
        content = render_pdf(report)
        media_type = "application/pdf"
        filename = "dealflow360-report.pdf"

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
