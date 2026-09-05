# DealFlow360 — Data Model & Architecture

Required deliverable of PLAN.md Phase 2, and doubles as the one-page
architecture diagram required by the hackathon spec (PRD Section 8).

**Keep this current.** If the schema changes and this file does not, the next
session inherits a lie. Source of truth is `backend/app/models/`; this is its
picture.

- 30 tables · 70 foreign keys · migration `809cac63fb15`
- Regenerate the table list with:
  `docker compose exec db psql -U dealflow -d dealflow360 -c "\dt"`

---

## 1. System architecture

```mermaid
flowchart TB
    subgraph browser["Browser"]
        REP["Rep workspace<br/>(quotation builder)"]
        PORTAL["Customer portal<br/>(separate, restricted view)"]
    end

    subgraph api["FastAPI backend — /api/v1"]
        AUTH["Auth + RBAC<br/>permission → resource ownership"]
        QUOTE["Quotation service<br/>totals · live margin"]
        RISK["Blended risk engine<br/>+ single-line Finance gate"]
        APPR["Approval routing<br/>reads approval_chains"]
        FULFIL["Warehouse split<br/>greedy fill + backorders"]
        BILL["Hybrid billing<br/>one-time + recurring + proration"]
        HEALTH["Deal health<br/>scheduled async task"]
        AUDIT["Audit logger"]
    end

    DB[("PostgreSQL 16<br/>constraints · state machines · indexes")]

    REP --> AUTH
    PORTAL --> AUTH
    AUTH --> QUOTE
    QUOTE --> RISK
    RISK --> APPR
    APPR --> FULFIL
    FULFIL --> BILL
    QUOTE -.-> HEALTH
    AUTH --> AUDIT
    APPR --> AUDIT

    QUOTE --> DB
    RISK --> DB
    APPR --> DB
    FULFIL --> DB
    BILL --> DB
    HEALTH --> DB
    AUDIT --> DB
```

Backend enforcement is authoritative throughout; the frontend hides controls
for usability only (SECURITY_SPEC.md).

---

## 2. Entity relationship diagram

Attributes are limited to keys and the columns that carry business meaning.
The full column list, with every CHECK constraint, is in
`backend/app/models/`.

All 30 tables appear below. The one without its own box is `ROLE_PERMISSIONS`,
the roles-to-permissions junction: it carries no columns of its own, so it is
drawn as the many-to-many edge between `ROLES` and `PERMISSIONS` rather than
as an entity.

### 2.1 Identity, access and customers

```mermaid
erDiagram
    ROLES ||--o{ USERS : "grants"
    ROLES }o--o{ PERMISSIONS : "role_permissions"
    SALES_TEAMS ||--o{ USERS : "employs"
    USERS ||--o| SALES_TEAMS : "manages"
    CUSTOMERS ||--o{ USERS : "portal logins"

    ROLES {
        int id PK
        string code UK "admin | sales_manager | sales_rep | finance_ops | customer"
        string name
    }
    PERMISSIONS {
        int id PK
        string code UK "deal.approve_finance, portal.own_quote.view, ..."
    }
    USERS {
        int id PK
        string email UK
        string password_hash "Argon2/bcrypt — never returned by an API"
        int role_id FK
        int sales_team_id FK "nullable"
        int customer_id FK "set only for portal users → ownership anchor"
        bool is_active
    }
    SALES_TEAMS {
        int id PK
        string name UK
        int manager_id FK
    }
    CUSTOMERS {
        int id PK
        string code UK
        string name
        string tier "bronze | silver | gold → left key of the discount ceiling"
        string currency
        bool is_active
        datetime archived_at "archival, never hard delete"
    }
```

### 2.2 Catalogue, pricing and discount policy

```mermaid
erDiagram
    PRODUCT_CATEGORIES ||--o{ PRODUCTS : "classifies"
    PRODUCT_CATEGORIES ||--o{ DISCOUNT_TIERS : "ceiling per category"
    PRODUCTS ||--o{ PRODUCT_VARIANTS : "has"
    PRODUCTS ||--o{ PRICE_LIST_ITEMS : "priced by"
    PRICE_LISTS ||--o{ PRICE_LIST_ITEMS : "contains"
    PRODUCTS ||--o{ UPSELL_RULES : "triggers"
    ROLES ||--o{ APPROVAL_CHAINS : "required by"

    PRODUCT_CATEGORIES {
        int id PK
        string code UK
    }
    PRODUCTS {
        int id PK
        string sku UK
        int category_id FK
        decimal list_price
        decimal cost_price "required for the live margin indicator"
        string item_type "one_time | subscription"
        bool is_promoted "ranks higher in upsell suggestions"
    }
    PRODUCT_VARIANTS {
        int id PK
        int product_id FK
        string attribute_name "e.g. Size"
        string attribute_value
        decimal extra_price
    }
    PRICE_LISTS {
        int id PK
        string customer_tier "nullable = applies to all tiers"
        string currency
        date valid_from
        date valid_to
    }
    PRICE_LIST_ITEMS {
        int id PK
        int price_list_id FK
        int product_id FK
        decimal unit_price
        decimal min_quantity "volume break"
    }
    DISCOUNT_TIERS {
        int id PK
        string customer_tier "UNIQUE together with category_id"
        int category_id FK
        decimal max_discount_percent "this is ceiling_i in the risk formula"
    }
    APPROVAL_CHAINS {
        int id PK
        decimal min_score "band is [min_score, max_score)"
        decimal max_score "NULL = unbounded"
        int required_role_id FK
        int step_order
    }
    UPSELL_RULES {
        int id PK
        int trigger_product_id FK
        int suggested_product_id FK
        decimal co_purchase_score
        decimal min_margin_percent "suppress unhealthy suggestions"
    }
```

### 2.3 Quotation, approval, fulfillment and billing

```mermaid
erDiagram
    CUSTOMERS ||--o{ QUOTATIONS : "places"
    USERS ||--o{ QUOTATIONS : "owns (rep)"
    QUOTATIONS ||--o{ QUOTATION_LINES : "contains"
    PRODUCTS ||--o{ QUOTATION_LINES : "sold as"

    QUOTATIONS ||--o{ APPROVAL_REQUESTS : "raises"
    APPROVAL_REQUESTS ||--o{ APPROVAL_STEPS : "ordered steps"
    USERS ||--o{ APPROVAL_STEPS : "decides"

    QUOTATIONS ||--o{ FULFILLMENTS : "ships via"
    FULFILLMENTS ||--o{ FULFILLMENT_SPLITS : "split across warehouses"
    FULFILLMENTS ||--o{ BACKORDERS : "shortfall"
    WAREHOUSES ||--o{ FULFILLMENT_SPLITS : "sources"
    WAREHOUSES ||--o{ STOCK_LEVELS : "holds"
    PRODUCTS ||--o{ STOCK_LEVELS : "stocked as"
    QUOTATION_LINES ||--o{ FULFILLMENT_SPLITS : "fulfilled by"

    SUBSCRIPTION_PLANS ||--o{ QUOTATION_LINES : "attached to"
    QUOTATION_LINES ||--o| SUBSCRIPTIONS : "becomes"
    SUBSCRIPTION_PLANS ||--o{ SUBSCRIPTIONS : "governs"
    SUBSCRIPTIONS ||--o{ PRORATION_RECORDS : "mid-cycle changes"
    QUOTATIONS ||--o{ BILLING_SCHEDULES : "bills as"
    SUBSCRIPTIONS ||--o{ BILLING_SCHEDULES : "instalments"
    BILLING_SCHEDULES ||--o{ PAYMENTS : "settled by"

    QUOTATIONS ||--o{ DEAL_HEALTH_SNAPSHOTS : "monitored by"
    USERS ||--o{ AUDIT_LOGS : "acts"

    QUOTATIONS {
        int id PK
        string quote_number UK
        int customer_id FK
        int owner_id FK "rep — the IDOR ownership anchor"
        string status "9-state machine, see section 3"
        decimal total_amount
        decimal margin_percent "live margin indicator"
        decimal blended_risk_score "value-weighted excess"
        decimal max_line_excess "drives the >15 Finance gate"
        bool requires_finance_approval
        datetime last_activity_at "stalled-deal detection"
        int version "optimistic lock"
    }
    QUOTATION_LINES {
        int id PK
        int quotation_id FK
        int line_number "UNIQUE per quotation"
        int product_id FK
        decimal quantity
        decimal unit_list_price "snapshot at quoting time"
        decimal unit_cost_price "snapshot"
        decimal discount_percent
        decimal allowed_discount_percent "ceiling snapshot — what the policy was"
        decimal line_excess_points "max(0, given - allowed)"
        string line_type "one_time | subscription"
        int subscription_plan_id FK "CHECK: required iff subscription"
        bool added_from_upsell
    }
    APPROVAL_REQUESTS {
        int id PK
        int quotation_id FK
        decimal blended_risk_score "snapshot the routing was based on"
        decimal max_line_excess
        bool triggered_by_line_gate
        string status "pending | approved | rejected | returned_for_revision"
    }
    APPROVAL_STEPS {
        int id PK
        int request_id FK
        int step_order "UNIQUE per request"
        int required_role_id FK "snapshot — chain edits cannot rewrite history"
        int actor_id FK
        datetime decided_at
        string reason "PRD: user, timestamp, reason"
    }
    WAREHOUSES {
        int id PK
        string code UK
        decimal shipping_cost_weight "primary sort key of the greedy split"
    }
    STOCK_LEVELS {
        int id PK
        int warehouse_id FK
        int product_id FK
        int variant_id FK "UNIQUE w/ NULLS NOT DISTINCT"
        decimal quantity_on_hand
        decimal quantity_reserved "CHECK: <= on_hand"
        decimal reorder_point
    }
    FULFILLMENTS {
        int id PK
        int quotation_id FK
        string status "pending | partially_fulfilled | fulfilled | backordered"
        int shipment_count
        decimal estimated_shipping_cost
        bool is_manual_override
        date promised_date "slippage baseline"
    }
    FULFILLMENT_SPLITS {
        int id PK
        int fulfillment_id FK
        int quotation_line_id FK
        int warehouse_id FK
        decimal quantity
    }
    BACKORDERS {
        int id PK
        int fulfillment_id FK
        decimal quantity_outstanding
        string status "open | consolidated | fulfilled | cancelled"
    }
    SUBSCRIPTION_PLANS {
        int id PK
        string code UK
        string billing_interval "monthly | quarterly | yearly"
        int interval_count
        decimal unit_amount
        string refund_policy
    }
    SUBSCRIPTIONS {
        int id PK
        int quotation_line_id FK "UNIQUE — one per line"
        string status "active | modified | cancelled"
        date current_cycle_start
        date current_cycle_end
    }
    BILLING_SCHEDULES {
        int id PK
        int quotation_id FK "hybrid billing reconciles here"
        int subscription_id FK "CHECK: required iff recurring"
        string schedule_type "one_time | recurring"
        string status "scheduled | invoiced | paid | cancelled"
        date due_date
        decimal amount
        bool is_credit_note
    }
    PRORATION_RECORDS {
        int id PK
        int subscription_id FK
        date change_date
        int cycle_days
        int remaining_days
        decimal credit_amount
        decimal charge_amount
        decimal proration_amount "signed; negative = credit note"
    }
    PAYMENTS {
        int id PK
        int billing_schedule_id FK
        decimal amount
        string method
        datetime paid_at
    }
    DEAL_HEALTH_SNAPSHOTS {
        int id PK
        int quotation_id FK
        bool is_stalled
        int days_inactive
        bool has_discount_anomaly
        decimal discount_vs_rep_average
        bool has_delivery_slippage
    }
    AUDIT_LOGS {
        int id PK
        int user_id FK "nullable — a failed login has no user"
        string action
        string resource
        string resource_id
        string status
        string ip_address
        string reason
    }
```

---

## 3. State machines

Enforced in `backend/app/services/state_machine.py`. Invalid transitions raise
`InvalidStateTransition` — they are rejected, not merely unused.

### Quotation

```mermaid
stateDiagram-v2
    [*] --> draft
    draft --> pending_approval : score > 0
    draft --> sent : score = 0, no approval needed
    pending_approval --> approved
    pending_approval --> rejected
    pending_approval --> draft : returned for revision
    rejected --> draft : rep revises
    approved --> sent
    approved --> confirmed
    sent --> under_negotiation : customer responds
    sent --> confirmed
    under_negotiation --> pending_approval : counter-offer breaches threshold
    under_negotiation --> sent : rep re-issues
    under_negotiation --> confirmed
    confirmed --> fulfilled
    fulfilled --> [*]
```

`cancelled` is reachable from every non-terminal state and is terminal, as is
`fulfilled`. `sent`, `under_negotiation` and `rejected` extend the list in
PLAN.md Section 7 — see PROJECT_CONTEXT.md for why.

### Approval (request and each step)

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> approved
    pending --> rejected
    pending --> returned_for_revision
    approved --> [*]
    rejected --> [*]
    returned_for_revision --> [*]
```

All three outcomes are terminal. A decided approval is never reopened — a
customer counter-offer raises a *new* request, so the record of who approved
what survives intact.

### Fulfillment

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> partially_fulfilled
    pending --> fulfilled
    pending --> backordered
    partially_fulfilled --> fulfilled
    partially_fulfilled --> backordered
    backordered --> partially_fulfilled
    backordered --> fulfilled
    fulfilled --> [*]
```

`backordered` returns to `partially_fulfilled` when stock arrives — this edge
is what the PRD's "Consolidate Remaining Backorder" prompt drives.

### Subscription

```mermaid
stateDiagram-v2
    [*] --> active
    active --> modified
    modified --> active
    modified --> modified
    active --> cancelled
    modified --> cancelled
    cancelled --> [*]
```

`modified → modified` is the one deliberate self-transition in the system: a
subscription can be changed again before the previous change settles.

### Billing schedule

```mermaid
stateDiagram-v2
    [*] --> scheduled
    scheduled --> invoiced
    invoiced --> paid
    scheduled --> cancelled
    invoiced --> cancelled
    paid --> [*]
    cancelled --> [*]
```

A paid invoice is never re-edited; a correction is a credit note.

### Backorder

```mermaid
stateDiagram-v2
    [*] --> open
    open --> consolidated
    open --> fulfilled
    open --> cancelled
    consolidated --> fulfilled
    consolidated --> cancelled
    fulfilled --> [*]
    cancelled --> [*]
```

---

## 4. Modelling decisions worth defending

| Decision | Why |
|---|---|
| **Prices, costs and discount ceilings are snapshotted onto `quotation_lines`** | Master data changes. An approved quotation must remain reproducible, and `allowed_discount_percent` answers "what was the policy when this was approved?" |
| **Approval modelled as request → ordered steps** | Each step is a different person, time and reason. One row per decision is what makes the audit trail complete, and it is what the PRD's B4 step list displays. |
| **`approval_chains` is data, not constants** | PRD A3 requires the chain to be Admin-configurable. Editing policy must not need a redeploy. |
| **Chain and role snapshots on `approval_steps`** | Reconfiguring the chain later must not retroactively change who was supposed to approve a past deal. |
| **`version` column on `quotations`** | Two managers approving simultaneously would otherwise silently last-write-win. |
| **`NULLS NOT DISTINCT` on the stock unique index** | PostgreSQL treats NULLs as distinct by default, so a plain UNIQUE would allow duplicate stock rows whenever `variant_id` is NULL, and the split would under-count available stock. |
| **Enums stored as VARCHAR + CHECK, not native ENUM** | `ALTER TYPE` is painful to reverse in a downgrade; a CHECK constraint is ordinary DDL. The database still rejects invalid values. |
| **`audit_logs` deliberately lacks `updated_at` / `created_by`** | An audit row is never updated, and `user_id` already names the actor. A mutable timestamp on an audit table invites the tampering the table exists to detect. |
| **RESTRICT is the default FK behaviour; CASCADE is the exception** | CASCADE is used only where a child has no independent existence (lines, variants, approval steps, splits). Nothing cascades into quotations, approvals or audit records. |
| **Archival flags on master data, never hard delete** | A two-year-old order must still be reprintable. |
| **Surrogate integer primary keys** | SKUs and quote numbers do change; a changing primary key propagates into every referencing row. Business identifiers keep UNIQUE constraints instead. |
