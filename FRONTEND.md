# DealFlow360 — Frontend Specification

## Purpose of This Document

This is the implementation contract for the frontend, handed to Claude Code alongside `PLAN.md`, `PROJECT_CONTEXT.md`, `SECURITY_SPEC.md`, and `IMPLEMENTATION_LOG.md`. Per `PLAN.md` Section 13 (Phase 8 — "wait for design input before building UI"), this document **is** that design input: the Excalidraw mockup (`DealFlow360 — End to End Product Flow`, 18 screens) plus the accompanying visual style brief, translated into implementation detail.

**Precedence rules (read this before building anything):**

1. **Screen content, fields, tables, buttons, and navigation flow** — the Excalidraw wireframe is authoritative. This document describes it screen-by-screen; do not add fields, screens, or actions that aren't in the wireframe or explicitly required to make a wireframed flow work.
2. **Visual chrome (shell layout, sidebar vs. tab bar, colors, spacing, typography, shadows, radii)** — the separately-provided Style Spec is authoritative. The wireframe uses a horizontal top tab bar per screen; the Style Spec explicitly calls for a persistent sidebar shell. **Resolution:** implement the wireframe's navigation *items* and *flow* inside the Style Spec's sidebar shell (see Section 2). This is a deliberate reconciliation, not an invented feature — the wireframe is low-fidelity chrome around real content; the Style Spec is the explicit visual system.
3. **Feature completeness and roles** — `DealFlow360_PRD_Merged.md` (the PRD) and `SECURITY_SPEC.md` / `PROJECT_CONTEXT.md`'s five-role model.
4. **API contracts / data shape** — backend, once defined (Phase 4). This document specifies what data each screen displays and what actions it triggers, not response schemas.

Anything not resolvable from the above is explicitly marked **`TBD`** below. Do not silently invent behavior for a `TBD` item — flag it back to the user/team per `PLAN.md` Section 0.6.

---

## 1. Roles Recap (for access-control notes throughout)

| Role | Summary |
|---|---|
| **Sales Rep** | Builds/edits own quotations, tracks own approval/fulfillment status |
| **Sales Manager / Approver** | Approves/rejects flagged quotations, configures discount tiers & approval chains, monitors deal health |
| **Finance / Operations User** | Second-level approval on high-risk discounts, fulfillment/backorder decisions, billing reconciliation |
| **Customer (Portal User)** | Own quotation only, via a separate restricted portal shell — never the internal app shell |
| **Admin** | Full system administration, product/price/discount/warehouse/subscription setup, platform-wide reporting |

Every screen section below states which roles can view it and which can act on it. **Frontend role gating is UX only** — hide/disable controls the user can't use, but never treat this as the security boundary (`SECURITY_SPEC.md` Section 1: backend enforcement is authoritative).

---

## 2. Application Shell

Two distinct shells exist. Do not let the customer ever see the internal shell (PRD: "must be a real, separate, restricted view, not just another internal screen with a different label").

### 2.1 Internal Shell (Sales Rep, Sales Manager, Finance, Admin)

Persistent layout per the Style Spec Section 3:

```
┌──────────────────────────────────────────────────────────────────────┐
│ Header: breadcrumb / page context, global search, notif., user menu  │
├───────────────┬──────────────────────────────────────────────────────┤
│ Sidebar       │  Page Header (title + primary action)                │
│               │  Toolbar (search / filters / view switch)            │
│  Dashboard    │  ─────────────────────────────────────────────────   │
│  Quotations   │  Main content (table / cards / detail)               │
│  Approvals    │                                                      │
│  Fulfillment  │                                                      │
│  Subscriptions│                                                      │
│  Invoices     │                                                      │
│  Deal Health  │                                                      │
│  Reports      │                                                      │
│  Product*     │                                                      │
└───────────────┴──────────────────────────────────────────────────────┘
```

Sidebar items map 1:1 to the wireframe's top tab bar (`Dashboard | Quotations | Approvals | Fulfillment | Subscriptions | Invoices | Deal Health | Reports | Product`), reordered into a vertical sidebar per the Style Spec. The active item is highlighted per Style Spec Section 4 (subtle, not saturated).

`*` **Product** is the entry point to Product Catalog (Screen 16/17) and, alongside it, Discount Tiers & Approval Chains (Screen 18). Both are **Admin**-only in the wireframe; **Sales Manager** additionally needs write access to discount tiers/approval chains per PRD (A3: "Sales Manager... configures discount tiers and approval chains"). Recommended: Sales Manager sees a "Discount Tiers" sidebar item (Screen 18 only, no Product Catalog); Admin sees the full "Product" section (Screens 16, 17, 18). Sales Rep and Finance do not see this sidebar section at all.

Header, per Style Spec Section 5, holds global search, notifications, and user/profile menu. The wireframe does not detail these controls — treat their exact placement/behavior as `TBD`, but they must not compete with sidebar navigation.

**Gap vs. PRD (B1):** the PRD's "Top Menu" mentions `Reload Data`, `Go to Back-end`, `Close Workspace` actions that are not drawn anywhere in the wireframe. `TBD` — flag to the team before adding; do not invent a design for these. If needed for demo completeness, the safest placement is small icon buttons in the header, but confirm first.

### 2.2 Customer Portal Shell (Customer / Portal User)

A **completely separate** shell, matching the wireframe's own separate top bar on Screen 11: `My Quotations | Messages | Profile`. No sidebar, no internal navigation items, no access to any internal screen. Keep it visually simpler/lighter than the internal shell (still following the Style Spec's professional tone, just with less density — a customer sees one quotation at a time, not an ops console).

**Gap vs. wireframe:** only the negotiation detail screen (Screen 11) is drawn. `My Quotations` (a list, presumably needed if a customer has more than one quotation), `Messages`, and `Profile` are nav labels only — no screen content is specified for them. Do not invent full screens. Minimum viable treatment:
- `My Quotations`: a simple list of the customer's own quotations (customer-scoped, reuses the row shape of Screen 3 but customer-only columns: Quotation #, Status, Amount, Last Updated) — clicking a row opens Screen 11 for that quotation. This is the minimum needed to make the nav item functional at all, since a customer could plausibly have more than one quotation; if the demo only needs one active quotation per customer, this list can be a stub/redirect straight to Screen 11 — confirm with the team (`TBD`).
- `Messages` and `Profile`: `TBD`, not specified. Do not build full functionality; a placeholder ("Coming soon") is acceptable if the nav item must exist for visual completeness, but do not treat this as a real deliverable.

---

## 3. Design Tokens (proposed — not specified verbatim in source docs)

The Style Spec gives philosophy, not exact values. These are concrete proposed defaults consistent with that philosophy; they are **not** in the wireframe or PRD, so treat them as a starting point the team can tune, not a locked spec.

**Color**
- Background (app shell): `#F5F6F8` (near-white neutral)
- Surface (cards, tables, panels): `#FFFFFF`
- Primary text: `#1A1D23`
- Secondary/muted text: `#6B7280`
- Border: `#E3E5E8`
- Primary/accent (nav selection, primary buttons, links): `#2454E0` (a restrained enterprise blue — echoes the blue header bars used throughout the wireframe)
- Success (approved / active / paid / confirmed): `#1E8E5A`
- Warning (pending / negotiation / partially fulfilled / stalled): `#B5820B`
- Error / destructive (rejected / over limit / backordered / overdue): `#C0342A`
- Neutral / draft / inactive: `#6B7280` on `#EEF0F3` background

**Typography:** a modern sans-serif (e.g., Inter or system-ui stack). Page title: 20–24px semibold. Section title: 15–16px semibold. Primary data (table cell primary line, amounts): 14px medium. Secondary/metadata: 12–13px, muted color.

**Spacing scale:** 4 / 8 / 12 / 16 / 24 / 32px, per Style Spec Section 16.

**Radius:** inputs/buttons 6px, cards 8px, modals 10px. No pill shapes except status badges and filter chips.

**Shadows:** none by default on cards (border only, per Style Spec Section 18); `sm` shadow reserved for dropdowns/modals/popovers.

---

## 4. Cross-Cutting Components

These recur across nearly every screen; build them once.

### 4.1 Status Badge
Small pill, color + text (never color alone), used for quotation status, approval stage, fulfillment status, invoice status, subscription status. Map states to the semantic colors in Section 3:
- Draft — neutral
- Pending Approval / Under Negotiation / Pending / Backorder / Partially Fulfilled / Unpaid — warning
- Approved / Confirmed / Active / Paid / Fulfilled — success
- Rejected / Over Limit / Past Due / Cancelled — error

### 4.2 KPI Card
Used on Screens 2, 14, 15, 16 (dashboards/catalog summary rows). Border, small radius, no/minimal shadow, per Style Spec Section 8. Contains: label, large value, optional secondary caption (e.g., "4 quotations waiting"). Not clickable unless the wireframe shows it linking somewhere (see per-screen notes — Screen 2's cards are the entry point into filtered list views; this is inferred from the PRD's "Central hub, links out to every module below," not explicitly drawn as a click target — `TBD` on exact click behavior, but a sensible default).

### 4.3 Data Table
Used on nearly every List/Detail screen (Screens 3, 5, 7, 9, 12, 16, and inline tables inside Screens 4, 6, 8, 10, 13, 14, 17, 18). Compact rows, clear column hierarchy, hover state, sortable/filterable where the wireframe shows filter chips or a search box. Row click opens the corresponding detail screen wherever the wireframe note says "Click a row to open..." (this phrase appears verbatim on Screens 3→4, 5→6, 7→8, 9→10, 12→13, 16→17 — treat it as the standard list→detail pattern across the whole app).

### 4.4 Note/Callout Bar
Every screen in the wireframe has a highlighted note bar (rendered as a dark-yellow/olive box in the mockup) containing a plain-language explanation of the screen's behavior (e.g., "Discount is checked against each line's own limit..."). Render these as a subtle inline info banner (not a toast, not a modal) directly below the relevant table/section — they are persistent contextual help, not transient notifications. Use a neutral/info tone (light background, left border accent), not a warning color, unless the content is itself a warning.

### 4.5 Approval Stepper
Used on Screen 6 (Submitted → Sales Manager → Finance → Confirmed) and Screen 13 (Order Confirmed → Shipped → Invoiced → Paid). Horizontal step indicator, filled/current/upcoming states. On Screen 6, the Finance step must visually indicate when it's skipped (low-risk quotes only need Sales Manager) vs. required (high-risk quotes need both) — exact visual treatment for "skipped" is `TBD`, propose greying it out with a "not required" label.

### 4.6 Filter Chips
Used on Screens 5, 9, 12 (e.g., "5 Pending / 1 Returned / 12 Approved"). Clickable toggle chips that filter the table beneath them; show the active filter clearly per Style Spec Section 21.

### 4.7 Audit Trail List
Used on Screen 6 (and referenced by the PRD for every approval/rejection/edit). Table/list of `User | Action | Date | Note`. Read-only, append-only, chronological.

---

## 5. Screen-by-Screen Specification

Numbering matches the wireframe's own screen numbers (circled numerals on the canvas).

---

### Screen 1 — Login / Signup
**Route:** `/login`
**Roles:** Unauthenticated (all roles land here first)

**Layout:** Centered single-column card labeled "DealFlow360." Login / Sign Up as two modes (tabs or toggle — wireframe shows both buttons at top; exact toggle mechanism `TBD`, a simple tab switch is the reasonable default).

**Fields:** Email, Password.
**Actions:** `Log In` (primary), `Forgot Password?` (link).

**Note bar content (render as Section 4.4 component):**
- After login, internal users land on the Sales Dashboard (Screen 2). Customers land on their Quotation Portal (Screen 11 / customer shell).
- Company/Team selector shown for multi-team setups.
- Basic validation on email and password fields.
- Sign Up link creates a new internal or customer account.

**Post-login routing logic (derived from role):**
- Sales Rep, Sales Manager, Finance, Admin → `/dashboard` (Screen 2), internal shell.
- Customer → customer portal shell, negotiation screen for their quotation (Screen 11) or `My Quotations` if they have more than one (see Section 2.2).

**Gap:** the "Company/Team selector for multi-team setup" mentioned in the note bar has no drawn field. `TBD` — do not invent its exact UI; a simple dropdown next to email is the reasonable placeholder if it turns out to be needed for the demo.

---

### Screen 2 — Sales Dashboard / Home
**Route:** `/dashboard`
**Roles:** Sales Rep, Sales Manager, Finance, Admin (content may be scoped to "my deals" for Rep vs. team/org-wide for Manager/Finance/Admin — wireframe doesn't distinguish this; `TBD`, reasonable default: Rep sees own quotations only, others see team/org-wide, consistent with the role model in Section 1).

**Subtitle (render verbatim as page description):** "Central hub, links out to every module below."

**Layout:** Three KPI cards (Section 4.2) in a row:
- **Pending Approvals** — "4 quotations waiting" — links to Approvals List (Screen 5), filtered to pending.
- **Open Quotations** — "12 active deals" — links to Quotations List (Screen 3).
- **At-Risk Deals** — "3 flagged by Deal Health" — links to Deal Health Dashboard (Screen 14).

**Actions:** `+ New Quotation` (primary — opens a new Quotation Detail in draft state, Screen 4) and `View Approvals` (secondary — Screen 5).

**Recent Activity section:** plain list of recent events, e.g.:
- "Acme Corp quotation approved by Finance"
- "Beta Industries requested a discount change"
- "East Depot stock updated for Order #Q291"

Each line should deep-link to the relevant record (quotation, quotation, fulfillment detail respectively) where the entity is identifiable — this mirrors the deep-link behavior explicitly described for Deal Health alerts (PRD B9: "Clicking an alert opens the related quotation directly"). Exact click targets per activity type are `TBD` beyond this inference.

---

### Screen 3 — Quotations List
**Route:** `/quotations`
**Roles:** Sales Rep (own quotations), Sales Manager/Finance/Admin (team/org-wide)

**Subtitle:** "Every quotation in the system, one row per quotation, click a row to open it."

**Layout:** This screen doubles as the PRD's "Pipeline" Kanban view (B1/B2) and the plain list — the wireframe draws it as status-grouped columns (a lightweight Kanban), with a `Switch to Table View` toggle for a flat sortable table. Columns/stages, left to right:
- **Draft** — e.g., "Acme Corp — $12,400", "Delta LLC — $5,200"
- **Pending Approval** — e.g., "Beta Industries — $28,600"
- **Approved** — e.g., "Nova Retail — $8,750"
- **Negotiation** — e.g., "Zenith Co — $15,100"
- **Confirmed** — e.g., "Orion Ltd — $41,300"

**Confirmed:** `negotiation` is a real backend quotation state, distinct from `approved`/`pending_approval` — not a UI-only grouping. The exact transition rules (which states can enter/exit `negotiation`) are a backend data-model decision (`PROJECT_CONTEXT.md` / Phase 2) and out of scope for this document. What the frontend needs regardless of how that's resolved:

- Render `negotiation` as its own distinct status value everywhere a quotation's status is shown (this column, Screen 4's header, Screen 6, Screen 11) — never merge it visually with `Approved` or `Pending Approval`.
- Status badge (Section 4.1): give `negotiation` its own mapped color (grouped under the "warning" semantic alongside `Pending Approval`/`Backorder`, since "needs attention" is the correct read).
- Screen 6 must be able to show a "re-entered approval after customer counter-offer" note whenever a quotation arrives there from `negotiation` — this only requires the record to carry that origin as data; the frontend does not need to validate the transition itself.

Each card shows: customer name, amount. Clicking a card opens Quotation Detail (Screen 4).

**Actions:** `+ New Quotation` (primary), `Switch to Table View` (secondary — renders the same data as a Section 4.3 data table with sortable columns: Customer, Amount, Status, Owner, Last Updated).

---

### Screen 4 — Quotation Detail
**Route:** `/quotations/:id` (example shown: Q-1042, Acme Corp)
**Roles:** Sales Rep (own quotation, edit), Sales Manager/Finance (view), Admin (view). Customer never sees this screen — they see Screen 11 instead.

**Subtitle:** "Opened by clicking a row on the Quotations List. Add products, apply discounts, review specifics."

**Layout:**
- Header fields: Customer (selector), Price List (selector).
- Line-item table — columns: **Product, Qty, Price, Discount, Limit, Status**. Example rows:
  - Laptop Pro 14 — 2 — $1,200 — [discount] — [limit] — OK
  - Onsite Setup Service — 1 — $450 — [discount] — [limit] — **OVER LIMIT**
  - Extended Warranty — 1 — $180 — [discount] — [limit] — OK

  "Limit" is the per-line/per-category discount ceiling (from Screen 18 config); "Status" reflects whether the given discount is within that line's own limit. Use the error/warning badge treatment (Section 4.1) for `OVER LIMIT`.

- **Note bar:** "Discount is checked against each line's own limit, not just an overall limit — one line over triggers approval, even if others are fine." This is the Blended Discount Risk Score concept (PRD Section 10) surfacing at the line level; render prominently, it's core to the product's differentiator.

- **Upsell and Cross-Sell Suggestions panel** (PRD B5), shown alongside the line-item table:
  - `+ Wireless Mouse` — margin +$18
  - `+ Docking Station` — Promo: 12% off
  - `+ Care Plan 2yr` — margin +$96

  Each suggestion has an add action (the wireframe shows `+` prefixed names as the add affordance; PRD also specifies a `Dismiss` action per suggestion — not visually distinguished in the wireframe, but required by PRD B5, so include it, e.g. as a small "x" or "Dismiss" text link next to each suggestion card). Adding a suggestion must update the line-item table and any live margin/total indicator immediately (PRD: "the margin indicator on the quotation updates immediately").

**Actions:** `Save Draft` (secondary), `Submit for Approval` (primary). Submitting evaluates the blended risk score; if any line is over its limit (or the blended score crosses a threshold), the quotation routes to Approvals (Screen 5/6) automatically — this transition is drawn as a labeled arrow in the wireframe ("Discount is checked against each line's own limit, as soon as it's entered, not only at submit time" per the note bar, plus a separate red-dashed connector between this screen and the Approval Detail screen labeled "if negotiated terms exceed threshold, quote re-enters approval" — see Screen 6 notes).

**Missing/TBD:** exact UI for entering a discount value per line (input field, %, or slider) is not drawn — only the resulting Discount/Limit/Status columns are shown. Implement as an inline editable percentage field in the Discount column; this is the minimum needed to make the row functional, not an invented feature.

---

### Screen 5 — Approvals List
**Route:** `/approvals`
**Roles:** Sales Manager (act), Finance (act), Admin (view), Sales Rep (view own, read-only)

**Subtitle:** "Every quotation that needed review, waiting to go through discount approval."

**Filter chips (Section 4.6):** `5 Pending`, `1 Returned`, `12 Approved`.

**Table columns:** Quotation, Customer, Blended Risk, Stage, Assigned To. Example rows:

| Quotation | Customer | Blended Risk | Stage | Assigned To |
|---|---|---|---|---|
| Q-1042 | Acme Corp | HIGH | Sales Manager | M. Shah |
| Q-1039 | Beta Industries | MEDIUM | Finance | P. Iyer |
| Q-1030 | Nova Retail | LOW | Auto-Approved | — |

"Blended Risk" uses the badge component (HIGH=error, MEDIUM=warning, LOW/Auto-Approved=success/neutral).

**Note bar:** "Click any row to see full approval risk breakdown and audit trail."

**Actions:** `Filter: Pending Only` toggle (secondary).

Row click → Approval Detail (Screen 6).

---

### Screen 6 — Approval Detail
**Route:** `/approvals/:id` (example: Q-1042, Acme Corp)
**Roles:** Sales Manager (act at Manager step), Finance (act at Finance step), Admin (view/override — exact override rights `TBD`), Sales Rep (view own, read-only)

**Header badges:** `Blended Risk: HIGH`, `Customer Tier: Gold`.

**"Why This Quote Was Flagged" table** — columns: Line, Discount Given, Limit Allowed, Over By. Example:

| Line | Discount Given | Limit Allowed | Over By |
|---|---|---|---|
| Laptop (Hardware) | 12% | 15% | 0 pt — OK |
| Setup Service (Services) | 18% | 10% | 8 pt OVER |

**Note bar:** "Even though the tier allows 15%, the Service line broke its own stricter limit — this is what triggers blended scoring." (This is the direct UI expression of PRD Section 10's worked example — keep the wording aligned with that section so it's demo/viva-consistent.)

**Approval stepper (Section 4.5):** `Submitted → Sales Manager → Finance → Confirmed`. Finance step only activates/required when the blended risk crosses the Finance threshold (configured on Screen 18); otherwise it's skipped (see Section 4.5 note on "skipped" treatment, `TBD` on exact visual).

**Audit trail table** — columns: User, Action, Date, Note. Example:

| User | Action | Date | Note |
|---|---|---|---|
| J. Ravi | Submitted | Aug 20 | Initial 12% discount |
| M. Shah | Returned | Aug 21 | Requested justification |
| J. Ravi | Resubmitted | Aug 22 | Added margin note |

This is the append-only log required by both the PRD ("all approvals, rejections, and edits must be logged with user, timestamp, and reason") and `SECURITY_SPEC.md` Section 10 (`audit_logs` table, `ROLE_CHANGED`/`DISCOUNT_APPROVED`/etc. event types).

**Actions:** `Approve` (primary/success), `Return for Revision` (secondary/warning — sends back to the Sales Rep, Screen 4, in a `draft`-like editable state), `Reject` (destructive — requires confirmation per Style Spec Section 12).

**Cross-screen connector (drawn in wireframe as a red dashed line + label near the top of this screen):** "if negotiated terms exceed threshold, quote re-enters approval" — this is the same automatic re-approval triggered from the Customer Portal (Screen 11) when a customer's counter-offer breaches thresholds. When a quotation re-enters approval this way, this screen should make that origin visible (e.g., a note like "Re-entered approval after customer counter-offer" sourced from the audit trail) rather than looking identical to a first-time submission — exact copy `TBD`, but the distinction should exist for viva/audit clarity.

---

### Screen 7 — Fulfillment List
**Route:** `/fulfillment`
**Roles:** Finance/Operations (act), Admin (view/act), Sales Manager (view), Sales Rep (view own orders)

**Subtitle:** "Live stock per warehouse, plus every order that still needs fulfilling."

**Stock table** — columns: Warehouse, Product, In Stock, Reserved, Available. Example:

| Warehouse | Product | In Stock | Reserved | Available |
|---|---|---|---|---|
| Main Warehouse | Laptop Pro 14 | 40 | 18 | 22 |
| East Depot | Laptop Pro 14 | 6 | 0 | 6 |
| Main Warehouse | Docking Station | 85 | 12 | 73 |

**"Orders Awaiting Fulfillment" table** — columns: Order, Customer, Status, Warehouse. Example:

| Order | Customer | Status | Warehouse |
|---|---|---|---|
| Q-1042 | Acme Corp | Split Pending | Main + East Depot |
| Q-1038 | Zenith Co | Backorder | East Depot |

**Note bar:** "Click an order row to open its warehouse split detail."

Row click → Fulfillment Detail (Screen 8).

---

### Screen 8 — Fulfillment Detail
**Route:** `/fulfillment/:id` (example: Q-1042, Acme Corp)
**Roles:** Finance/Operations (act — accept/override), Admin (act), Sales Manager/Sales Rep (view)

**Subtitle:** "Opened by clicking a row on the Fulfillment List."

**Split table** — columns: Warehouse, Qty Fulfilled, Est. Shipments, Cost. Example:

| Warehouse | Qty Fulfilled | Est. Shipments | Cost |
|---|---|---|---|
| Main Warehouse | 18 units | 1 | $42 |
| East Depot | 4 units | 1 | $29 |

**Note bar:** "Consolidate Remaining Backorder" prompt appears automatically once East Depot restocks — render this as a conditional banner/action that appears only when a backorder exists for this order and new stock has arrived (matches PRD B6: "If stock arrives mid fulfillment, a 'Consolidate Remaining Backorder' prompt appears automatically").

**Actions:** `Accept Suggested Split` (primary), `Manual Override` (secondary — opens an editable version of the split table; exact override UI, e.g. inline qty edits per warehouse row, is `TBD` beyond "the table becomes editable").

Downward flow arrow in the wireframe connects this screen to Subscriptions List (Screen 9) — i.e., once fulfillment is settled, the natural next stop in the flow is billing/subscriptions for the same order. Treat this as a suggested "next" link/breadcrumb on this screen (e.g., "View billing for this order →"), not a forced redirect.

---

### Screen 9 — Subscriptions List
**Route:** `/subscriptions`
**Roles:** Finance/Operations (act — reconcile, modify/cancel), Admin (act — create plans), Sales Manager/Sales Rep (view)

**Subtitle:** "Every recurring plan across every customer, regardless of which order it came from."

**Filter chips:** `18 Active`, `2 Paused`, `3 Cancelled`.

**Table columns:** Customer, Plan, Cycle, Next Bill, Status. Example:

| Customer | Plan | Cycle | Next Bill | Status |
|---|---|---|---|---|
| Acme Corp | Care Plan 2yr | Monthly | Sep 15 | Active |
| Beta Industries | Support SLA | Quarterly | Nov 1 | Active |
| Delta LLC | Care Plan 1yr | Monthly | — | Paused |

**Note bar:** "Click a subscription row to open its billing detail and proration history."

**Actions:** `+ New Plan (Admin)` — visible/enabled only for Admin, per its own label; this is plan *definition* (PRD A5), distinct from a customer's individual subscription line.

Row click → Billing Detail (Screen 10).

---

### Screen 10 — Billing Detail
**Route:** `/subscriptions/:id` (example: Acme Corp — Care Plan 2yr)
**Roles:** Finance/Operations (act), Admin (act), Sales Manager/Sales Rep (view)

**Subtitle:** "Opened by clicking a row on the Subscriptions list."

**"One-Time Lines (from originating order)" table** — columns: Product, Qty, Amount. Example:

| Product | Qty | Amount |
|---|---|---|
| Laptop Pro 14 | 2 | $2,280 |
| Onsite Setup | 1 | $450 |

**"Recurring Lines" table** — columns: Plan, Cycle, Next Bill Date, Amount. Example:

| Plan | Cycle | Next Bill Date | Amount |
|---|---|---|---|
| Care Plan 2yr | Monthly | Sep 15 | $40 |
| Support SLA | Quarterly | Nov 1 | $300 |

This two-table layout is the direct UI expression of the PRD's hybrid billing requirement: "shows one-time lines and recurring lines separately within the same order" (B7). Any proration adjustment (mid-cycle quantity/plan change) should show as an additional line or annotation within the Recurring Lines table — exact proration display format is `TBD` pending the proration rounding rule (`PROJECT_CONTEXT.md` Known Issues).

**Actions:** `Modify Subscription` (secondary), `Cancel Subscription` (destructive — per PRD B7, "an automatic partial refund or credit note trigger" fires on cancel; the frontend should show a confirmation step communicating that, not just a bare confirm dialog).

---

### Screen 11 — Customer Portal Negotiation Screen
**Route:** customer portal shell, e.g. `/portal/quotations/:id`
**Roles:** Customer (Portal User) only. This is the one screen internal roles never see in this shell.

**Subtitle:** "Customer reviews and negotiates the quote directly, no email needed."

**Status badge:** e.g. `Status: Under Negotiation` (also: Sent, Confirmed — per PRD B8).

**Comment/negotiation table** — columns: Line, Customer Comment. Example:

| Line | Customer Comment |
|---|---|
| Extended Warranty | "Can we get 10% instead of 5%?" |
| Onsite Setup | "Can we push this to next month?" |

This is the "line level comment and change request tool" from PRD B8.

**Fields:** Counter Discount %, Requested Delivery Date.

**Actions:** `Submit Request` (secondary — sends the counter/comments without finalizing), `Confirm Quotation` (primary — accepts current terms).

**Note bar:** "If final terms exceed thresholds, the quote automatically re-enters approval (Screen 6)." This is the auto re-approval loop (PRD B8 and the "Complete Flow" section) — after `Confirm Quotation`, if the negotiated terms breach discount thresholds, route back into the approval flow (Screen 6) rather than straight to fulfillment; otherwise proceed directly to fulfillment (Screen 8) per the PRD's "otherwise, the order moves directly to fulfillment."

**Explicit constraint:** this screen (and its shell) must never expose any internal-only control, data field, or navigation item — no discount limits, no other customers' data, no internal audit trail, no role/permission info. Keep this screen's data strictly scoped to what PRD B8 lists.

---

### Screen 12 — Invoices List
**Route:** `/invoices`
**Roles:** Finance/Operations (act), Admin (view), Sales Manager/Sales Rep (view)

**Subtitle:** "Every invoice generated from one-time and recurring lines."

**Filter chips:** `4 Unpaid`, `1 Past Due`, `12 Paid`.

**Table columns:** Invoice #, Customer, Amount, Status, Due Date. Example:

| Invoice # | Customer | Amount | Status | Due Date |
|---|---|---|---|---|
| INV-1042 | Acme Corp | $2,730 | Unpaid | Sep 30 |
| INV-1041 | Acme Corp | $40 | Paid | Sep 15 |
| INV-1030 | Nova Retail | $8,750 | Paid | Aug 30 |

**Note bar:** "Click an invoice row to see full payment and delivery reconciliation detail."

Row click → Invoice Detail (Screen 13).

---

### Screen 13 — Invoice Detail
**Route:** `/invoices/:id` (example: INV-1042, Acme Corp)
**Roles:** Finance/Operations (act — record payment), Admin (view), Sales Manager/Sales Rep (view)

**Subtitle:** "Opened by clicking a row on the Invoices List."

**Delivery/payment stepper (Section 4.5):** `Order Confirmed → Shipped → Invoiced → Paid`.

**Line table** — columns: Invoice #, Amount, Status, Due Date. Example:

| Invoice # | Amount | Status | Due Date |
|---|---|---|---|
| INV-1042 | $2,730 | Unpaid | Sep 30 |
| INV-1041 (Recurring) | $40 | Paid | Sep 15 |

**Actions:** `Record Payment` (primary), `Download Summary` (secondary).

**Note bar:** "Partial invoicing stays reconciled with partial delivery, nothing is billed before it ships." — surfaces the fulfillment↔billing reconciliation the PRD requires for split/backordered orders; make sure the stepper and line table visually agree with the linked Fulfillment Detail (Screen 8) state for the same order.

---

### Screen 14 — Deal Health and Anomaly Dashboard
**Route:** `/deal-health`
**Roles:** Sales Manager (act — escalate/nudge), Admin (view/act), Finance (view), Sales Rep (view own deals, read-only)

**Subtitle:** "Real-time flags for stalled deals and unusual discount patterns."

**KPI cards:**
- **Stalled Deals** — "3 quotes for 7+ days"
- **Discount Anomalies** — "2 above rep average"
- **Delivery Slippage** — "2 promises at risk"

**Table columns:** Deal, Issue, Flagged, Action. Example:

| Deal | Issue | Flagged | Action |
|---|---|---|---|
| Delta LLC | Idle 9 days | Aug 24 | Nudge sent |
| Q-1038 | Discount 22% vs avg 8% | Aug 25 | Escalated to Manager |

Clicking a deal row opens the related Quotation Detail (Screen 4) directly, per PRD B9 ("Clicking an alert opens the related quotation directly").

**Actions:** `Escalate` (secondary), `Nudge Rep` (secondary) — both are the "automated nudge or escalation action" from PRD B9, triggered per-row (exact row- vs. dashboard-level trigger scope is inferred from the two buttons sitting at dashboard level in the wireframe; if per-row actions are also needed, add them to the Action column — `TBD` on whether both scopes are needed for the demo).

**Anomaly threshold definitions** (what counts as "stalled," what counts as an anomalous discount) are explicitly listed as not-yet-locked in `PROJECT_CONTEXT.md` Known Issues — the frontend should treat these as backend-computed values it displays, not compute them client-side.

---

### Screen 15 — Admin / Reporting Dashboard (Optional)
**Route:** `/reports`
**Roles:** Admin, Sales Manager (per PRD A7's general "sales performance" framing — Finance may also need billing-relevant views; exact per-role report scoping is `TBD`, PRD doesn't split this by role)

**Subtitle:** "Sales trends, approval bottlenecks and platform usage."

**Filters:** Period, Sales Team, Approval Status, Product — matches PRD's "Reporting Filters" section exactly (date range, rep/team, pending/approved/rejected, best-selling/most-discounted).

**KPI cards:**
- **Quotas Created** — "164 this month" *(likely "Quotations Created" — wireframe text may be truncated; keep the label as "Quotations Created" unless the team confirms otherwise — flag as a minor `TBD` label check)*
- **Avg Approval Time** — "6.4 hours"
- **Top Upsold Product** — "Care Plan 2yr"

**Actions:** `Export PDF`, `Export XLS` — both required by PRD A7.

This screen is explicitly marked "(Optional)" in its own wireframe title, consistent with its 🟡/reporting placement in `PLAN.md` Section 18 (Supporting, not Core). Build after Core flows are solid.

---

### Screen 16 — Product Catalog
**Route:** `/admin/products`
**Roles:** Admin only (per PRD A2, module owned by Admin's backend configuration area)

**Subtitle:** "Every product, variant and price list in one place."

**KPI cards:**
- **Total Products** — "128 active, 9 archived" (reflects the archival-not-hard-delete pattern for master data from `PROJECT_CONTEXT.md`)
- **Pricelists** — "3 tiers, 2 currencies"
- **Variants** — "340 SKUs across all products"

**Table columns:** Product name, Category, Variant, Price, Unit, Tax, Status. Example:

| Product name | Category | Variant | Price | Unit | Tax | Status |
|---|---|---|---|---|---|---|
| Laptop Pro 14 | Hardware | Color | $1,200 | Each | 15% | Active |
| Onsite Setup Service | Services | — | $450 | Each | 10% | Active |
| Docking Station | Hardware | Color | $180 | Each | 15% | Active |
| Care Plan 3 yrs | Subscription | — | $40/month | Recurring | 8% | Active |

**Note bar:** "Click a product row to open general info, variants, and low-margin/price rules."

**Actions:** `+ New Product` (primary), `Manage Price fields` (secondary — likely opens price-list/field configuration; exact scope of this action beyond the label is `TBD`).

Row click → Product Detail (Screen 17).

---

### Screen 17 — Product Detail (Product and Pricelist)
**Route:** `/admin/products/:id`
**Roles:** Admin only

**"General Info" form fields:** Product name, Category, Price, Unit, Tax %, Description; Subscription (Yes/No toggle), Recurring (Monthly/Yearly/Weekly — only shown/enabled when Subscription = Yes, per the wireframe's own note "if subscription yes then recurring will be visible"), Quantity on hand (integer field).

**"Product Variants" table** — columns: Attribute, Values, Extra price. Example:

| Attribute | Values | Extra price |
|---|---|---|
| Color | Blue, Black | $0 |
| RAM | 4GB, 8GB | +$30 |
| Manufacturer | Dell, HP | +$10 / +$30 |

**"Pricelists" table** — columns: Tier, Currency, Price Rule. Example:

| Tier | Currency | Price Rule |
|---|---|---|
| Bronze | USD | Price, no adjustment |
| Gold | USD/EUR | Price minus 10 percent base |

**Note bar:** "Product details should be filled. Recurring order with the product will be accessed at the beginning of the period."

This screen implements PRD A2 (General Info / Variants / Price Lists) and A5 (recurring plan attachment) directly.

---

### Screen 18 — Discount Tiers and Approval Chain Setup
**Route:** `/admin/discount-tiers`
**Roles:** Admin (full access), Sales Manager (per PRD A3 — configures discount tiers and approval chains)

**Title:** "Discount tiers and approval chains."

**"Tier Discount Ceilings" table** — columns: Tier, Max Discount. Example:

| Tier | Max Discount |
|---|---|
| Bronze | 5 percent |
| Silver | 10 percent |
| Gold | 15 percent |

**"Category Discount Ceilings" table** — columns: Category, Max Discount. Example:

| Category | Max Discount |
|---|---|
| Hardware | 15 percent |
| Services | 10 percent |

**"Discount range → approval chain" table** — columns: Discount Range, Required Approval. Example:

| Discount Range | Required Approval |
|---|---|
| Within tier/category limit | No approval needed |
| Over limit, blended risk medium | Sales Manager |
| Over limit, blended risk high | Sales Manager then Finance |

This table is the direct configuration surface for the blended risk routing described in PRD Section 10 and is what populates the Limit column on Screen 4, the risk badges on Screens 5/6, and the approval stepper's Finance-required/skipped state on Screen 6.

**Actions:** `Save configuration` (primary).

**Note bar:** "When a quote combines different ceilings, the system must compute a blended risk score and route to the highest required level. All approvals, rejections, and edits must be logged with user, timestamp, and reason."

**Explicit dependency:** the exact blended risk score formula is marked "not yet locked" in `PROJECT_CONTEXT.md` and `PLAN.md` Section 0.6. This screen's job is to capture the *configuration inputs* (tier ceilings, category ceilings, threshold bands); it should not hardcode the scoring formula itself — that lives in backend business logic and is only reflected here as results (badges, "Over By" values) elsewhere in the app.

> **Status update (2026-09-05):** the formula, the single-line Finance gate, the routing bands and the ceiling matrix are now all LOCKED — see `PROJECT_CONTEXT.md` "Locked Business Rules" #1, #2 and #6. The dependency above is resolved. The guidance still stands unchanged: this screen captures configuration inputs and displays backend-computed results; it must never compute the score client-side.

---

## 6. Traced End-to-End Flows

These match the PRD's required demo flows (`PLAN.md` Phase 11) and the wireframe's own connector arrows between screens. Build these two paths as the primary integration/testing spine.

**Flow 1 — Over-limit discount → approval → fulfillment**
Screen 4 (Rep enters a discount exceeding a line's limit) → auto-flag surfaces inline (Screen 4's Status column shows `OVER LIMIT`) → `Submit for Approval` → Screen 5 (appears in Approvals List) → Screen 6 (Sales Manager reviews "Why This Quote Was Flagged," approves; Finance step added if blended risk is HIGH) → Screen 7/8 (approved quote appears in "Orders Awaiting Fulfillment," warehouse split shown, `Accept Suggested Split` or `Manual Override`) → (if a warehouse is short) backorder flagged, "Consolidate Remaining Backorder" surfaces once restocked.

**Flow 2 — Upsell → customer negotiation → auto re-approval → hybrid billing**
Screen 4 (Rep accepts an upsell suggestion, e.g. `+ Care Plan 2yr`; margin updates live) → `Submit for Approval` (if needed) or straight to customer → Screen 11 (Customer Portal: customer sees the quote, adds comments, submits a counter discount) → if the counter breaches thresholds, quote auto re-enters Screen 6 (approval) with the origin visible in the audit trail → once confirmed, Screen 10 (Billing Detail shows the one-time Laptop/Setup lines and the new recurring Care Plan 2yr line together) → Screen 13 (Invoice Detail reflects both one-time and recurring invoices, payment recorded).

**Dashboard deep-links (Screen 2 → everywhere):** Pending Approvals card → Screen 5 (filtered); Open Quotations card → Screen 3; At-Risk Deals card → Screen 14. Recent Activity list items → the specific record referenced.

---

## 7. States (apply per Style Spec Sections 23–25)

Every list screen (3, 5, 7, 9, 12, 16) and every dashboard (2, 14, 15) needs:
- **Loading:** skeleton rows for tables, skeleton cards for KPI rows — never a blank screen or full-page spinner for these.
- **Empty:** e.g. "No quotations yet — create your first quotation to start managing your pipeline" (+ `+ New Quotation` action) vs. "No quotations found — you don't have any matching the current filters" (+ clear-filters action), matching Style Spec Section 24's two-case pattern.
- **Error:** specific, actionable messages ("Unable to load quotations. Please try again.") with a retry action, never a raw error dump — this also satisfies `SECURITY_SPEC.md`'s requirement to never leak stack traces/DB details to the frontend.

Form/detail screens (4, 6, 8, 10, 17, 18) need inline field-level validation errors near the relevant field, and a disabled/loading state on primary action buttons while a submit is in flight (never allow a double-submit on `Submit for Approval`, `Approve`/`Reject`, `Confirm Quotation`, `Record Payment` — these are exactly the concurrent-operation risks `PLAN.md` Phase 9 calls out, e.g. two managers approving the same quote at once).

---

## 8. Responsive Behavior

Desktop is the primary experience (this is an ops console used for hours at a time). Per Style Spec Section 27:
- Sidebar collapses to icon-only or an off-canvas drawer on tablet/narrow widths.
- Data tables (Screens 3, 5, 7, 9, 12, 16) go horizontally scrollable rather than silently dropping columns.
- The Quotation Builder (Screen 4) and Approval Detail (Screen 6), which have multi-section layouts (line table + upsell panel; risk table + stepper + audit trail), should stack vertically on narrower widths rather than compress.
- The Customer Portal (Screen 11) is the one screen most likely to be opened on mobile by an actual customer — prioritize it being fully usable single-column on small screens, more so than any internal screen.

---

## 9. Consolidated Open Questions / TBD List

Carry these into `PROJECT_CONTEXT.md`'s Known Issues per `PLAN.md` Section 0.6 — do not resolve them silently in the frontend:

1. Exact login mode toggle (tabs vs. buttons) — Screen 1.
2. Company/Team selector UI for multi-team login — mentioned in Screen 1's note bar, not drawn.
3. ~~Whether "Negotiation" (Screen 3) is a distinct backend state~~ — **Resolved:** it is. See Screen 3's spec above for the frontend display requirements this implies; the exact transition rules are a backend/Phase 2 decision, out of scope here.
4. Discount input control per line on Screen 4 (percentage field, stepper, etc.) — only the resulting columns are drawn.
5. Dismiss affordance styling for upsell suggestions (Screen 4) — PRD requires it, wireframe doesn't visually distinguish it from Add.
6. Visual treatment for a "skipped" (not required) step in the approval stepper (Screen 6).
7. Manual Override interaction detail on Fulfillment Detail (Screen 8) — assumed inline-editable table.
8. Proration display format in Billing Detail (Screen 10) — pending the proration rounding rule.
9. `My Quotations` list, `Messages`, and `Profile` screens in the Customer Portal shell — only nav labels exist, no screen content specified.
10. PRD B1 top-menu actions (`Reload Data`, `Go to Back-end`, `Close Workspace`) — not present anywhere in the wireframe.
11. Per-role scoping of Screens 2, 7, 9, 12, 14, 15 (own deals/orders vs. team/org-wide) — wireframe doesn't distinguish; defaults proposed in each screen's Roles line above.
12. `Manage Price fields` action scope on Screen 16.
13. Whether Escalate/Nudge (Screen 14) act on a selected row or the dashboard as a whole.
14. Exact label on Screen 15's first KPI card ("Quotas Created" vs. "Quotations Created").
15. Warehouse creation/configuration UI and full Subscription Plan creation form (PRD A4/A5) — no wireframe screen exists for either; only a stock view (Screen 7) and a `+ New Plan (Admin)` button (Screen 9) are drawn.
16. Upsell/Cross-Sell Rule Setup screen (PRD A6, marked Optional/Bonus in the PRD) — not wireframed at all.
17. Admin user/role management screen (PRD lists this under Admin's responsibilities) — not wireframed.
18. Header controls (global search, notifications, user menu) — present in the Style Spec's shell description, not detailed in the wireframe beyond their existence.

---

## 10. Suggested Route Map (for implementation reference)

```
/login

# Internal shell
/dashboard                         Screen 2
/quotations                        Screen 3
/quotations/:id                    Screen 4
/approvals                         Screen 5
/approvals/:id                     Screen 6
/fulfillment                       Screen 7
/fulfillment/:id                   Screen 8
/subscriptions                     Screen 9
/subscriptions/:id                 Screen 10
/invoices                          Screen 12
/invoices/:id                      Screen 13
/deal-health                       Screen 14
/reports                           Screen 15
/admin/products                    Screen 16
/admin/products/:id                Screen 17
/admin/discount-tiers              Screen 18

# Customer portal shell (separate layout, no internal nav)
/portal/quotations                 (TBD stub — Section 2.2)
/portal/quotations/:id             Screen 11
/portal/messages                   (TBD stub)
/portal/profile                    (TBD stub)
```

Route-level guards must check role (and, for `:id` routes, resource ownership for Sales Rep and Customer) before rendering — mirroring `SECURITY_SPEC.md` Section 4's authorization order (identity → role → action → resource → ownership). Frontend guards are a UX convenience only; the backend must independently reject unauthorized calls regardless of what the frontend shows.
