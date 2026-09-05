"""Approval routing: turning a risk assessment into approval records.

The routing decision itself lives in `app/services/risk.py` and is pure. This
module is the thin layer that reads the configured bands out of
`approval_chains`, asks the router what steps are needed, and persists them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.enums import ApprovalStatus, RoleCode
from app.models.policy import ApprovalChain
from app.models.quotation import Quotation
from app.models.rbac import Role
from app.services.risk import ApprovalBand, ApprovalStepPlan, RiskAssessment, plan_approval_steps


def risk_band(assessment: RiskAssessment) -> str:
    """The LOW / MEDIUM / HIGH badge FRONTEND.md Screens 5 and 6 display.

    Derived from the routing outcome rather than from raw score thresholds, so
    the badge can never disagree with who actually has to approve — which is
    the thing an approver is really being told.
    """
    if not assessment.requires_approval:
        return "LOW"
    if assessment.finance_gate_tripped:
        return "HIGH"
    return "MEDIUM"


async def load_bands(session: AsyncSession) -> list[ApprovalBand]:
    rows = await session.execute(
        select(
            ApprovalChain.min_score,
            ApprovalChain.max_score,
            Role.code,
            ApprovalChain.step_order,
        )
        .join(Role, Role.id == ApprovalChain.required_role_id)
        .where(ApprovalChain.is_active.is_(True))
    )
    return [
        ApprovalBand(
            min_score=min_score,
            max_score=max_score,
            role_code=role_code,
            step_order=step_order,
        )
        for min_score, max_score, role_code, step_order in rows.all()
    ]


async def raise_approval_request(
    session: AsyncSession,
    quotation: Quotation,
    assessment: RiskAssessment,
    *,
    dry_run: bool = False,
) -> list[ApprovalStepPlan]:
    """Work out the required steps and, unless `dry_run`, persist them.

    `dry_run` powers the live risk preview on the builder: the rep sees which
    approvals a discount *would* trigger before committing to it, without
    littering the database with speculative approval requests.

    A re-submission creates a NEW request rather than reopening the previous
    one. That is what preserves the history of who approved what across a
    customer counter-offer (PRD B8), and it is why decided approvals are
    terminal in the state machine.
    """
    bands = await load_bands(session)
    steps = list(plan_approval_steps(assessment, bands, escalation_role_code=RoleCode.FINANCE_OPS))

    if dry_run or not steps:
        return steps

    role_ids = {
        code: role_id for code, role_id in (await session.execute(select(Role.code, Role.id))).all()
    }

    request = ApprovalRequest(
        quotation_id=quotation.id,
        blended_risk_score=assessment.blended_score,
        max_line_excess=assessment.max_line_excess,
        triggered_by_line_gate=assessment.finance_gate_tripped,
        status=ApprovalStatus.PENDING,
        requested_at=datetime.now(UTC),
        created_by=quotation.owner_id,
    )
    session.add(request)
    await session.flush()

    for step in steps:
        session.add(
            ApprovalStep(
                request_id=request.id,
                step_order=step.step_order,
                # Snapshotted: reconfiguring the chain later must not rewrite
                # who was supposed to approve this deal.
                required_role_id=role_ids[step.role_code],
                status=ApprovalStatus.PENDING,
                created_by=quotation.owner_id,
            )
        )
    await session.flush()
    return steps


async def current_step(session: AsyncSession, request: ApprovalRequest) -> ApprovalStep | None:
    """The lowest-ordered step still pending — the one awaiting a decision.

    Steps are sequential: Finance never acts before the Manager has.
    """
    pending = [step for step in request.steps if step.status == ApprovalStatus.PENDING]
    if not pending:
        return None
    return min(pending, key=lambda step: step.step_order)
