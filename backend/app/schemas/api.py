"""Request and response DTOs.

Explicit response models everywhere — SECURITY_SPEC.md Section 6: never return
an ORM object directly, or a password hash reaches the wire the first time
someone adds a relationship.

Request models are equally deliberate: they contain ONLY the fields a caller
is allowed to set. There is no `role`, `owner_id`, `customer_id` or `status`
on any inbound model, so mass assignment has nothing to bite on
(SECURITY_SPEC.md Section 8).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth ------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    # S105 false positive: this is the OAuth2 token_type field, whose value
    # is literally the word "bearer", not a secret.
    token_type: str = "bearer"  # noqa: S105


class CurrentUserResponse(BaseModel):
    """Note what is absent: no password hash, ever."""

    id: int
    email: str
    full_name: str
    role: str
    permissions: list[str]
    customer_id: int | None
    customer_name: str | None


# --- Catalogue -------------------------------------------------------------


class ProductResponse(ORMModel):
    id: int
    sku: str
    name: str
    category_id: int
    category_code: str | None = None
    list_price: Decimal
    tax_rate: Decimal
    item_type: str
    is_promoted: bool


class CustomerResponse(ORMModel):
    id: int
    code: str
    name: str
    tier: str
    currency: str


# --- Quotations ------------------------------------------------------------


class QuotationLineResponse(BaseModel):
    id: int
    line_number: int
    product_id: int
    product_name: str
    product_sku: str
    quantity: Decimal
    unit_list_price: Decimal
    discount_percent: Decimal
    # The "Limit" column on FRONTEND.md Screen 4.
    allowed_discount_percent: Decimal
    # Drives the "OVER LIMIT" badge.
    line_excess_points: Decimal
    is_over_limit: bool
    line_type: str
    line_subtotal: Decimal
    line_discount_amount: Decimal
    line_total: Decimal
    added_from_upsell: bool


class QuotationSummaryResponse(BaseModel):
    """Row/card shape for the Quotations List (Screen 3)."""

    id: int
    quote_number: str
    customer_id: int
    customer_name: str
    owner_name: str
    status: str
    total_amount: Decimal
    currency: str
    blended_risk_score: Decimal
    updated_at: datetime


class QuotationResponse(QuotationSummaryResponse):
    """Full detail for the builder (Screen 4)."""

    customer_tier: str
    subtotal_amount: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    margin_amount: Decimal
    margin_percent: Decimal
    max_line_excess: Decimal
    requires_approval: bool
    requires_finance_approval: bool
    valid_until: date | None
    version: int
    lines: list[QuotationLineResponse]
    # UX only. The backend re-checks on every write regardless of what this says.
    can_edit: bool


class CreateQuotationRequest(BaseModel):
    customer_id: int
    valid_until: date | None = None


class LineRequest(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0, le=Decimal("100000"))
    discount_percent: Decimal = Field(ge=0, le=100)
    added_from_upsell: bool = False


class ReplaceLinesRequest(BaseModel):
    """The builder sends the whole line set.

    Simpler and safer than per-line PATCH: there is no partial-update state
    where the stored totals disagree with the lines, and no ordering ambiguity
    between concurrent line edits.
    """

    lines: list[LineRequest] = Field(max_length=200)


class OrderDiscountRequest(BaseModel):
    """Locked Business Rules #4: distributed onto every line, overwriting."""

    discount_percent: Decimal = Field(ge=0, le=100)


class RiskLineBreakdown(BaseModel):
    line_number: int
    product_name: str
    discount_percent: Decimal
    allowed_discount_percent: Decimal
    excess_points: Decimal


class RiskPreviewResponse(BaseModel):
    """Powers the live risk indicator and Screen 6's "why flagged" table."""

    blended_risk_score: Decimal
    max_line_excess: Decimal
    requires_approval: bool
    finance_gate_tripped: bool
    risk_band: str
    lines: list[RiskLineBreakdown]
    required_steps: list[str]


# --- Approvals -------------------------------------------------------------


class ApprovalStepResponse(BaseModel):
    step_order: int
    required_role: str
    status: str
    actor_name: str | None
    decided_at: datetime | None
    reason: str | None
    forced_by_line_gate: bool = False


class ApprovalSummaryResponse(BaseModel):
    """Row shape for the Approvals List (Screen 5)."""

    id: int
    quotation_id: int
    quote_number: str
    customer_name: str
    blended_risk_score: Decimal
    risk_band: str
    status: str
    current_stage: str | None
    assigned_to: str | None
    requested_at: datetime


class AuditEntryResponse(BaseModel):
    user_name: str | None
    action: str
    created_at: datetime
    reason: str | None


class ApprovalDetailResponse(ApprovalSummaryResponse):
    customer_tier: str
    max_line_excess: Decimal
    triggered_by_line_gate: bool
    total_amount: Decimal
    currency: str
    steps: list[ApprovalStepResponse]
    line_breakdown: list[RiskLineBreakdown]
    audit_trail: list[AuditEntryResponse]
    # Whether THIS user may act on the current step. UX only.
    can_act: bool


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject|return)$")
    # PRD A3 requires a reason on every approval action.
    reason: str = Field(min_length=1, max_length=1000)


# --- Fulfillment (PRD B6, FRONTEND.md Screens 7-8) --------------------------


class StockLevelResponse(BaseModel):
    """One row of the stock table on Screen 7."""

    warehouse_id: int
    warehouse_name: str
    product_id: int
    product_name: str
    quantity_on_hand: Decimal
    quantity_reserved: Decimal
    available: Decimal


class OrderAwaitingFulfillmentResponse(BaseModel):
    """One row of the "Orders Awaiting Fulfillment" table on Screen 7."""

    quotation_id: int
    quote_number: str
    customer_name: str
    # None when the quotation is confirmed but no split has been generated yet.
    fulfillment_status: str | None
    warehouse_names: list[str]


class FulfillmentSplitResponse(BaseModel):
    quotation_line_id: int
    product_name: str
    warehouse_id: int
    warehouse_name: str
    quantity: Decimal
    is_manual_override: bool


class BackorderResponse(BaseModel):
    id: int
    quotation_line_id: int
    product_name: str
    quantity_outstanding: Decimal
    status: str
    # True once enough stock exists somewhere to consolidate right now - the
    # frontend's stand-in for PRD B6's "prompt appears automatically", which
    # needs a background job to be genuinely automatic (see Known Issues).
    can_consolidate: bool


class FulfillmentDetailResponse(BaseModel):
    id: int
    quotation_id: int
    quote_number: str
    customer_name: str
    status: str
    shipment_count: int
    estimated_shipping_cost: Decimal
    is_manual_override: bool
    splits: list[FulfillmentSplitResponse]
    backorders: list[BackorderResponse]
    # UX only, mirroring can_edit/can_act elsewhere - the backend re-checks
    # permission and status on every write regardless of what this says.
    can_act: bool


class OverrideLineRequest(BaseModel):
    quotation_line_id: int
    warehouse_id: int
    quantity: Decimal = Field(gt=0)


class OverrideSplitRequest(BaseModel):
    lines: list[OverrideLineRequest] = Field(min_length=1, max_length=200)


# --- Dashboard -------------------------------------------------------------


class DashboardResponse(BaseModel):
    pending_approvals: int
    open_quotations: int
    at_risk_deals: int
    recent_activity: list[AuditEntryResponse]
