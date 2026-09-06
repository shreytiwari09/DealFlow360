/**
 * API client.
 *
 * Two things this deliberately does NOT do:
 *  - It never decides what a user may do. It reports what the server said.
 *    A 403 is rendered, not predicted (SECURITY_SPEC.md: frontend controls
 *    are UX only).
 *  - It never surfaces a raw error body. Server errors are already generic
 *    by design; this turns them into something a person can act on.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const V1 = `${API_BASE_URL}/api/v1`;

/*
 * The refresh token lives ONLY in an HttpOnly cookie the browser manages
 * entirely on its own (SECURITY_SPEC.md Section 7) — this file never reads,
 * stores, or even sees its value. That single fact is what retired the
 * sessionStorage/localStorage machinery that used to live here: a cookie is
 * already scoped correctly per-browser and sent automatically by the browser
 * on every request to its own path, which is exactly the property the old
 * bootstrap-fallback dance existed to approximate by hand across tabs (a new
 * tab just... has the cookie, the same way every tab always has it — there
 * is no "which tab's copy is the real one" question left to answer).
 *
 * `credentials: "include"` on every request is what makes the browser
 * attach that cookie at all for the cross-origin call to :8000 from :5173 —
 * paired with the backend's `allow_credentials=True` CORS setting. The
 * cookie's own `Path=/api/v1/auth` means the browser still only actually
 * SENDS it to the auth routes that need it; harmless to request it
 * everywhere else.
 *
 * The access token remains in-memory only, exactly as before: it is a
 * short-lived bearer credential attached manually via `Authorization`, which
 * carries none of a cookie's CSRF exposure and none of localStorage's
 * XSS-exfiltration risk either way.
 */
let accessToken: string | null = null;

function getCsrfToken(): string | null {
  const match = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

/** Called by `auth.tsx` after a successful sign-in/sign-up/invite-accept —
 * those endpoints already set the refresh+CSRF cookies themselves via
 * `Set-Cookie`; this is only the in-memory half. */
export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** `auth.tsx`'s `signOut()`. Best-effort and CSRF-guarded like the backend
 * route itself — a missing/expired cookie is not an error to the caller,
 * since the point is just "make sure this session is over" either way. */
export async function logout(): Promise<void> {
  try {
    await fetch(`${V1}/auth/logout`, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": getCsrfToken() ?? "" },
    });
  } catch {
    /* the local sign-out below must proceed regardless of network state */
  }
  accessToken = null;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function friendly(status: number, detail: unknown): string {
  if (typeof detail === "string" && detail.length > 0 && detail.length < 300) return detail;
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "You do not have access to this.";
  if (status === 404) return "Not found.";
  if (status >= 500) return "Something went wrong on the server. Please try again.";
  return "Request failed.";
}

async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  return fetch(`${V1}${path}`, { ...init, headers, credentials: "include" });
}

async function refreshAccessToken(): Promise<boolean> {
  // No body, no stored token to check for — the refresh_token cookie IS the
  // credential, and the browser attaches it on its own. A brand-new tab with
  // no session simply gets a 401 here, same as any other unauthenticated
  // call; there is no separate "do we even have a token to try" question to
  // ask first anymore.
  const response = await fetch(`${V1}/auth/refresh`, {
    method: "POST",
    credentials: "include",
    headers: { "X-CSRF-Token": getCsrfToken() ?? "" },
  });
  if (!response.ok) {
    accessToken = null;
    return false;
  }
  const data = (await response.json()) as TokenResponse;
  accessToken = data.access_token;
  return true;
}

/**
 * Access tokens live 15 minutes, so a demo will cross that boundary. On a
 * 401 we rotate once and replay the request; if the rotation also fails the
 * session is genuinely over and the caller sees a 401.
 *
 * The retry fires on ANY 401, not only when `accessToken` is already set:
 * on a fresh page load `accessToken` starts as null even when the refresh
 * cookie is perfectly valid, so the very call meant to resume the session
 * must not skip the refresh path just because nothing is in memory yet.
 */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response = await raw(path, init);

  if (response.status === 401) {
    if (await refreshAccessToken()) response = await raw(path, init);
  }

  if (response.status === 204) return undefined as T;

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, friendly(response.status, body?.detail));
  }
  return body as T;
}

/**
 * Downloads a binary export (PDF/XLSX) and hands the browser a real file
 * save via a temporary object URL — not a JSON response, so it bypasses
 * `request()` entirely. Shares the same 401-retry logic since an export can
 * just as easily race an access-token expiry as any other call.
 */
async function download(path: string, filename: string): Promise<void> {
  let response = await raw(path);
  if (response.status === 401) {
    if (await refreshAccessToken()) response = await raw(path);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(response.status, friendly(response.status, body?.detail));
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, payload?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(payload ?? {}) }),
  put: <T>(path: string, payload: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(payload) }),
  patch: <T>(path: string, payload: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(payload) }),
  download,
};

// --- Types mirroring the backend DTOs ------------------------------------

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface CurrentUser {
  id: number;
  email: string;
  full_name: string;
  role: string;
  permissions: string[];
  customer_id: number | null;
  customer_name: string | null;
}

export interface Product {
  id: number;
  sku: string;
  name: string;
  category_id: number;
  category_code: string | null;
  list_price: string;
  tax_rate: string;
  item_type: string;
  is_promoted: boolean;
}

export interface Customer {
  id: number;
  code: string;
  name: string;
  tier: string;
  currency: string;
}

export interface QuotationLine {
  id: number;
  line_number: number;
  product_id: number;
  product_name: string;
  product_sku: string;
  quantity: string;
  unit_list_price: string;
  discount_percent: string;
  allowed_discount_percent: string;
  line_excess_points: string;
  is_over_limit: boolean;
  line_type: string;
  line_subtotal: string;
  line_discount_amount: string;
  line_total: string;
  added_from_upsell: boolean;
  subscription_plan_id: number | null;
  subscription_plan_name: string | null;
}

export interface QuotationSummary {
  id: number;
  quote_number: string;
  customer_id: number;
  customer_name: string;
  owner_id: number;
  owner_name: string;
  status: string;
  total_amount: string;
  currency: string;
  blended_risk_score: string;
  updated_at: string;
}

export interface Quotation extends QuotationSummary {
  customer_tier: string;
  subtotal_amount: string;
  discount_amount: string;
  tax_amount: string;
  margin_amount: string;
  margin_percent: string;
  max_line_excess: string;
  requires_approval: boolean;
  requires_finance_approval: boolean;
  valid_until: string | null;
  version: number;
  lines: QuotationLine[];
  can_edit: boolean;
}

export interface AssignableUser {
  id: number;
  full_name: string;
  role_name: string;
}

export interface RiskLine {
  line_number: number;
  product_name: string;
  discount_percent: string;
  allowed_discount_percent: string;
  excess_points: string;
}

export interface RiskPreview {
  blended_risk_score: string;
  max_line_excess: string;
  requires_approval: boolean;
  finance_gate_tripped: boolean;
  risk_band: string;
  lines: RiskLine[];
  required_steps: string[];
}

export interface ApprovalStep {
  step_order: number;
  required_role: string;
  status: string;
  actor_name: string | null;
  decided_at: string | null;
  reason: string | null;
  forced_by_line_gate: boolean;
}

export interface AuditEntry {
  user_name: string | null;
  action: string;
  created_at: string;
  reason: string | null;
}

export interface ApprovalSummary {
  id: number;
  quotation_id: number;
  quote_number: string;
  customer_name: string;
  blended_risk_score: string;
  risk_band: string;
  status: string;
  current_stage: string | null;
  assigned_to: string | null;
  requested_at: string;
}

export interface ApprovalDetail extends ApprovalSummary {
  customer_tier: string;
  max_line_excess: string;
  triggered_by_line_gate: boolean;
  total_amount: string;
  currency: string;
  steps: ApprovalStep[];
  line_breakdown: RiskLine[];
  audit_trail: AuditEntry[];
  can_act: boolean;
}

export interface StockLevel {
  warehouse_id: number;
  warehouse_name: string;
  product_id: number;
  product_name: string;
  quantity_on_hand: string;
  quantity_reserved: string;
  available: string;
}

export interface OrderAwaitingFulfillment {
  quotation_id: number;
  quote_number: string;
  customer_name: string;
  fulfillment_status: string | null;
  warehouse_names: string[];
}

export interface FulfillmentOverview {
  stock: StockLevel[];
  orders: OrderAwaitingFulfillment[];
}

export interface FulfillmentSplit {
  quotation_line_id: number;
  product_name: string;
  warehouse_id: number;
  warehouse_name: string;
  quantity: string;
  is_manual_override: boolean;
}

export interface Backorder {
  id: number;
  quotation_line_id: number;
  product_name: string;
  quantity_outstanding: string;
  status: string;
  can_consolidate: boolean;
}

export interface FulfillmentDetail {
  id: number;
  quotation_id: number;
  quote_number: string;
  customer_name: string;
  status: string;
  shipment_count: number;
  estimated_shipping_cost: string;
  is_manual_override: boolean;
  splits: FulfillmentSplit[];
  backorders: Backorder[];
  can_act: boolean;
}

export interface DashboardSummary {
  pending_approvals: number;
  open_quotations: number;
  at_risk_deals: number;
  recent_activity: AuditEntry[];
}

// --- Billing (PRD B7, FRONTEND.md Screens 9-10, 12-13) --------------------

export interface SubscriptionPlan {
  id: number;
  code: string;
  name: string;
  billing_interval: string;
  interval_count: number;
  unit_amount: string;
}

export interface ProrationRecord {
  id: number;
  change_date: string;
  cycle_start: string;
  cycle_end: string;
  cycle_days: number;
  remaining_days: number;
  old_quantity: string;
  new_quantity: string;
  old_amount: string;
  new_amount: string;
  credit_amount: string;
  charge_amount: string;
  proration_amount: string;
}

export interface BillingScheduleRow {
  id: number;
  quotation_id: number;
  quote_number: string;
  subscription_id: number | null;
  schedule_type: string;
  status: string;
  due_date: string;
  amount: string;
  cycle_start: string | null;
  cycle_end: string | null;
  invoice_number: string | null;
  invoiced_at: string | null;
  is_credit_note: boolean;
}

export interface SubscriptionSummary {
  id: number;
  quotation_id: number;
  quote_number: string;
  customer_name: string;
  product_name: string;
  plan_name: string;
  status: string;
  quantity: string;
  unit_amount: string;
  current_cycle_start: string;
  current_cycle_end: string;
}

export interface SubscriptionDetail extends SubscriptionSummary {
  plan_id: number;
  billing_schedules: BillingScheduleRow[];
  proration_history: ProrationRecord[];
  can_act: boolean;
}

export interface Payment {
  id: number;
  amount: string;
  method: string;
  paid_at: string;
  reference: string | null;
  notes: string | null;
}

export interface InvoiceDetail extends BillingScheduleRow {
  customer_name: string;
  payments: Payment[];
  can_act: boolean;
}

// --- Customer portal (PRD B8, FRONTEND.md Screen 11) ----------------------
//
// Deliberately thin. These mirror the backend's portal-only schemas, which
// carry no discount ceiling, no risk score, no margin and no owner — there is
// nothing internal here to accidentally render.

export interface PortalLine {
  line_number: number;
  product_name: string;
  quantity: string;
  unit_list_price: string;
  discount_percent: string;
  line_total: string;
}

export interface PortalComment {
  created_at: string;
  author_name: string | null;
  message: string;
}

export interface PortalQuotationSummary {
  id: number;
  quote_number: string;
  status: string;
  total_amount: string;
  currency: string;
  updated_at: string;
  valid_until: string | null;
}

export interface PortalQuotationDetail extends PortalQuotationSummary {
  customer_name: string;
  subtotal_amount: string;
  discount_amount: string;
  tax_amount: string;
  lines: PortalLine[];
  comments: PortalComment[];
  can_negotiate: boolean;
}

export interface PortalConfirmResult {
  quotation: PortalQuotationDetail;
  re_entered_approval: boolean;
  message: string;
}

// --- Upsell / cross-sell (PRD A6, B5) --------------------------------------

export interface UpsellSuggestion {
  product_id: number;
  product_name: string;
  product_sku: string;
  list_price: string;
  is_promoted: boolean;
  margin_delta_percent: string;
}

// --- Admin config: discount tiers & approval chains (Screen 18) -----------

export interface RoleOption {
  id: number;
  code: string;
  name: string;
}

export interface DiscountTierRow {
  id: number;
  customer_tier: string;
  category_id: number;
  category_name: string;
  max_discount_percent: string;
  is_active: boolean;
}

export interface ApprovalChainRow {
  id: number;
  min_score: string;
  max_score: string | null;
  required_role_id: number;
  required_role_name: string;
  required_role_code: string;
  step_order: number;
  label: string | null;
  is_active: boolean;
}

// --- Admin config: product catalogue (Screens 16-17) -----------------------

export interface ProductCategoryRow {
  id: number;
  code: string;
  name: string;
  description: string | null;
  is_active: boolean;
}

export interface AdminProduct {
  id: number;
  sku: string;
  name: string;
  description: string | null;
  category_id: number;
  category_name: string;
  unit: string;
  list_price: string;
  cost_price: string;
  tax_rate: string;
  item_type: string;
  is_promoted: boolean;
  is_active: boolean;
}

// --- Deal health (Screen 14, PRD B9) ---------------------------------------

export interface DealHealthAlert {
  quotation_id: number;
  quote_number: string;
  customer_name: string;
  owner_name: string;
  is_stalled: boolean;
  days_inactive: number;
  has_discount_anomaly: boolean;
  discount_vs_rep_average: string;
  has_delivery_slippage: boolean;
  days_slipped: number;
  snapshot_at: string;
}

export interface DealHealthDashboard {
  stalled_count: number;
  anomaly_count: number;
  slippage_count: number;
  alerts: DealHealthAlert[];
}

// --- Reporting (Screen 15, PRD A7) -----------------------------------------

export interface ReportRow {
  quote_number: string;
  customer_name: string;
  owner_name: string;
  status: string;
  total_amount: string;
  discount_amount: string;
  blended_risk_score: string;
  created_at: string;
}

export interface ReportResult {
  rows: ReportRow[];
  total_amount: string;
  total_discount: string;
  count: number;
}

export interface ReportFilters {
  date_from?: string;
  date_to?: string;
  owner_id?: number;
  status?: string;
  category_id?: number;
}

// --- Admin: customers & users/invitations (PRD A1, A4) ---------------------

export interface AdminCustomer {
  id: number;
  code: string;
  name: string;
  tier: string;
  currency: string;
  email: string | null;
  phone: string | null;
  is_active: boolean;
}

export interface AdminUser {
  id: number;
  email: string;
  full_name: string;
  role_id: number;
  role_code: string;
  role_name: string;
  customer_id: number | null;
  customer_name: string | null;
  is_active: boolean;
  has_password: boolean;
}

export interface InviteUserResult {
  user: AdminUser;
  invite_url: string;
  expires_at: string;
  email_sent: boolean;
}

export interface InvitationPreview {
  email: string;
  full_name: string;
  role_name: string;
  customer_name: string | null;
  expires_at: string;
  already_accepted: boolean;
  is_expired: boolean;
}

// --- Customer portal: Profile & Messages (Screen 11) ------------------------

export interface PortalProfile {
  full_name: string;
  email: string;
  customer_name: string;
  customer_code: string;
  customer_tier: string;
}

export interface PortalMessage {
  created_at: string;
  author_name: string | null;
  message: string;
  quotation_id: number;
  quote_number: string;
}
