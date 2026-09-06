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


class SignupRequest(BaseModel):
    """PRD A1 / Locked Business Rules #5: public signup, always a Sales Rep.

    There is deliberately no `role`, `role_id` or `customer_id` field here —
    SECURITY_SPEC.md Section 8's mass-assignment case ("a profile update must
    not silently allow {"role": "Admin"}") is enforced structurally, not by
    discipline: the field doesn't exist on this model, so there is nothing
    for a crafted request body to smuggle in even if the endpoint were
    careless about it.

    `EmailStr` (via the `email-validator` package) is real RFC 5321/5322
    validation, not a `.`/`@` regex — it rejects a bare "user@localhost" with
    no TLD as well as the more obviously wrong "not-an-email".
    """

    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(min_length=1, max_length=160)


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
    # Populated only for a subscription line — the builder's plan picker
    # needs both to show the current selection and to know it's editable.
    subscription_plan_id: int | None = None
    subscription_plan_name: str | None = None


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
    # Required for a subscription product, forbidden for a one-time product —
    # enforced in the endpoint against the product's actual item_type, not
    # trusted blindly (the same "never trust client-asserted shape" rule as
    # everything else inbound). See PROJECT_CONTEXT.md Remaining Work #1.
    subscription_plan_id: int | None = None


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


# --- Billing (PRD B7, FRONTEND.md Screens 9-10, 12-13) ---------------------


class SubscriptionPlanResponse(BaseModel):
    """The plan picker's data source (builder Screen 4)."""

    id: int
    code: str
    name: str
    billing_interval: str
    interval_count: int
    unit_amount: Decimal


class ProrationRecordResponse(BaseModel):
    """One row of a subscription's proration history (Screen 10).

    Every input is returned alongside the result — Locked Business Rules #3 —
    so the screen can show the calculation, not just its answer.
    """

    id: int
    change_date: date
    cycle_start: date
    cycle_end: date
    cycle_days: int
    remaining_days: int
    old_quantity: Decimal
    new_quantity: Decimal
    old_amount: Decimal
    new_amount: Decimal
    credit_amount: Decimal
    charge_amount: Decimal
    proration_amount: Decimal


class BillingScheduleResponse(BaseModel):
    """One row: a one-time invoice line, a recurring instalment, or a
    proration adjustment — `schedule_type`/`is_credit_note` distinguish them."""

    id: int
    quotation_id: int
    quote_number: str
    subscription_id: int | None
    schedule_type: str
    status: str
    due_date: date
    amount: Decimal
    cycle_start: date | None
    cycle_end: date | None
    invoice_number: str | None
    invoiced_at: datetime | None
    is_credit_note: bool


class SubscriptionSummaryResponse(BaseModel):
    """Row shape for the Subscriptions List (Screen 9)."""

    id: int
    quotation_id: int
    quote_number: str
    customer_name: str
    product_name: str
    plan_name: str
    status: str
    quantity: Decimal
    unit_amount: Decimal
    current_cycle_start: date
    current_cycle_end: date


class SubscriptionDetailResponse(SubscriptionSummaryResponse):
    """Screen 10: adds the full billing-schedule and proration history."""

    plan_id: int
    billing_schedules: list[BillingScheduleResponse]
    proration_history: list[ProrationRecordResponse]
    can_act: bool


class ModifySubscriptionRequest(BaseModel):
    """At least one of the two must be set; the endpoint rejects a no-op."""

    new_quantity: Decimal | None = Field(default=None, gt=0)
    new_plan_id: int | None = None


class PaymentResponse(BaseModel):
    id: int
    amount: Decimal
    method: str
    paid_at: datetime
    reference: str | None
    notes: str | None


class InvoiceDetailResponse(BillingScheduleResponse):
    """Screen 13."""

    customer_name: str
    payments: list[PaymentResponse]
    can_act: bool


class RecordPaymentRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    method: str = Field(pattern="^(bank_transfer|card|cash|cheque|other)$")
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


# --- Customer portal (PRD B8, FRONTEND.md Screen 11) -----------------------
#
# Separate models, not a reuse of the internal ones with fields blanked out.
# FRONTEND.md Screen 11: "must never expose any internal-only control, data
# field, or navigation item — no discount limits, no other customers' data, no
# internal audit trail, no role/permission info." A separate model makes that
# a property of the type rather than of whoever remembers to blank a field:
# there is no `allowed_discount_percent`, `line_excess_points`, `margin_*`,
# `owner_name` or `blended_risk_score` here to leak in the first place.


class PortalLineResponse(BaseModel):
    line_number: int
    product_name: str
    quantity: Decimal
    unit_list_price: Decimal
    discount_percent: Decimal
    line_total: Decimal


class PortalCommentResponse(BaseModel):
    """One row of Screen 11's comment table, sourced from the audit trail."""

    created_at: datetime
    author_name: str | None
    message: str


class PortalQuotationSummaryResponse(BaseModel):
    """Row shape for the portal's "My Quotations" list."""

    id: int
    quote_number: str
    status: str
    total_amount: Decimal
    currency: str
    updated_at: datetime
    valid_until: date | None


class PortalQuotationDetailResponse(PortalQuotationSummaryResponse):
    customer_name: str
    subtotal_amount: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    lines: list[PortalLineResponse]
    comments: list[PortalCommentResponse]
    # Whether the two PRD B8 buttons should be live. The backend re-checks on
    # every write regardless of what this says.
    can_negotiate: bool


class PortalNegotiateRequest(BaseModel):
    """`Submit Request` — a comment, optionally with a counter discount.

    `requested_delivery_date` is deliberately part of the free-text message
    rather than a column; see Locked Business Rules #8c.
    """

    comment: str = Field(min_length=1, max_length=2000)
    counter_discount_percent: Decimal | None = Field(default=None, ge=0, le=100)


class PortalConfirmResponse(BaseModel):
    """PRD B8's two outcomes, told to the customer plainly."""

    quotation: PortalQuotationDetailResponse
    re_entered_approval: bool
    message: str


# --- Upsell / cross-sell (PRD A6, B5) ---------------------------------------


class UpsellSuggestionResponse(BaseModel):
    product_id: int
    product_name: str
    product_sku: str
    list_price: Decimal
    is_promoted: bool
    margin_delta_percent: Decimal


# --- Admin config: discount tiers & approval chains (PRD A3, Screen 18) ----


class RoleOptionResponse(BaseModel):
    """Just enough to populate a role picker — never the full RBAC row."""

    id: int
    code: str
    name: str


class DiscountTierResponse(BaseModel):
    id: int
    customer_tier: str
    category_id: int
    category_name: str
    max_discount_percent: Decimal
    is_active: bool


class UpdateDiscountTierRequest(BaseModel):
    max_discount_percent: Decimal = Field(ge=0, le=100)


class CreateDiscountTierRequest(BaseModel):
    customer_tier: str
    category_id: int
    max_discount_percent: Decimal = Field(ge=0, le=100)


class ApprovalChainResponse(BaseModel):
    id: int
    min_score: Decimal
    max_score: Decimal | None
    required_role_id: int
    required_role_name: str
    required_role_code: str
    step_order: int
    label: str | None
    is_active: bool


class CreateApprovalChainRequest(BaseModel):
    min_score: Decimal = Field(ge=0)
    max_score: Decimal | None = Field(default=None, gt=0)
    required_role_id: int
    step_order: int = Field(ge=1)
    label: str | None = Field(default=None, max_length=120)


class UpdateApprovalChainRequest(BaseModel):
    min_score: Decimal = Field(ge=0)
    max_score: Decimal | None = Field(default=None, gt=0)
    step_order: int = Field(ge=1)
    label: str | None = Field(default=None, max_length=120)
    is_active: bool = True


# --- Admin config: product catalogue (PRD A2, Screens 16-17) ---------------


class ProductCategoryResponse(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    is_active: bool


class CreateProductCategoryRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=255)


class AdminProductResponse(BaseModel):
    id: int
    sku: str
    name: str
    description: str | None
    category_id: int
    category_name: str
    unit: str
    list_price: Decimal
    cost_price: Decimal
    tax_rate: Decimal
    item_type: str
    is_promoted: bool
    is_active: bool


class CreateProductRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    category_id: int
    unit: str = Field(default="unit", max_length=20)
    list_price: Decimal = Field(ge=0)
    cost_price: Decimal = Field(ge=0)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    item_type: str = Field(pattern="^(one_time|subscription)$")
    is_promoted: bool = False


class UpdateProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    category_id: int
    unit: str = Field(default="unit", max_length=20)
    list_price: Decimal = Field(ge=0)
    cost_price: Decimal = Field(ge=0)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    is_promoted: bool = False
    is_active: bool = True


# --- Deal health (PRD B9) ---------------------------------------------------


class DealHealthAlertResponse(BaseModel):
    quotation_id: int
    quote_number: str
    customer_name: str
    owner_name: str
    is_stalled: bool
    days_inactive: int
    has_discount_anomaly: bool
    discount_vs_rep_average: Decimal
    has_delivery_slippage: bool
    days_slipped: int
    snapshot_at: datetime


class DealHealthDashboardResponse(BaseModel):
    stalled_count: int
    anomaly_count: int
    slippage_count: int
    alerts: list[DealHealthAlertResponse]


# --- Reporting (PRD A7) -----------------------------------------------------


class ReportFiltersRequest(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    owner_id: int | None = None
    status: str | None = None
    category_id: int | None = None


class ReportRow(BaseModel):
    quote_number: str
    customer_name: str
    owner_name: str
    status: str
    total_amount: Decimal
    discount_amount: Decimal
    blended_risk_score: Decimal
    created_at: datetime


class ReportResponse(BaseModel):
    rows: list[ReportRow]
    total_amount: Decimal
    total_discount: Decimal
    count: int


# --- Admin: customers (PRD A4 continuation) ---------------------------------


class CreateCustomerRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    tier: str
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    billing_address: str | None = Field(default=None, max_length=500)


class AdminCustomerResponse(ORMModel):
    id: int
    code: str
    name: str
    tier: str
    currency: str
    email: str | None
    phone: str | None
    is_active: bool


# --- Admin: users & invitations (PRD A1, A4) --------------------------------
#
# There is no `PATCH /admin/users/{id}/role` — an Admin provisioning the
# right role directly through an invitation (below) is the realistic ERP
# pattern this replaces, not a gap it still needs filling. See
# `services/invitation.py`'s module docstring.


class AdminUserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role_id: int
    role_code: str
    role_name: str
    customer_id: int | None
    customer_name: str | None
    is_active: bool
    # False for an invitation that has not yet been accepted — the account
    # exists but has never had a password set.
    has_password: bool


class InviteUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=160)
    role_id: int
    # Required by the service when, and only when, `role_id` resolves to the
    # customer role — validated there, not here, since that depends on a
    # database lookup this schema cannot perform.
    customer_id: int | None = None


class InviteUserResponse(BaseModel):
    user: AdminUserResponse
    # No email infrastructure exists in this project (PROJECT_CONTEXT.md) —
    # the activation link is handed straight back to the Admin to copy and
    # send however they already reach this person, the same "copy this link"
    # shape as a Google Doc share link or a Slack invite.
    invite_url: str
    expires_at: datetime


class InvitationPreviewResponse(BaseModel):
    email: str
    full_name: str
    role_name: str
    customer_name: str | None
    expires_at: datetime
    already_accepted: bool
    is_expired: bool


class AcceptInvitationRequest(BaseModel):
    password: str = Field(min_length=8, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


# --- Customer portal: profile & messages (Screen 11's "Profile"/"Messages") -


class PortalProfileResponse(BaseModel):
    """The portal's own read-only account view. Deliberately thinner than
    `CurrentUserResponse` — no permissions list, no role code, nothing an
    internal screen would need and a customer has no reason to see."""

    full_name: str
    email: str
    customer_name: str
    customer_code: str
    customer_tier: str


class PortalMessageResponse(PortalCommentResponse):
    """One row of the portal's "Messages" screen — `PortalCommentResponse`
    plus which quotation it belongs to, since this view spans every
    quotation the customer has, not just one."""

    quotation_id: int
    quote_number: str
