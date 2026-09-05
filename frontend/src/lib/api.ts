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
 * Tokens live in memory, with the refresh token mirrored to sessionStorage so
 * a page reload does not log the user out.
 *
 * sessionStorage, not localStorage, as the per-tab SOURCE OF TRUTH. localStorage
 * is shared across every tab of the same browser, so two tabs signed in as
 * different users (exactly the "rep in one window, manager in another" setup
 * this app's own demo script asks for) would otherwise fight over one stored
 * session: whichever tab last touched storage silently evicts the other's
 * login. sessionStorage is per-tab, so each tab keeps its own identity
 * independent of what any other tab does, while still surviving a reload of
 * that same tab.
 *
 * BUT sessionStorage alone breaks a real workflow: a brand-new tab (a deep
 * link opened from Slack/email, a bookmark, ctrl-click, or pasting a URL)
 * starts with EMPTY sessionStorage no matter how logged-in the user is
 * elsewhere in the same browser — that tab bounces straight to /login even
 * though the user never signed out. localStorage is kept alongside
 * sessionStorage as a "last known session" bootstrap value purely for this
 * case: a brand-new tab with nothing of its own falls back to it once, then
 * behaves exactly like any other tab from that point on (its own
 * sessionStorage copy, immune to what other tabs do afterward). Explicit
 * sign-out clears the fallback too, but only if it still points at the
 * session being signed out of — so one tab signing out can never silently
 * kill a *different* identity that another, still-open tab is using.
 *
 * The bootstrap must only ever happen ONCE per tab, the very first time that
 * tab asks for a token at all — never again after that, even once this tab's
 * own copy is later cleared. Without that rule, explicitly signing out in
 * this tab would immediately re-bootstrap it right back from the shared
 * fallback if some OTHER identity happened to be sitting there (a manager
 * still active in a different tab, say) — turning "sign out" into "silently
 * sign in as someone else," which is worse than the deep-link bug this whole
 * mechanism exists to fix. `BOOTSTRAPPED_KEY` is the marker for "this tab has
 * an opinion of its own now, stop asking the shared pool."
 *
 * SECURITY_SPEC.md Section 7 prefers HttpOnly cookies over either Storage
 * mechanism, and that remains the right end state. This is a deliberate,
 * documented gap for the demo: cookie auth needs CSRF protection and a
 * same-site story that the split localhost:5173 / localhost:8000 origins do
 * not currently give us. Tracked in PROJECT_CONTEXT.md Known Issues.
 */
const REFRESH_KEY = "dealflow.refresh";
const BOOTSTRAPPED_KEY = "dealflow.bootstrapped";

let accessToken: string | null = null;

export function getRefreshToken(): string | null {
  try {
    const ownToken = sessionStorage.getItem(REFRESH_KEY);
    if (ownToken) return ownToken;
    // This tab has already had its own identity established (and since
    // cleared, e.g. by an explicit sign-out) — never re-adopt whatever the
    // shared pool currently holds, even if it looks like a valid session.
    if (sessionStorage.getItem(BOOTSTRAPPED_KEY)) return null;
  } catch {
    /* private browsing or storage disabled — fall through to the shared copy */
  }

  try {
    const lastKnown = localStorage.getItem(REFRESH_KEY);
    if (lastKnown) {
      // Bootstrap this tab from the shared fallback, once. From here on this
      // tab has its own sessionStorage copy and is independent of whatever
      // any other tab does next.
      sessionStorage.setItem(REFRESH_KEY, lastKnown);
      sessionStorage.setItem(BOOTSTRAPPED_KEY, "1");
      return lastKnown;
    }
  } catch {
    /* private browsing or storage disabled */
  }
  return null;
}

/**
 * `background: true` is the one case that must NOT touch the shared
 * localStorage fallback: a routine access-token rotation (every ~15 minutes,
 * silently, in every open tab) is not a new identity becoming active — it is
 * the SAME identity's token being renewed. Writing it to localStorage
 * unconditionally would reintroduce exactly the bug sessionStorage was
 * adopted to fix in the first place, just one layer down: tab A's ordinary
 * background refresh would silently overwrite tab B's still-active identity
 * in the shared fallback, so a brand-new tab C opened right after would
 * bootstrap into A's session instead of B's, purely because of refresh
 * timing neither tab's user had any control over. An explicit sign-in
 * (`signIn`/`signUp` in `auth.tsx`) IS a new identity becoming active and
 * updates the fallback normally; only `refreshAccessToken()`'s own success
 * path below passes `background: true`.
 */
export function setTokens(
  access: string | null,
  refresh: string | null,
  { background = false }: { background?: boolean } = {},
): void {
  accessToken = access;

  let previousOwnToken: string | null = null;
  try {
    previousOwnToken = sessionStorage.getItem(REFRESH_KEY);
  } catch {
    /* ignore */
  }

  try {
    if (refresh) sessionStorage.setItem(REFRESH_KEY, refresh);
    else sessionStorage.removeItem(REFRESH_KEY);
    // From this point on this tab has its own established state (signed in
    // or explicitly signed out) and must never again silently bootstrap from
    // the shared fallback — see `getRefreshToken()`'s docstring.
    sessionStorage.setItem(BOOTSTRAPPED_KEY, "1");
  } catch {
    /* private browsing — the session simply will not survive a reload */
  }

  if (background) return;

  try {
    if (refresh) {
      localStorage.setItem(REFRESH_KEY, refresh);
    } else if (previousOwnToken && localStorage.getItem(REFRESH_KEY) === previousOwnToken) {
      localStorage.removeItem(REFRESH_KEY);
    }
  } catch {
    /* private browsing or storage disabled */
  }
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
  return fetch(`${V1}${path}`, { ...init, headers });
}

async function refreshAccessToken(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) return false;
  const response = await fetch(`${V1}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!response.ok) {
    setTokens(null, null);
    return false;
  }
  const data = (await response.json()) as TokenResponse;
  // background: true - see setTokens's own docstring. This is a routine
  // rotation of the SAME identity's token, not a new sign-in, and must not
  // overwrite the shared "last active session" fallback other tabs bootstrap
  // brand-new tabs from.
  setTokens(data.access_token, data.refresh_token, { background: true });
  return true;
}

/**
 * Access tokens live 15 minutes, so a demo will cross that boundary. On a
 * 401 we rotate once and replay the request; if the rotation also fails the
 * session is genuinely over and the caller sees a 401.
 *
 * The retry fires on ANY 401, not only when `accessToken` is already set.
 * Gating it on an in-memory access token was the actual bug: on a fresh page
 * load `accessToken` starts as null even when a perfectly valid refresh
 * token is sitting in storage, so the very call meant to resume the session
 * skipped the refresh path entirely, fell through to the generic 401, and
 * `resume()` in auth.tsx reacted by wiping the stored token — turning "resume
 * my session" into "log everyone out on every reload." `refreshAccessToken()`
 * already returns false immediately when there is no stored refresh token,
 * so dropping the guard does not risk looping on a genuinely unauthenticated
 * request.
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
  download,
};

// --- Types mirroring the backend DTOs ------------------------------------

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
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
