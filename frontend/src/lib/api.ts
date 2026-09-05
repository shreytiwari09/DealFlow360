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
 * sessionStorage, not localStorage. localStorage is shared across every tab
 * of the same browser, so two tabs signed in as different users (exactly the
 * "rep in one window, manager in another" setup this app's own demo script
 * asks for) fight over one stored session: whichever tab last touched
 * storage silently evicts the other's login. sessionStorage is per-tab, so
 * each tab keeps its own identity independent of what any other tab does,
 * while still surviving a reload of that same tab.
 *
 * SECURITY_SPEC.md Section 7 prefers HttpOnly cookies over either Storage
 * mechanism, and that remains the right end state. This is a deliberate,
 * documented gap for the demo: cookie auth needs CSRF protection and a
 * same-site story that the split localhost:5173 / localhost:8000 origins do
 * not currently give us. Tracked in PROJECT_CONTEXT.md Known Issues.
 */
const REFRESH_KEY = "dealflow.refresh";

let accessToken: string | null = null;

export function getRefreshToken(): string | null {
  try {
    return sessionStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function setTokens(access: string | null, refresh: string | null): void {
  accessToken = access;
  try {
    if (refresh) sessionStorage.setItem(REFRESH_KEY, refresh);
    else sessionStorage.removeItem(REFRESH_KEY);
  } catch {
    /* private browsing — the session simply will not survive a reload */
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
  setTokens(data.access_token, data.refresh_token);
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

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, payload?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(payload ?? {}) }),
  put: <T>(path: string, payload: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(payload) }),
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
