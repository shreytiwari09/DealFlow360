# Project Context — DealFlow360

## Current Objective
Build the full PRD scope per its own Core/Supporting/Bonus classification (PLAN.md Section 18), sequenced: 🔴 Core workflow fully working first, then 🟡 Supporting, then 🟢 Bonus only if ahead of schedule. Database and business-logic correctness are being treated as first-class judging criteria, not implementation afterthoughts.

**Where we are right now:** Phases 1, 2 and the first half of Phase 3 are complete, plus a
Phase 8 frontend slice brought forward at the user's request. **There is a working, demoable
application** — see `DEMO.md`, the verified script to run in front of an interviewer, which also
lists exactly what is and is not built.

Working end to end: login for all five roles, quotation builder with a live blended risk score,
automatic approval routing (including the sequential two-step Manager→Finance chain), approve /
reject / return-for-revision with a mandatory reason, and a full audit trail. Screens 1-6 of
`FRONTEND.md` are built.

**Next: the rest of Phase 3** — warehouse split and backorders, hybrid billing and proration,
then the customer portal negotiation screen. See "Remaining Work" for the ordered backlog.

**Source-of-truth documents:** `PLAN.md` (process and order), `PROJECT_CONTEXT.md` (this file),
`IMPLEMENTATION_LOG.md` (history), `SECURITY_SPEC.md` (security contract), `FRONTEND.md`
(screens and visual system), `DEMO.md` (what to show, and what not to claim).

## Product Understanding
DealFlow360 is a self-governing B2B sales operations platform — a full quote-to-cash system, not a simple quote-to-invoice tool. Core value: automatic discount discipline (blended risk scoring), real-time multi-warehouse inventory awareness, reconciled one-time + recurring billing on a single order, and a live customer negotiation portal.

**Actual PRD Roles (source of truth — do NOT use the generic roles from the security spec files):**
- **Admin** — full system access, user/role management, platform-wide analytics
- **Sales Manager/Approver** — reviews/approves flagged quotations, configures discount tiers and approval chains, monitors deal health
- **Sales Representative** — builds/edits own quotations, applies discounts within tier limits, tracks approval/fulfillment status
- **Finance/Operations User** — second-level approval for high-risk discounts, manages fulfillment/backorder decisions, reconciles billing/credit notes
- **Customer (Portal User)** — views/negotiates only their own quotations; no internal-screen access

## Current Architecture
- **Backend:** FastAPI (Python 3.12) — async-native, Pydantic v2 validation, auto-generated OpenAPI docs (disabled in production).
- **Frontend:** React 18 + TypeScript, built with Vite. **Design input RECEIVED 2026-09-05** — `FRONTEND.md` is the implementation contract: 18 screens, two shells, design tokens, component inventory, route map and a TBD list. It is the Phase 8 design input PLAN.md Section 13 was waiting for, so the UI hold is lifted. FRONTEND.md is authoritative for screen content and visual chrome; the backend remains authoritative for data shape and for every authorization decision.
- **Database:** PostgreSQL 16 via SQLAlchemy 2 (async, `asyncpg`) + Alembic (versioned migrations — required, not optional, per ERP industry-standard practice).
- **Infra:** Docker Compose (Postgres + backend + frontend). No Redis.
- **NOT using:** the Odoo framework itself (any stack allowed per hackathon rules) — business logic conceptually mirrors Odoo's domain model.

## Repository Structure

```
backend/
  alembic/            Versioned migrations. env.py is async and pulls the DB URL
                      from app settings, never from alembic.ini (no credentials
                      in committed config).
                      versions/809cac63fb15 - the whole initial schema.
  app/
    main.py           FastAPI app: lifespan, CORS allowlist, exception handlers,
                      v1 router mounted at /api/v1.
    core/
      config.py       Pydantic Settings. POSTGRES_PASSWORD and JWT_SECRET_KEY
                      are REQUIRED (no defaults) so a placeholder cannot ship.
      errors.py       Global handlers: generic client messages + correlation id,
                      full detail logged server-side only.
      logging.py      Logging setup.
      security.py     Argon2id password hashing. JWT joins it at login.
    db/
      base.py         DeclarativeBase + metadata naming convention + TimestampMixin.
      session.py      Async engine, bounded pool, get_session() with rollback.
    models/           The full data model, 30 tables. enums.py holds every
                      enumeration; the rest are grouped by domain (rbac,
                      customer, catalog, policy, quotation, approval,
                      inventory, billing, upsell, dealhealth, audit).
                      Every model MUST be imported in models/__init__.py or
                      Alembic autogenerate silently omits its table.
    schemas/          Pydantic response DTOs (health.py only so far).
    services/         state_machine.py - transition tables for all six
                      lifecycle entities, plus assert_transition().
                      risk.py - the blended risk engine and approval router.
                      Both pure: no DB, no I/O, no ORM objects.
    seed.py           Idempotent demo/dev seed. `python -m app.seed`.
    api/
      deps.py         SessionDep. Auth/permission dependencies land here in Phase 6.
      v1/router.py    Aggregate router; feature routers registered here.
      v1/endpoints/   health.py only so far.
  tests/              test_health.py (endpoints), test_state_machines.py and
                      test_risk_engine.py (pure), test_db_constraints.py and
                      test_seed_data.py (real PostgreSQL, each test rolled
                      back). test_seed_data.py REQUIRES the seed to have run.
frontend/
  src/App.tsx         Unstyled Phase 1 placeholder — replace entirely at Phase 8.
  src/lib/api.ts      Thin fetch client; base URL from VITE_API_BASE_URL.
docs/erd.md           ERD + architecture diagram + state machines.
                      Doubles as the hackathon architecture deliverable.
                      KEEP CURRENT when the schema changes.
```

## Core Data Model (implemented in Phase 2 — diagrammed in docs/erd.md)

**Status: implemented and under migration control.** 30 tables, 70 foreign keys, migration
`809cac63fb15`. Diagrammed in `docs/erd.md`. The migration has been verified to apply from
empty, downgrade fully back to empty, and produce an *empty* autogenerate diff afterwards
(no drift between models and database).

**Entities:** users, customers (tier), products (with variants), price_lists, discount_tiers (customer tier × category → max %), approval_chains, quotations, quotation_lines, warehouses, stock_levels, fulfillment_splits, backorders, subscription_plans, billing_schedules, proration_records, upsell_rules, deal_health_snapshots, approval_logs (audit trail).

**Standards applied to every table:**
- Audit columns: `created_at`, `updated_at`, `created_by` — supplied by `AuditMixin` in `app/db/base.py`. `created_by` uses `use_alter=True` because it forms FK cycles (users→roles→users, users→customers→users) that CREATE TABLE ordering cannot satisfy
- Archival, not hard delete, for master data (products, customers): `is_active` / `archived_at`
- Explicit FK behavior (RESTRICT vs CASCADE) decided per relationship, not left as an ORM default
- Indexes on all foreign keys and frequently filtered columns (customer_id, status, created_at)
- CHECK constraints where meaningful (e.g., discount percentage within valid range)
- A metadata naming convention is already configured, so constraints get stable names and can be altered/dropped by later migrations

**Explicit state machines** — all six enforced in `app/services/state_machine.py`; invalid
transitions raise `InvalidStateTransition`. Full tables and diagrams in `docs/erd.md`.
- Quotation: `draft → pending_approval → approved → rejected / sent → under_negotiation →
  confirmed → fulfilled / cancelled` (**superset of the PLAN.md list — see Known Issues**)
- Approval: `pending → approved / rejected / returned_for_revision` (all terminal)
- Subscription: `active ↔ modified → cancelled`
- Fulfillment: `pending → partially_fulfilled → fulfilled / backordered`
- Backorder: `open → consolidated → fulfilled / cancelled`
- Billing schedule: `scheduled → invoiced → paid / cancelled`

**ERD status:** `docs/erd.md` — current as of migration `809cac63fb15`. All 30 tables are
covered, and all 10 Mermaid diagrams were machine-parsed to confirm they render.

**Schema decisions worth knowing before touching it** (full reasoning in `docs/erd.md`):
- Prices, costs and the applicable discount ceiling are **snapshotted onto `quotation_lines`**
  at quoting time. Master data changes; an approved quotation must stay reproducible, and
  `allowed_discount_percent` is what answers "what was the policy when this was approved?"
- Approvals are **request → ordered steps**, not one flat row, because each step is a
  different person, time and reason.
- `approval_steps.required_role_id` is snapshotted from the chain, so reconfiguring policy
  later cannot retroactively change who was supposed to approve a past deal.
- FK default is **RESTRICT**; CASCADE appears only where a child has no independent existence
  (lines, variants, approval steps, splits, proration records). Nothing cascades into
  quotations, approvals or audit records.
- `stock_levels` uses a **`NULLS NOT DISTINCT`** unique index. Without it PostgreSQL would
  allow duplicate stock rows whenever `variant_id` is NULL, and the warehouse split would
  under-count available stock.
- `audit_logs` deliberately has no `updated_at`/`created_by` — an audit row is never updated,
  and `user_id` already names the actor.

## Locked Business Rules

These were ambiguous in the PRD and were explicitly confirmed by the user on 2026-09-05
(PLAN.md Section 0.6). **They are locked. Do not redefine them in a later session** — if
they need to change, change them here first and record it in IMPLEMENTATION_LOG.md.

### 1. Blended Discount Risk Score — LOCKED

Per quotation line `i`:

```
ceiling_i         = max allowed discount %, from discount_tiers,
                    keyed by (customer_tier x product_category)
given_i           = discount % actually applied to the line
line_excess_i     = max(0, given_i - ceiling_i)       # in percentage POINTS
line_value_i      = unit_list_price_i x quantity_i    # PRE-discount list value
```

```
                     SUM( line_excess_i x line_value_i )
BLENDED_RISK_SCORE = ------------------------------------
                          total_order_value
```

where `total_order_value = SUM(line_value_i)`.

Units: percentage points. Read it as **"the value-weighted average number of points of
discount given beyond policy, across the order."**

It is algebraically identical to:

```
                     total currency discounted beyond policy
BLENDED_RISK_SCORE = --------------------------------------- x 100
                            total order list value
```

Both readings are worth knowing for the viva — the first explains *why* it is called
blended, the second explains *what it costs the company*.

**Worked check against the PRD's own example (PRD Section 10):**

| Line | List value | Given | Ceiling | Excess |
|---|---|---|---|---|
| Laptop (Hardware) | 100,000 | 12% | 15% | 0 |
| Setup Service (Service) | 20,000 | 18% | 10% | 8 |

`score = (0 x 100000 + 8 x 20000) / 120000 = 1.33` → greater than 0 → routed to Sales
Manager. The PRD requires this quote to be flagged, and it is.

**Worked check against the PRD's "many small violations" case:** three lines of equal
value, 2 / 3 / 2 points over → `score = 2.33` → routed to Sales Manager. No single line
looks alarming, but the order is still caught.

**Useful property:** every `line_value_i` is positive, so `score > 0` if and only if at
least one line exceeds its own ceiling. "Any line over its ceiling must be flagged" is
therefore not a separate gate bolted onto the formula — it falls out of the formula. Do
not write a redundant second check for *whether approval is required*. (This is distinct
from the single-line Finance gate in #2, which is a genuine additional rule.)

**Implementation notes:**
- Compute with `Decimal`, never `float`. Store as `NUMERIC` in Postgres.
- Persist the score on the quotation **and** the per-line excess breakdown, so an approver
  can see *why* a quote scored what it did rather than just seeing a number.
- Recompute on every line change and on every customer-portal counter-offer — a
  counter-offer that pushes the score into a higher band must re-enter approval
  automatically (PRD B8).

### 2. Approval Routing — LOCKED (as configurable data, not constants)

Two things decide routing: the blended score band, and a single-line escalation gate.

**(a) Single-line Finance gate — overrides the score band.**

```
if max(line_excess_i) > 15:   ->  Manager + Finance, regardless of blended_score
```

Any one line more than 15 points over its own limit forces Finance escalation even when
the blended score is low. This is what stops a severely-discounted small line from being
diluted into insignificance by a large, well-behaved order — the exact blind spot a
value-weighted average has.

**(b) Score bands — live in an `approval_chains` table**, seeded with the values below and
editable by an Admin at runtime. This is deliberate: PRD section A3 ("Configure approval
chain") explicitly asks for it, it is how real ERP systems handle policy that changes over
time, and it strengthens both the data-model judging criterion and the viva answer.
**Do not reintroduce these numbers as constants in application code.**

| Score band | Required approvals |
|---|---|
| `score = 0` | None — straight to fulfillment |
| `0 < score < 25` | Sales Manager |
| `score >= 25` | Sales Manager (step 1), then Finance (step 2) |

**Resolution order:**

```
if score == 0:                      no approval
elif max(line_excess_i) > 15:       Manager -> Finance     # gate (a) wins
elif score >= 25:                   Manager -> Finance
else:                               Manager
```

> ### FINDING (2026-09-05): the `>= 25` band is unreachable, so the gate is the
> only Finance trigger
>
> The blended score is a value-**weighted mean** of the per-line excesses, and a
> weighted mean can never exceed its largest input. Therefore
> `score <= max_line_excess`, always.
>
> It follows that `score >= 25` implies `max_line_excess >= 25`, which is well over
> the gate's 15, so **the gate has already fired before the band is ever consulted.**
> The `>= 25` rows in `approval_chains` are harmless belt-and-braces but they never
> independently decide anything.
>
> This is not a bug — routing is correct, and both demo paths work — but the band is
> doing no work. **Options if you want it to:** lower the band to something below 15
> (e.g. `>= 10`), so a broad pattern of moderate breaches escalates to Finance even
> when no single line is severe; or leave it and treat the single-line gate as the
> sole Finance trigger. It is seed data either way — a one-row change.
>
> Encoded as `test_finance_band_is_unreachable_without_the_line_gate_firing_first`
> in `tests/test_risk_engine.py`. If the band is ever retuned below 15, that test
> fails, and the failure is the signal.

> **Note on demo-ability.** A blended score of 25 is a very large breach — roughly a 40%
> discount order-wide against a 15% ceiling — so band (b) alone would almost never fire,
> and PLAN.md Section 16 Flow 1 wants the two-step chain shown live. The single-line gate
> in (a) fixes this: one line at, say, 35% against a 15% ceiling is 20 points over, which
> escalates to Finance on its own. Use that as the demo path. Both numbers remain easy to
> retune — the band is seed data, and the gate is a single named constant.

### 3. Subscription Proration — LOCKED

Daily basis on exact remaining days, rounded **half-up to 2 decimal places**.

```
cycle_days     = cycle_end - cycle_start
remaining_days = cycle_end - change_date

credit    = old_amount x (remaining_days / cycle_days)
charge    = new_amount x (remaining_days / cycle_days)
proration = ROUND_HALF_UP(charge - credit, 2)
```

Worked example — 1200/month upgraded to 1800/month on day 10 of a 30-day cycle:

```
remaining = 20/30
credit    = 1200 x 0.666... =  800.04
charge    = 1800 x 0.666... = 1200.06
proration =                     400.02
```

**Implementation notes:**
- Use `decimal.Decimal` with an explicit `ROUND_HALF_UP` quantize. Python's built-in
  `round()` is banker's rounding and produces different results — do not use it.
- Store `cycle_start`, `cycle_end`, `change_date`, `old_amount`, `new_amount` and the
  computed `proration` in `proration_records`. Storing only the result makes a billing
  dispute unanswerable.
- A downgrade yields a negative proration, which becomes the credit note PRD B7 requires.

### 4. Order-Level Discount — LOCKED

PRD B3 offers "line level or order level discounts", but an order-level discount has no
per-line ceiling of its own to breach. Confirmed resolution: **an order-level discount is
distributed across the lines, not scored separately.**

Applying `X%` at order level writes `X%` into every line's `discount_percent`. Because each
line then carries the same percentage, the discount *amount* is automatically proportional to
line value — "uniform percentage" and "pro-rata by value" are the same operation here. The
risk formula in #1 is unchanged.

**Applying an order-level discount OVERWRITES existing per-line discounts.** There is exactly
one discount number per line, always; the rep may re-adjust individual lines afterwards.
Stacking was rejected: it makes "what discount is this line actually at" ambiguous for both
the risk score and the audit trail, and edit history is already covered by `audit_logs`, so
stacking buys no traceability it does not already have.

> **Phase 3/4 builder requirement:** when an order-level discount is about to overwrite
> manually-set line discounts, the builder must warn the user before applying. Cheap to do and
> it stops the overwrite from being a silent surprise.

**Why distribution and not a separate order-level check against the tier cap:** the
alternative reopens the precise loophole the blended score exists to close. A Gold customer
with a 12% order discount passes a 15% tier cap while the thin-margin Services line sits
2 points over its own 10% ceiling and nobody ever sees it — worse than the naive case,
because it bypasses line limits entirely.

Worked check — Gold customer, Hardware ceiling 15, Services ceiling 10, 12% at order level:

| Line | List value | Applied | Ceiling | Excess |
|---|---|---|---|---|
| Laptop (Hardware) | 100,000 | 12% | 15% | 0 |
| Setup Service (Service) | 20,000 | 12% | 10% | 2 |

`score = (0 × 100000 + 2 × 20000) / 120000 = 0.33` → greater than 0 → Sales Manager. The
Services breach is still caught.

### 5. Account Creation — LOCKED

**Public signup exists and always creates a Sales Rep.** `POST /api/v1/auth/signup` assigns
`sales_rep` unconditionally and **never reads a role from the request body**. Any `role`,
`role_id`, `customer_id` or privilege field in the payload is ignored, not rejected — this is
SECURITY_SPEC.md Section 8's mass-assignment case implemented literally ("a profile update
must not silently allow `{"role": "Admin"}`").

Role changes go through `PATCH /api/v1/admin/users/{id}/role`, which requires the
`user.manage` permission and writes `ROLE_CHANGED` to `audit_logs`. That endpoint is not extra
scope — Admin's "user/role management" duty in the PRD role list requires it regardless, so
signup reuses machinery already being built.

This satisfies PRD A1 ("Internal users can sign up and log in") and PRD Section 5's opening
step ("Sales rep signs up (first time) or logs in") literally, with no privilege-escalation
path.

**Consequence worth knowing — customer portal accounts are NOT self-service.** A portal user
needs `users.customer_id` pointing at a `customers` row, and signup cannot set that (it
ignores client-supplied `customer_id` by the rule above). Portal accounts are therefore
created by an Admin. This is the correct outcome: self-signup must never be able to attach
itself to an existing customer's quotations.

> **Documented limitation, deliberately accepted for the hackathon.** Unrestricted public
> signup means anyone can obtain a `sales_rep` account and reach the internal workspace — an
> empty one (they own no quotations, and ownership checks are enforced server-side), but they
> would still see the product catalogue. Production would gate this behind an email-domain
> allowlist or admin activation. Recorded here so it is a known trade-off rather than a hole,
> and it belongs in the "what we would build next" deliverable.

### 6. Discount Ceiling Matrix — LOCKED (seed data)

`discount_tiers` is seeded with the full (customer tier × product category) grid below.
Graduated by margin: Hardware sits at the tier cap, Services is stricter, Subscriptions
strictest.

| Ceiling % | Bronze | Silver | Gold |
|---|---|---|---|
| **Hardware** | 5 | 10 | 15 |
| **Services** | 3 | 7 | 10 |
| **Subscriptions** | 2 | 5 | 8 |

Chosen because it reproduces the PRD's own worked example exactly (Gold + Hardware = 15,
Gold + Services = 10, per PRD Section 10) **and** makes "category ceilings differ" visible
across two rows rather than one. That matters for the viva: when a judge asks why the score is
not simply a per-order cap, a gradient demonstrates the answer where a single exception only
hints at it.

Both demo paths are reachable from this one seed:
- **Manager only** — Laptop at 12% (within 15) plus Setup Service at 18% (8 points over 10).
  The PRD's example verbatim.
- **Manager then Finance** — one Hardware line at 35% is 20 points over its 15% ceiling, which
  trips the single-line gate in #2 (`> 15`) regardless of the blended score.

These are rows, not constants: an Admin can retune any cell at runtime (PRD A3).

### 7. Fulfillment Trigger Point and Stock Reservation Timing — LOCKED

**Trigger: a warehouse split can only be generated once a quotation reaches `CONFIRMED`
status.** The PRD contains two slightly different sentences on when fulfillment starts —
Section 5's overview says "once approved... the system suggests a warehouse fulfillment
split", while the Complete Flow section says "once confirmed, the order proceeds to
fulfillment and billing." These read as in tension. Resolved in favour of `CONFIRMED`,
because that is what the Phase 2 state machine was actually built around: `CONFIRMED` is
the sole legal predecessor of `FULFILLED` (`APPROVED → CONFIRMED → FULFILLED` and
`SENT → CONFIRMED → FULFILLED` are the only paths there), so treating `APPROVED` as the
trigger would mean generating a fulfillment for a quotation with no legal route to ever
finish one.

**Consequence:** since the customer portal negotiation screen (backlog item 2, not yet
built) is what would normally call this transition, a small internal stand-in exists —
`POST /quotations/{id}/confirm` — moving `approved`/`sent`/`under_negotiation` →
`confirmed`. Deliberately **not** restricted to the owning rep: "the customer confirmed on
a call" is not something only the original rep witnessed. **This endpoint is temporary**
and should be retired or restricted to Admin once the real portal action exists.

**Reservation happens at generation, not at "accept".** `SELECT ... FOR UPDATE` locks and
reserves stock (`quantity_reserved += allocation`) the moment a split is *computed*, inside
the same transaction. A design that reserved only on accept would leave a window between
"here is what we can offer" and "we actually hold it," during which a second confirmation
could be offered the same nominally-available units. "Accept" is therefore a pure status
transition — no stock movement — and "Manual Override" releases the old reservation and
re-reserves the new one atomically within one transaction, never leaving stock momentarily
un-reserved where a concurrent reader could see it.

**Consolidating a backorder is a manual action, not yet the automatic prompt PRD B6
describes** ("a prompt appears automatically" once stock arrives). The manual endpoint
(`POST .../backorders/{id}/consolidate`) is what that prompt would call; nothing currently
watches for restocks and surfaces the prompt unprompted — that needs a background job,
tracked in Known Issues.

## Core Workflows
1. Rep builds quotation → adds lines → applies discounts (line-level, or order-level distributed onto every line — see Locked Business Rules #4)
2. Blended risk score computed live across all lines (**formula locked — see Locked Business Rules #1**)
3. Threshold exceeded → auto-routes to Manager (and Finance on the score band or the single-line gate — see Locked Business Rules #2)
4. Approved → stock deducted/split across warehouses; backorder created if insufficient
5. Subscription lines get billing schedule + proration on mid-cycle change (**rule locked — see Locked Business Rules #3**)
6. Customer negotiates via portal → counter-offer may re-trigger step 3 automatically
7. Deal health dashboard surfaces stalled/anomalous deals from the above activity

## Important APIs

Base prefix: `/api/v1`. Implemented so far:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Liveness. Does not touch the database. |
| GET | `/api/v1/health/ready` | Readiness. Returns 503 (not 500) when the DB is unreachable, so "not ready yet" is distinguishable from "broken". |

Feature routers are registered in `app/api/v1/router.py` as they are built. No business
endpoints exist yet — Phase 2 delivered the data model, not the API surface.

## Authentication & Authorization
**Reference:** SECURITY_SPEC.md is authoritative for security mechanics — it already uses the correct PRD roles directly, no remapping needed.

**Status: not implemented yet (Phase 6).** What is already in place from Phase 1:
- CORS is an explicit allowlist from `CORS_ORIGINS`, never wildcard-with-credentials (verified: a disallowed origin receives no `access-control-allow-origin` header)
- Error responses carry generic messages plus a correlation id; stack traces, SQL, and DB details are logged server-side only (verified by test)
- `POSTGRES_PASSWORD` / `JWT_SECRET_KEY` are required env vars with no in-code defaults
- OpenAPI docs are served in development but disabled in production
- Backend container runs as a non-root user; Postgres port is bound to `127.0.0.1` only
- `app/api/deps.py` is the single intended home for auth/permission dependencies, so authorization logic cannot get duplicated across routers

Still to do in Phase 6:
- Permission-based authorization (e.g., `deal.create`, `deal.approve_manager`, `deal.approve_finance`, `deal.update_own`, `portal.own_quote.view`, `portal.own_quote.negotiate`) — not hardcoded role checks
- Password hashing via Argon2/bcrypt
- JWT: short-lived access token + refresh-token rotation, algorithm explicitly whitelisted, no sensitive data in payload, `exp`/`iss`/`aud` validated
- **Resource-ownership checks** — Rep can only edit own quotations; Customer can only view own quotation (IDOR prevention)
- Rate limiting on login; generic auth failure messages (no user enumeration)
- All approval/rejection/edit actions logged (user, timestamp, reason) — both a security and a PRD-explicit requirement

**JWT security checklist:** see SECURITY_SPEC.md Section 11. **Audited 2026-09-06** (see
IMPLEMENTATION_LOG.md that date for the item-by-item pass): 13 of 14 items verified directly
against the code, not assumed. The one partial: login and refresh are rate-limited; password
reset and MFA are not built at all (outside PRD scope), so there is nothing there yet to
rate-limit — not a violation, but recorded rather than silently checked off.

## Redis / Caching
Not used. Considered and rejected at the Phase 1 checkpoint (see decisions table). Only added if a Section 0.5 technology-evaluation checkpoint surfaces a real, measured bottleneck — document justification here if that happens.

## Background Jobs
Simple async/scheduled task (no queue infra) for stalled-deal detection on the dashboard. Not yet implemented.

## Important Technical Decisions

| Decision | Reason | Alternative Considered | Trade-off |
|---|---|---|---|
| FastAPI over Django/Express/Flask | Async-native, Pydantic validation, team's Python strength | Django (heavier, sync-default), Express (forces weaker JS onto backend), Flask (no built-in validation/async) | Less batteries-included than Django |
| React over Vue/Next.js | Team's existing hands-on experience | Next.js (merges backend into JS) | Requires explicit CORS setup |
| PostgreSQL over MongoDB/MySQL/Firebase | Strict relational integrity needed for quote→discount→approval→stock chains | MongoDB, Firebase | None significant for our data shape |
| Alembic migrations (not ad-hoc schema) | ERP-standard practice; schema will evolve during build | `create_all()` only | Slightly more setup upfront, pays off immediately when schema changes |
| No Redis (default) | No real bottleneck at demo scale | N/A | Revisit only if a Section 0.5 checkpoint finds a real one |
| No AI/ML for upsell | PRD defines it as rule-based (co-purchase pairing table); ML adds non-determinism risk in live demo | Real ML recommendation model | Less "smart," fully explainable and reliable |
| Greedy warehouse-fill (not optimizer) | Satisfies PRD requirement without algorithm-heavy build time | Full shipment-cost optimization | Not globally optimal, but explainable and correct |
| Permission-based RBAC (not hardcoded role checks) | From security spec; scales better as roles/permissions evolve | Hardcoded `if role == "manager"` checks | Slightly more setup, avoids scattered role logic |
| **Async SQLAlchemy 2 + `asyncpg`** (Phase 1 checkpoint) | FastAPI is async; mixing a sync driver into async endpoints blocks the event loop, which is the classic silent-performance footgun. Row locking (`SELECT … FOR UPDATE`) for stock deduction and optimistic locking on approvals both work identically in async | Sync SQLAlchemy + `psycopg2` with `def` endpoints running in a threadpool (simpler, fewer sharp edges) | Async requires `greenlet`, an async Alembic `env.py`, and care that no blocking call sneaks into a request path. Accepted because the two hardest correctness requirements (stock locking, concurrent approvals) are unaffected either way |
| **Vite as the React toolchain** (Phase 1 checkpoint) | Current standard for a React SPA; instant dev server and HMR matter over a 24h build | Create React App (deprecated), Next.js (already rejected — merges backend into JS) | Needs `usePolling` for HMR through a Windows bind mount (configured) |
| **Python 3.12 in the container** (not 3.13/3.14) | Every dependency ships prebuilt wheels for 3.12; avoids a compiler stall mid-hackathon. Host has 3.14, which is why the container pin is explicit | Match the host's 3.14 | Slightly behind latest; irrelevant here |
| **Enums as VARCHAR + named CHECK, not native PG ENUM** (Phase 2 checkpoint) | `ALTER TYPE ... ADD VALUE` cannot always run in a transaction and is awkward to reverse in a downgrade. PLAN.md Section 7 expects the schema to keep evolving, and a CHECK constraint is ordinary DDL that Alembic can drop and recreate | Native PostgreSQL ENUM types | Slightly less "proper" typing at the database level; the database still rejects invalid values, so nothing is lost in enforcement |
| **Snapshot pricing and discount ceilings onto quotation lines** (Phase 2) | An approved quotation must remain reproducible after master data changes, and an auditor must be able to see what the policy was at approval time | Join to live master data on read | Denormalised data that must be written correctly once; the alternative silently produces numbers that disagree with what the customer signed |
| **Optimistic locking (`version`) on quotations** (Phase 2) | Two managers approving the same quote concurrently would otherwise last-write-win silently. SQLAlchemy raises `StaleDataError` instead | Pessimistic `SELECT … FOR UPDATE` on every read | Callers must handle a conflict error; far cheaper than holding row locks across a user's think-time |
| **argon2-cffi for password hashing** (Phase 3 checkpoint) | SECURITY_SPEC names Argon2id first; work-factor parameters live inside the hash string, so raising cost later needs no migration - just rehash-on-login | bcrypt directly (silently truncates at 72 bytes); passlib (unmaintained since 2020, breaks on bcrypt 4.x) | ~50-100ms per hash, which is the point |
| **PyJWT for tokens** (Phase 3 checkpoint) | `algorithms=[...]` is a REQUIRED argument to `decode()`, so the allowlist SECURITY_SPEC Section 9 demands cannot be forgotten and `alg:none` is structurally impossible | python-jose (slower releases, algorithm-confusion CVE history - the exact attack the spec lists) | None material; PyJWT does less, and less is what we need |
| **slowapi for login rate limiting** (Phase 3 checkpoint) | A hand-rolled dict-pruned-on-read limiter has a genuine read-then-write race under async, and nobody writes tests for a rate limiter at 2am. Defaults to in-memory, so "no Redis" is the default path, not a workaround; the backend swaps later without touching call sites | Hand-rolled sliding window (race-prone); deferring to Phase 6 (rejected - it is on the pre-submission checklist and hardening phases are exactly what gets squeezed) | Two small dependencies |
| **Secrets have no in-code defaults** | `POSTGRES_PASSWORD` / `JWT_SECRET_KEY` are required settings, so the app fails loudly rather than silently running on a placeholder | Defaults for developer convenience | A missing `.env` is now a startup error — which is the intended behaviour |

### Section 0.5 Technology Evaluation Checkpoints (log)

**Phase 1 — Foundation.** *Outcome: no new technology adopted.*
1. Anything the current stack cannot cleanly satisfy? **No.** Phase 1 is scaffolding; FastAPI + React + PostgreSQL + Docker Compose covers it, and Alembic is already mandated by PLAN.md Section 6 rather than being a new choice.
2. Candidates genuinely considered:
   - **`uv`** (Astral) instead of `pip` + `requirements.txt`. *Problem it would solve:* Docker rebuild latency during a 24h build. *Why the current stack is enough:* pip plus Docker layer caching keeps rebuilds acceptable, and dependencies change rarely after Phase 2. *What breaks without it:* nothing — only slower rebuilds. **Rejected**; revisit only if rebuild time becomes a felt cost.
   - **A Redis-backed rate limiter** for the login endpoint required by SECURITY_SPEC.md Section 5. *Why deferred:* login does not exist until Phase 3/6, and at single-instance demo scale an in-process limiter is sufficient and has no extra failure mode. **Deferred to the Phase 6 checkpoint**, where it will be evaluated against a real endpoint.
3. Two in-stack architectural decisions were made and recorded in the table above (async SQLAlchemy, Vite) — these are choices within the sanctioned stack, not new dependencies.

**Phase 2 — Core Data Model.** *Outcome: no new technology adopted.*
1. Anything the current stack cannot cleanly satisfy? **No.** SQLAlchemy 2 plus Alembic covers
   the whole model, including the CHECK constraints, partial/`NULLS NOT DISTINCT` indexes and
   optimistic locking the phase needed.
2. Candidates genuinely considered:
   - **`eralchemy2` / `sqlalchemy-schemadisplay`** to generate the ERD from metadata.
     *Problem it would solve:* keeping the diagram in sync with the schema automatically.
     *Why rejected:* both need Graphviz as a system dependency in the image, and the generated
     output is a raw box-and-line dump with no room for the "why" annotations that actually
     earn marks. Hand-written Mermaid renders natively on GitHub, is reviewable in a diff, and
     the sync risk is handled instead by a check that every table appears in the doc.
   - **`python-statemachine`** for the six lifecycle machines. *Problem it would solve:*
     declarative transitions with callbacks. *Why rejected:* the transition tables are ~60
     lines of plain dicts, dependency-free, trivially unit-testable, and far easier to explain
     in a viva than a DSL. Section 20 applies.
3. One in-stack decision recorded in the table above: enums as VARCHAR + CHECK rather than
   native PostgreSQL ENUM.

## Known Constraints
- 3-person team, 24-hour hackathon
- Team strengths: FastAPI, React (used together before); some DevOps
- Team weaknesses: JS depth, heavy full-stack polish
- No prior Odoo experience (not required — any stack allowed)
- This is treated as an ERP-grade build — data model and business logic correctness are weighted above UI polish

## Known Issues

**Resolved 2026-09-05** — blended risk score formula, the single-line Finance gate,
approval routing thresholds, and proration basis/rounding are all confirmed and written up
under "Locked Business Rules" above. **Phase 2 is no longer blocked.**

**Confirmed 2026-09-05 — the quotation state-machine superset stands.** PLAN.md Section 7
specifies six states; the implementation has nine. `sent` and `under_negotiation` come from
PRD B8 (portal status display, and the state the automatic re-approval trigger fires from),
`rejected` from PRD A7's reporting filter. PLAN.md Section 1 gives the PRD precedence on
*what* to build, so these are direct implementations of named requirements, not scope creep.

Reverting would also be *worse* data modelling, not stricter plan-adherence: a real quotation
state would become a derived flag, and rejection reporting would depend on joining
`approval_requests` and picking the latest row per quotation. Recorded here so a later session
does not "fix" the discrepancy against PLAN.

**From FRONTEND.md Section 9 — 18 frontend TBDs carried here per its own instruction.** Not
repeated in full; `FRONTEND.md` Section 9 is the list. The ones that will bite soonest, in
build order: the discount input control on Screen 4 (#4), the dismiss affordance for upsell
suggestions (#5), the "skipped" visual for the Finance step in the approval stepper (#6), and
per-role scoping of the dashboard and list screens (#11). Defaults are proposed inline in
FRONTEND.md for each; none is to be resolved silently.

**Reconciled by FRONTEND.md, no longer open:** the quotation `negotiation` state is confirmed
as a real backend state (FRONTEND.md Section 9 item 3), which matches the superset state
machine already implemented — `under_negotiation`. FRONTEND.md Section 18's note that the risk
formula is "not yet locked" is stale and has been annotated in place; the formula, gate, bands
and ceiling matrix are all locked here.

**Resolved 2026-09-06 — the warehouse tie-break assumption is now implemented, not just
proposed.** `compute_split()` in `app/services/fulfillment.py` orders candidates by lowest
`shipping_cost_weight`, then highest available stock, then lowest `warehouse_id`. Verified by
dedicated unit tests for each tiebreak level independently, and confirmed deterministic against
real seeded data across repeated runs. No longer "proceeding on an assumption" — it is built,
tested, and documented in Locked Business Rules #7.

**Still open — needed before the phase that depends on each (PLAN.md Section 0.6):**
- **Deal health anomaly thresholds not yet defined** — blocks the Phase 5 dashboard.
  Specifically: how many days of inactivity makes a quote "stalled", and how far above a
  rep's own historical average a discount must sit to count as an anomaly. Neither affects
  the Phase 2 schema (both are configuration rows), so this can wait.
- **Customer portal login method** — PRD A1 offers "magic link, or email and password".
  **Proceeding with email + password**, consistent with Locked Business Rules #5 (portal
  accounts are Admin-created) and avoiding token issuance and delivery. Magic link remains
  possible later; no schema change was made for or against it.
- **Demo currency** — the schema defaults `currency` to `INR` on customers, price lists and
  quotations. Say if the demo should present something else; it is a seed-data change.

**Missing source documents:**
- `DealFlow360_PRD_Merged.md` is named by PLAN.md as authoritative for feature scope, but is not present in the repository. `DealFlow360.pdf` was supplied in conversation and is the original source; it has not been committed. Ask the user to add both to `docs/`.

**Other:**
- **Frontend design system not yet provided** — waiting on the Excalidraw mockup / markdown resource before any UI work begins. Mockup link from the PRD: `https://app.excalidraw.com/l/65VNwvy7c4X/7Fb5SR3WKu2`

## Current Implementation Status

**Phase 0 (Reconnaissance): complete.** Repository was empty apart from a stub README.

**Phase 1 (Foundation): complete and validated.**
- `docker compose up` brings up Postgres + backend + frontend; backend reports healthy
- FastAPI serves `/api/v1/health` and `/api/v1/health/ready`; readiness performs a real `SELECT 1` against Postgres through the async SQLAlchemy engine and returns `{"database":"ok"}`
- Alembic connects, `alembic upgrade head` runs, `alembic_version` exists, and `--autogenerate` was proven to work end to end
- 3 backend tests pass; `ruff check` and `ruff format --check` are clean
- Frontend dev server serves, `tsc --noEmit` is clean, and `npm run build` produces a production bundle

**Phase 2 (Core Data Model): complete and validated.**
- 30 tables covering every Core, Supporting and Bonus-if-time PRD feature, under Alembic
  migration control as revision `809cac63fb15`
- Audit columns on every table; archival flags on all master data; explicit FK delete
  behaviour on all 70 foreign keys; CHECK constraints on percentages, quantities, money,
  date ordering and cross-column invariants
- Six state machines enforced in `app/services/state_machine.py`, with invalid transitions
  raising `InvalidStateTransition`
- Migration verified to apply from empty, downgrade fully back to empty, and leave **no
  drift** (a second autogenerate produces an empty migration)
- 69 tests pass: state machine transitions and rejections, transition-table completeness,
  and database constraints proven against real PostgreSQL
- ERD checked in at `docs/erd.md`, all 10 diagrams machine-parsed

**Phase 3 (Core Business Workflow): steps 1-5 and 8 complete.**
- Blended risk engine and approval router in `app/services/risk.py` — pure, `Decimal`, 35 tests
- Idempotent seed data covering RBAC, catalogue, the full ceiling matrix, chains, stock and rules
- Login for all five roles; Argon2id, JWT with an explicit algorithm allowlist, refresh rotation
  with reuse detection, slowapi rate limiting on login and refresh
- Permission-based authorization plus separate resource-ownership checks, all in `api/deps.py`
- Quotation API with a single recalculation writer for totals, margin and risk
- Automatic approval routing including the sequential two-step Manager→Finance chain
- **Warehouse split + backorders** — greedy fill in `app/services/fulfillment.py` (pure, mirrors
  `risk.py`'s shape), reserving stock atomically via `SELECT ... FOR UPDATE` at the moment a
  split is generated, not deferred to "accept". Covers the full PRD B6 surface: auto-suggestion
  on first view, Accept, Manual Override (with release-then-reserve, still atomic), and
  Consolidate Remaining Backorder (manually triggered — see Known Issues for the "automatic"
  half). See Locked Business Rules #7 for the CONFIRMED-status trigger point and the internal
  `POST /quotations/{id}/confirm` stand-in this required.
- Audit trail on every create, edit, submission, approval, rejection, fulfillment action and
  denial
- Not yet: hybrid billing (step 6), portal negotiation (step 7)

**Phase 8 (Frontend): Screens 1-8 built.** Screens 1-6 brought forward at the user's request once
`FRONTEND.md` supplied the design input; Screens 7-8 (Fulfillment List/Detail) followed
immediately once their backend existed. Screens 9-18 appear in the sidebar explicitly disabled
rather than as links to empty pages.

**Verified 2026-09-06:** 145 unit/integration tests (124 + 21 new fulfillment tests) plus 56 + 51
end-to-end API checks all pass, and every flow — including Confirm → auto-generated split →
Accept, Manual Override, and Consolidate-after-restock — was driven through the real UI
headlessly with no runtime errors. `DEMO.md` records the expected numbers for the flows it
covers; the fulfillment flow's numbers are recorded in Locked Business Rules #7 and
IMPLEMENTATION_LOG.md instead, pending a DEMO.md update.

## Remaining Work

Ordered backlog. Everything below already has schema support — the data model was built for the
full PRD in Phase 2, so none of it needs a migration for its core tables.

### Next up — finish Phase 3 (Core)

1. **Hybrid billing + proration** (PRD B7, Screens 9-10, 12-13)
   - Proration is locked (#3): daily basis, `ROUND_HALF_UP` to 2dp, with `Decimal` — never
     Python's built-in `round()`, which is banker's rounding
   - Store every input beside the result in `proration_records`, or a billing dispute is
     unanswerable
   - **Close this gap first:** `quotation_lines` has a CHECK requiring a subscription line to
     carry a plan, but the builder has no plan picker, so subscription products cannot yet be
     added to a quote. See `_default_plan_id` in the quotations endpoint.
   - Tables ready: `subscription_plans`, `subscriptions`, `billing_schedules`,
     `proration_records`, `payments`

2. **Customer portal negotiation** (PRD B8, Screen 11)
   - Needs its own endpoints under `portal.*` permissions — NOT a filtered view of the internal
     list. The portal shell exists and correctly refuses internal screens; only the negotiation
     screen itself is a placeholder
   - A counter-offer breaching a threshold must raise a NEW approval request, which is precisely
     why decided approvals are terminal in the state machine
   - `under_negotiation` and its transitions are already implemented and tested

3. **Upsell panel wired to `upsell_rules`** (PRD B5)
   - 7 rules are seeded. The builder currently shows promoted products as a stand-in; it needs
     the real co-purchase lookup, the margin-delta figure and the `Dismiss` action

### Then Phase 5 (Supporting)

5. Deal health dashboard — **blocked**: anomaly thresholds still undefined (see Known Issues)
6. Reporting with filters + PDF/XLS export — needs a Section 0.5 checkpoint for the export library
7. Admin config screens for discount tiers and approval chains (Screen 18) — the data is already
   configurable at runtime, only the UI is missing
8. Product catalogue (Screens 16-17), manual warehouse override, nudges/escalations

### Deferred deliberately

- **Order-level discount UI** — the endpoint works and is tested; the builder has no button yet,
  and it needs the overwrite warning required by Locked Business Rules #4
- **HttpOnly cookie auth** — the refresh token currently lives in `sessionStorage` (moved off
  `localStorage` after a real cross-tab session bug — see IMPLEMENTATION_LOG.md 2026-09-05).
  SECURITY_SPEC Section 7 prefers cookies and that remains the right end state; it needs CSRF
  handling and a same-site story the split localhost origins do not currently allow
- **Fully-automatic backorder consolidation** — PRD B6's "prompt appears automatically" needs a
  background job watching for restocks. What exists now (`POST
  /fulfillment/{id}/backorders/{id}/consolidate`) is the manual trigger that prompt would call;
  an ops/finance user has to check and click it themselves rather than being notified
- **Restricting public signup** — signup grants an empty internal workspace to anyone. Acceptable
  for a hackathon, wrong for production; belongs in the "what we'd build next" deliverable
- Bonus scope (multi-currency, multi-company) — untouched, correctly

## Do Not Change / Do Not Break
- **Blended risk score formula — now locked.** See Locked Business Rules #1. Do not let a
  later session silently redefine it, and do not add a redundant "any line over ceiling"
  check to decide *whether* approval is needed — that already falls out of the formula
- **The single-line Finance gate (`max(line_excess) > 15`) is a real, separate rule.** It
  overrides the score band and must not be folded into the blended score
- **Approval score bands live in `approval_chains` rows, not in code.** Do not hardcode them
- **No endpoint may read `role`, `role_id`, `owner_id` or `customer_id` from a client
  payload.** Signup ignores them and always assigns `sales_rep`; everything else derives them
  from authenticated server-side context — see Locked Business Rules #5
- **An order-level discount is distributed onto the lines and overwrites them, never scored
  separately and never stacked.** Scoring it against the tier cap alone reopens the loophole
  the blended score exists to close
- **Proration uses `Decimal` + explicit `ROUND_HALF_UP`.** Never `float`, never Python's
  built-in `round()`, which is banker's rounding and gives different answers
- **Stock is reserved at fulfillment GENERATION, not at accept.** See Locked Business Rules
  #7. Moving the `quantity_reserved` write to "accept" would reopen the double-sell window
  the `SELECT ... FOR UPDATE` locking exists to close
- **Any ORM object returned from a service function that was populated via bare
  `session.add(...)` (not `parent.children.append(...)`) must have its collection
  relationships explicitly `session.refresh(...)`'d before return.** This is not
  hypothetical — it caused two real bugs in this codebase (`auth.py`'s `_USER_LOADS`, and
  `generate_fulfillment`'s missing refresh, both `MissingGreenlet` under async). The API
  layer papering over it by re-querying afterward is not a substitute for fixing it at the
  source; a future caller that doesn't happen to re-query will hit it again
- Server-side role + resource-ownership enforcement — never move checks to frontend-only
- State machine transition rules — do not allow invalid transitions to pass silently
- `POSTGRES_PASSWORD` / `JWT_SECRET_KEY` must stay required settings with no in-code default
- Every new model must be imported in `app/models/__init__.py` — otherwise Alembic autogenerate silently omits its table
- The metadata naming convention in `app/db/base.py` must not be changed after the first migration exists, or constraint names will drift from what is already in the database

## Demo-Critical Features
1. Quotation builder with live margin/risk updates
2. Blended discount risk score triggering auto-approval routing
3. Multi-warehouse split + backorder handling
4. Hybrid billing (one-time + subscription) with proration
5. Customer portal negotiation with auto re-approval

## Viva-Critical Decisions
See "Important Technical Decisions" table above. Additionally be ready to explain:
- **Blended risk score logic:** why per-line limits alone aren't enough; exact aggregate formula (once locked)
- **Proration formula:** exact calculation and rounding rule (once locked)
- **State machine design:** why explicit transitions matter for an ERP system (prevents invalid states like a cancelled quotation being re-approved)
- **Concurrency handling:** two managers approving the same quote simultaneously (needs optimistic locking / version column)
- **RBAC model:** why permission-based over hardcoded role checks; how resource ownership is verified server-side
- **Async vs sync database access:** why an async driver was chosen, and why it does not change how stock-deduction locking works
- **Any technology adopted via a Section 0.5 checkpoint** — the specific problem it solved and the alternative considered
