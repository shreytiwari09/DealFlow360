# Project Context — DealFlow360

## Current Objective
Build the full PRD scope per its own Core/Supporting/Bonus classification (PLAN.md Section 18), sequenced: 🔴 Core workflow fully working first, then 🟡 Supporting, then 🟢 Bonus only if ahead of schedule. Database and business-logic correctness are being treated as first-class judging criteria, not implementation afterthoughts.

**Where we are right now:** Phases 1, 2, 3 and 5 are all complete, plus a Phase 8 frontend
slice brought forward at the user's request. **Every Core (🔴) and Supporting (🟡) item in
PLAN.md Section 18's classification is done.** There is a working, demoable application — see
`DEMO.md`, the verified script to run in front of an interviewer (its script currently covers
the two original approval flows plus fulfillment, billing and portal negotiation; the Phase 5
screens are real and tested but not yet added to that script — see its own changelog note).

Working end to end: login for all five roles, quotation builder with a live blended risk score,
order-level and per-line discounts, a subscription-plan picker for hybrid lines, and a real
Upsell & Cross-Sell panel; automatic approval routing (including the sequential two-step
Manager→Finance chain); approve / reject / return-for-revision with a mandatory reason; a full
audit trail; multi-warehouse fulfillment with backorders; hybrid billing with daily-basis
mid-cycle proration; a genuinely separate customer portal where a counter-offer that breaches
policy automatically re-enters approval; a deal health dashboard with real stalled/anomaly/
slippage thresholds; filtered reporting with PDF/XLS export; and admin screens for discount
tiers, approval chains and the product catalogue. Screens 1-18 of `FRONTEND.md` each have a
real screen or a deliberate, documented gap (variant/price-list editing — see "Remaining Work").

**Next:** only 🟢 Bonus scope (multi-currency, multi-company — PLAN.md marks these explicitly
optional) and the deliberately-deferred items below remain. See "Remaining Work."

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
- **Database:** PostgreSQL, via SQLAlchemy 2 (async, `asyncpg`) + Alembic (versioned migrations — required, not optional, per ERP industry-standard practice). **Runs natively on the host, not in a container** (changed 2026-09-06 at the user's request — see "Database" below); the app itself has no idea whether Postgres is containerized, since `POSTGRES_HOST`/`PORT` are plain settings.
- **Infra:** Docker Compose for backend + frontend only. No Redis.

### Database

Postgres is installed directly on the development machine (currently PostgreSQL 18 on
Windows), not run as a Docker service. `docker-compose.yml`'s `db` service and `pgdata`
volume were removed entirely; the backend container reaches the host's Postgres via
`POSTGRES_HOST=host.docker.internal`, which Docker Desktop (Windows/Mac) resolves to the
host automatically — no `pg_hba.conf` or `listen_addresses` change was needed, because
Docker Desktop's internal proxy makes a `host.docker.internal` connection appear to
Postgres as a plain loopback (`127.0.0.1`) connection, which the default install already
allows. Verified directly: `docker run --rm postgres:16-alpine psql -h host.docker.internal
...` succeeded against the host's Postgres with `inet_server_addr()` reporting `127.0.0.1`.
A dedicated `dealflow` role (not the `postgres` superuser) owns a dedicated `dealflow360`
database, matching the least-privilege principle the previous Dockerized setup already
followed. Native Linux Docker does not have this proxy behavior and would need an
`extra_hosts: ["host.docker.internal:host-gateway"]` line plus a real `pg_hba.conf`
allowance for the container's bridge subnet — noted in `docker-compose.yml`'s header
comment for whoever hits this next, but not implemented since the dev machine is Windows.

**Trade-off, stated plainly:** the README's "clone and run, nothing else installed"
promise is now weaker — a local Postgres install is a genuine prerequisite, not just
Docker and Git. This was an explicit, deliberate choice at the user's request ("database
should be on there only"), not a silent regression; `README.md`'s setup section documents
the one-time `CREATE ROLE`/`CREATE DATABASE` steps a fresh clone now needs.
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
remaining = 20/30 = 2/3
credit    = 1200 x 2/3 =  800.00
charge    = 1800 x 2/3 = 1200.00
proration =               400.00
```

> **Correction (2026-09-06):** this example previously read 800.04 / 1200.06 / 400.02. Those
> came from hand-rounding 0.666... to "0.6667" before multiplying — an arithmetic slip in the
> example, not a property of the formula. 20/30 reduces to exactly 2/3, and 1200 x 2/3 = 800 with
> nothing left to round away. The formula itself (full-precision division, `ROUND_HALF_UP`
> applied once at the end) was never wrong; only this example's own numbers were. Found while
> writing `test_locked_worked_example_exactly` in `backend/tests/test_billing.py` — see
> `IMPLEMENTATION_LOG.md` 2026-09-06 "Hybrid Billing and Proration." A genuine rounding tie (where
> `ROUND_HALF_UP` actually differs from Python's `round()`) is covered separately by
> `test_rounding_is_half_up_not_bankers_rounding` (17 x 1/8 = 2.125 exactly -> 2.13, not 2.12).

**Implementation notes:**
- Use `decimal.Decimal` with an explicit `ROUND_HALF_UP` quantize. Python's built-in
  `round()` is banker's rounding and produces different results — do not use it.
- Store `cycle_start`, `cycle_end`, `change_date`, `old_amount`, `new_amount` and the
  computed `proration` in `proration_records`. Storing only the result makes a billing
  dispute unanswerable.
- Implemented in `backend/app/services/billing.py`'s `compute_proration()`.
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
`sales_rep` unconditionally. There is **no `role`, `role_id` or `customer_id` field on
`SignupRequest` at all** — SECURITY_SPEC.md Section 8's mass-assignment case ("a profile
update must not silently allow `{"role": "Admin"}`") is enforced structurally, by the schema
having nowhere to smuggle a privilege field through, not by an endpoint that reads and
discards one.

> **Correction (2026-09-06).** This rule was locked and written up during Phase 1, but the
> endpoint implementing it was never actually built — `app/api/v1/endpoints/auth.py` carried a
> docstring claiming the opposite ("deliberately NO signup endpoint"), which was simply wrong,
> not a later, deliberate reversal. Found when the user reported the frontend had no
> registration flow at all. Implemented now: `app/services/auth.py`'s `signup()`, auto-issuing
> a token pair on success so "sign up" and "log in" are one action, matching the PRD's own
> "signs up (first time) or logs in" framing of them as alternatives.

Role changes going through `PATCH /api/v1/admin/users/{id}/role` (requiring `user.manage`,
writing `ROLE_CHANGED` to `audit_logs`) remains the plan but **is still not built** — promoting
a self-registered Sales Rep to another role today means an Admin edits the row directly. Not
in scope for this pass; tracked in Remaining Work.

This satisfies PRD A1 ("Internal users can sign up and log in") and PRD Section 5's opening
step ("Sales rep signs up (first time) or logs in") literally, with no privilege-escalation
path.

**Consequence worth knowing — customer portal accounts are NOT self-service.** A portal user
needs `users.customer_id` pointing at a `customers` row, and signup cannot set that (it
ignores client-supplied `customer_id` by the rule above). Portal accounts are therefore
created by an Admin. This is the correct outcome: self-signup must never be able to attach
itself to an existing customer's quotations.

> **Correction (2026-09-06, part 2).** The paragraph above was right that portal accounts must
> be Admin-created, but until now nothing actually implemented that — there was no endpoint or
> screen for an Admin to create ANY user at all, portal or internal, beyond the seed fixtures
> and the signup path above. Found when the user asked, correctly, "do we need an option to
> create a customer account, and how do real ERPs do this?"
>
> Built as an **invite-based activation flow**, not a direct "Admin sets the password" form —
> the same shape as a password-reset link, and the same reason: nobody but the account's own
> owner should ever handle its password, including the Admin who created the row. An Admin
> calls `POST /api/v1/admin/users/invite` (`user.manage`) with an email, name, role, and — only
> when the role is `customer` — a `customer_id` (`POST /api/v1/admin/customers`, `config.manage`,
> now exists too, since there was previously no way to create a customer either). This creates
> the `users` row with `password_hash = NULL` and `is_active = false` (both now enforced at the
> service layer: `password_hash` is nullable on the column, and `authenticate()` treats a null
> hash exactly like "no such user" — same generic failure, so a pending invitation cannot be
> enumerated by email through the login endpoint) and a `user_invitations` row holding only a
> SHA-256 hash of a one-time token — same pattern as `refresh_tokens.token_hash`. The Admin
> receives the raw activation link back in the response (`/activate/<token>` on the SPA) and
> sends it to the invitee however they already reach them; `GET /api/v1/auth/invitations/{token}`
> (public, generic-failure on a bad/expired/used token) lets the activation page greet them by
> name, and `POST /api/v1/auth/invitations/{token}/accept` sets their password, flips
> `is_active`, and logs them straight in — same "one action, not two" shape as `signup()`.
>
> This also quietly resolves the `PATCH .../role` gap noted just above: an Admin provisioning
> the *right* role directly through this same invite endpoint (Sales Manager, Finance/Ops,
> whatever is actually needed) is the more realistic ERP pattern, not a promotion endpoint
> bolted on after the fact. No email delivery exists in this project (no SMTP/provider
> configured anywhere) — the "send it yourself" copy-link UX is a deliberate, disclosed
> simplification, the same trade-off a Google Doc share link or Slack invite link makes.
> Verified live against the running stack (not just unit-tested): 29 checks covering create
> customer → invite portal user → duplicate-email rejected → mismatched role/customer
> combinations rejected → login blocked before activation → public preview → accept → replay
> rejected → activated login works and is correctly permission-scoped → a non-Admin cannot call
> either endpoint. One real bug caught by that live run and fixed before shipping: the new
> `GET /auth/invitations/{token}` route carried `@limiter.limit(...)` without the `response:
> Response` parameter slowapi requires to attach its rate-limit headers, which 500'd every call
> — the exact failure mode `login()`'s own docstring already warned about for this same library
> quirk.

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

**Consequence:** `POST /quotations/{id}/confirm` moves `approved`/`sent`/`under_negotiation`
→ `confirmed`. It began life as a temporary stand-in for the customer's own action while the
portal did not exist. **Now that the portal is built (see #8), it is restricted to the
`deal.confirm_override` permission (Admin only)** and survives only as the manual override
for "the customer confirmed on a call." The customer's own path is
`POST /portal/quotations/{id}/confirm`.

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

### 8. Customer Portal Negotiation — LOCKED (2026-09-06)

PRD B8 and FRONTEND.md Screen 11 leave three things unspecified. Confirmed with the user
before implementing, per PLAN.md §0.6:

**a) A counter-offer is an order-level discount, and comments are free text.** The wireframe
draws a per-line comment table, but the only quantitative field it gives the customer is a
single `Counter Discount %`. So the counter is applied exactly like the internal order-level
discount (Locked Business Rules #4 — distributed onto every line, overwriting, never scored
separately), and the per-line comments are informational text that never moves a number by
itself. This keeps one and only one code path capable of changing a line's discount.

**b) Negotiation history lives in `audit_logs`, not a new table.** Each `Submit Request`
writes one `AuditLog` row (`action=PORTAL_COUNTER_OFFER`, `reason` carrying the customer's
message and the counter percentage). Screen 11's comment table is rendered from those rows.
Rationale: the constant already existed for exactly this event, the audit trail is already
how every other reason-carrying action in this system is recorded (and how Screen 6 already
renders its history), and a customer-visible message *is* an audit-relevant event — putting
it anywhere else would mean the negotiation record could be edited without leaving a trace.

**c) `Requested Delivery Date` is informational, captured in the comment text.** It gets no
column. The PRD never states that anything downstream reacts to it (fulfillment's
`promised_date` is ops-set, a different thing), so a structured column would imply a
guarantee the system does not make.

**Confirm routing (PRD B8, verbatim):** on `Confirm Quotation`, the current terms are
re-scored. If approval is required, the quotation re-enters the approval flow
(`under_negotiation → pending_approval`) with a **new** approval request — decided approvals
are terminal, which is exactly why this must be a new request, not a reopened one — and the
audit reason records that the origin was a customer counter-offer, so Screen 6 can show it
differently from a first-time submission. If no approval is required, it goes straight to
`confirmed`, which generates billing and unlocks fulfillment (#7).

**d) "Exceeds approval thresholds" means "not already approved at these terms", not merely
"breaches policy".** Read literally, re-scoring on confirm is a trap: a quotation approved at
18% and then sent still scores as breaching, because nothing about it changed — so it would
bounce straight back to the manager who just approved it, and *no quotation that ever needed
an approval could ever be confirmed*. The rule implemented instead: an approval is required
unless an `ApprovalRequest` that reached `APPROVED` for this quotation snapshots **both** the
same `blended_risk_score` and the same `max_line_excess` as the terms now on the table. Any
counter-offer that changes a discount changes at least one of those, so it correctly
re-enters approval. Deliberately strict in one direction: a counter that is still over the
ceiling but *less* over than what was approved (18% → 16% against a 10% ceiling) does not
match and does go back for approval — different terms that still breach policy, and "the
customer talked us down a bit" is not a reason to skip the control. Implemented as
`terms_already_approved()` in `app/services/portal.py`.

**e) `approved` is negotiable, found live — not initially designed for.** The first cut of
`NEGOTIABLE_STATUSES` was `{sent, under_negotiation}`, following PRD B8's own wording literally.
The live-API script immediately showed the actual bug this caused: PRD B3's own flow has no
"send to customer" step after an approval clears — a quotation that needed approval before it
ever reached the customer sits at `approved`, not `sent`, and with `approved` excluded a
rep-approved quote could never reach the customer at all, and re-entering approval via a
counter-offer would land back on `approved` with no way forward from there either. Fixed by
adding `approved` to `NEGOTIABLE_STATUSES`, and — since the state machine had no
`approved → under_negotiation` edge — adding that edge to `QUOTATION_TRANSITIONS` (a customer
asking for MORE than what was approved is a fresh negotiation round, exactly like
`sent → under_negotiation`). The portal maps `approved` down to the customer-facing label
`Sent`, consistent with #8b/c's rule that internal state names are never shown verbatim.

**The internal `POST /quotations/{id}/confirm` stand-in is now restricted**, as #7 said it
should be once this screen existed. It requires the new `deal.confirm_override` permission,
which only Admin holds. It is gated by *permission*, not by a role check, so it stays
consistent with SECURITY_SPEC.md Section 4's rule — Admin holds it only because Admin is
seeded with every permission.

### 9. Deal Health Anomaly Thresholds — LOCKED (2026-09-06)

PLAN.md §0.6 names this explicitly as a "stop and ask" item; confirmed with the user before
implementing. Both numbers are read from a config row (`report_settings`-shaped, actually
just two module constants for now — see Known Issues), not hardcoded deep in logic, so they
can be retuned without a code change to the *formula*.

**Stalled**: no activity (`quotation.last_activity_at`) for **7 or more days**, for any
quotation not yet in a terminal state (`confirmed`, `fulfilled`, `rejected`, `cancelled`).
`days_inactive = today - last_activity_at`.

**Discount anomaly**: this quotation's *effective discount* —
`discount_amount / subtotal_amount * 100`, i.e. the realized blended discount rate, not the
risk score — is **more than 10 percentage points above** the owning rep's own average
effective discount across their own most recent 20 non-draft quotations (or all of them, if
the rep has fewer than 20). The quotation being evaluated is excluded from its own baseline.
A rep with no other non-draft quotations has no baseline yet, so no anomaly can be flagged —
recorded as "insufficient history," not silently treated as zero.

**Delivery slippage**: needs no new threshold — it is a comparison already possible from
existing data. A fulfillment has slipped once `today > promised_date` and the fulfillment
has not reached `fulfilled`; `days_slipped = today - promised_date`.

**Implementation note**: no scheduled job exists (see "Background Jobs" — still "not yet
implemented"). Rather than block the dashboard on building a scheduler, health is computed
live and a fresh `DealHealthSnapshot` row is written every time the dashboard is viewed —
the same "compute lazily on the read that needs it" pattern already used for fulfillment's
auto-generated split. This gives genuine history (a manager sees a deal has been stalling for
a week, not only that it is stalled *now*) without needing a cron-equivalent process, at the
cost of a snapshot only existing for a day someone actually opened the dashboard.

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
| **`openpyxl` (XLSX) + `fpdf2` (PDF) for reporting export** (Phase 5 §0.5 checkpoint) | PRD A7 explicitly asks for PDF/XLS export. Both are pure Python with no system libraries to bake into the Docker image | `weasyprint` for PDF (needs Pango/Cairo — meaningfully bloats the image and adds a class of "works on my machine" build failure this project has otherwise avoided); `reportlab` (heavier API for the same tabular-report need `fpdf2` already covers) | `fpdf2`'s styling is basic — tables and text, no charts — which is exactly what a tabular sales report needs and nothing more |

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

**Resolved 2026-09-06 — the subscription-plan-picker gap is closed, and Locked Business Rules
#3's worked example is corrected.** The builder can now put a subscription line on a quote
(`LineRequest.subscription_plan_id`, validated against the product's real `item_type`); hybrid
billing and mid-cycle proration are fully implemented in `app/services/billing.py`. Separately,
while writing the test that reproduces #3's worked example exactly, found the example's own
numbers (800.04 / 1200.06 / 400.02) were a hand-rounding artifact, not the correct output of the
locked formula (the exact answer is 800.00 / 1200.00 / 400.00) — corrected in place; see that
section for the full explanation and `IMPLEMENTATION_LOG.md` 2026-09-06 "Hybrid Billing and
Proration."

**Resolved 2026-09-06 — customer portal negotiation is built, closing out Phase 3 (Core)
entirely.** PRD B8's real "Confirm Quotation" now lives at `POST
/portal/quotations/{id}/confirm`; the internal stand-in from Locked Business Rules #7 is
restricted to `deal.confirm_override` (Admin only) as promised there. See Locked Business
Rules #8 for the four business-logic decisions this required and the one real gap
(`approved` being negotiable at all) found via the live-API script rather than designed for
up front.

**Resolved 2026-09-06 — the display-precision cosmetic swept project-wide.** The gap noted in
the previous entry (a `Decimal` set directly from a JSON body prints without trailing zeros
until the row round-trips through Postgres) is now fixed at all three known occurrences:
`services/portal.py`'s counter discount, `services/billing.py`'s subscription quantity, and
`services/quotation.py`'s new `quantize_percent()`, used by both `replace_lines` and
`apply_order_discount`. A repo-wide grep for `Numeric(` columns fed directly from a request
body found no further instances.

**Resolved 2026-09-06 — Order-level discount UI built, and the Upsell panel wired to real
`upsell_rules` data.** The builder now has an "Order-level discount" control (with the
overwrite-warning `Locked Business Rules #4 requires`), and the Upsell & Cross-Sell panel
calls `GET /quotations/{id}/upsell` instead of showing promoted products as a stand-in. See
`app/services/upsell.py` for the ranking/margin-floor logic and its one documented judgment
call: `min_margin_percent` is read as a floor on the **suggested product's own margin**, not
on the order-wide margin delta the class docstring's third ranking bullet literally names —
the seeded values (10-20) only make sense as plausible product-margin percentages, not as
swings in a blended margin, which are normally a few points at most. Not raised as a
clarifying question: low-stakes, reversible, and documented here rather than blocking on it.

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

**Phase 3 (Core Business Workflow): complete — all 8 steps.**
- Blended risk engine and approval router in `app/services/risk.py` — pure, `Decimal`, 35 tests
- Idempotent seed data covering RBAC, catalogue, the full ceiling matrix, chains, stock and rules
- Login for all five roles; Argon2id, JWT with an explicit algorithm allowlist, refresh rotation
  with reuse detection, slowapi rate limiting on login and refresh
- Permission-based authorization plus separate resource-ownership checks, all in `api/deps.py`
- Quotation API with a single recalculation writer for totals, margin and risk, and a
  subscription-plan picker so a hybrid (one-time + recurring) order can actually be built
- Automatic approval routing including the sequential two-step Manager→Finance chain
- **Warehouse split + backorders** — greedy fill in `app/services/fulfillment.py` (pure, mirrors
  `risk.py`'s shape), reserving stock atomically via `SELECT ... FOR UPDATE` at the moment a
  split is generated, not deferred to "accept". Covers the full PRD B6 surface: auto-suggestion
  on first view, Accept, Manual Override (with release-then-reserve, still atomic), and
  Consolidate Remaining Backorder (manually triggered — see Known Issues for the "automatic"
  half). See Locked Business Rules #7 for the CONFIRMED-status trigger point and the internal
  `POST /quotations/{id}/confirm` stand-in this required.
- **Hybrid billing + proration** — `app/services/billing.py` (pure `compute_proration()` and
  `add_billing_interval()`, then DB orchestration), generated at the same CONFIRMED trigger point
  as fulfillment. Covers PRD B7's full surface: a one-time invoice row plus a recurring
  `Subscription` for each subscription line, mid-cycle quantity/plan modification with a full
  `ProrationRecord` audit trail, cancellation with policy-driven refunds (none/prorated/full),
  and `Scheduled → Invoiced → Paid` invoicing with payment recording.
- Audit trail on every create, edit, submission, approval, rejection, fulfillment action,
  billing action and denial
- **Customer portal negotiation** — a genuinely separate `/portal/*` API surface
  (`app/services/portal.py`, `app/api/v1/endpoints/portal.py`) gated by `portal.*` permissions
  no internal role holds, scoped by `customer_id` from the token, and returning schemas with no
  internal field to leak. Covers PRD B8's full surface: comment/counter-offer (an order-level
  discount, reusing the same discount and risk-scoring code an internal edit would), and Confirm
  with the automatic re-approval loop — including `terms_already_approved()`, the rule that
  keeps an already-approved quotation from bouncing back to the same approver forever. See
  Locked Business Rules #8.
- **Upsell / cross-sell panel wired to real data** (PRD A6, B5) — `app/services/upsell.py`
  ranks seeded `upsell_rules` by promotion then co-purchase score, suppresses anything below its
  own margin floor, and computes the live margin-delta figure the panel displays by simulating
  the exact line `addProduct()` would create. Builder also gained the Order-Level Discount
  control (Locked Business Rules #4) that had been deferred since Phase 3 began.

**Phase 5 (Supporting): complete — all four originally-listed items.**
- **Deal health dashboard** (PRD B9) — `app/services/dealhealth.py` implements the thresholds
  locked in #9: 7+ days idle is "stalled," more than 10 points above a rep's own trailing
  20-quote average is a "discount anomaly," and any fulfillment past its `promised_date` has
  "delivery slippage." No scheduler exists, so health is recomputed and snapshotted live on
  every dashboard view rather than by a background job.
- **Reporting + export** (PRD A7) — filters exactly matching PRD A7's own list (Period, Rep,
  Approval Status, Category), with `openpyxl`/`fpdf2` export (Section 0.5 checkpoint — see
  Important Technical Decisions).
- **Admin config screens** (Screen 18) — the discount ceiling matrix and approval-chain bands
  are now editable through the UI, not just seeded data. One reconciliation: the wireframe's
  two separate "tier" and "category" ceiling tables are rendered as the one matrix the backend
  actually stores (Locked Business Rules #1/#6), since the ceiling has always been a
  (tier, category) pair, not two independent limits.
- **Product catalogue** (Screens 16-17) — Product and Category CRUD (create, edit, archive).
  Variant and price-list editing from the wireframe are not built this round — general info is
  the part PRD A2 actually gates the builder's product picker on.

**Phase 8 (Frontend): Screens 1-18 all have a real screen or a deliberate, documented gap.**
Screens 1-6 brought forward at the user's request once `FRONTEND.md` supplied the design
input; Screens 7-8 (Fulfillment), 9-10/12-13 (Subscriptions/Invoices), 11 (the customer
portal), 14 (Deal Health), 15 (Reports) and 16-18 (Admin config) each followed once their
respective backends existed.

**Verified 2026-09-06:** 223 unit/integration tests (197 + 26 new deal-health/reporting tests)
plus 56 + 51 + 40 + 29 + 9 + 15 end-to-end API checks all pass. Fulfillment's flows (Confirm →
auto-generated split → Accept, Manual Override, Consolidate-after-restock) were driven through
the real UI headlessly; everything built since (billing, portal, upsell, deal health,
reporting, admin config) compiles and type-checks against the real API (`tsc -b && vite build`
clean) and was verified via live-API scripts, but has not yet had a full browser click-through
— tracked in `IMPLEMENTATION_LOG.md`'s Known Issues. `DEMO.md` covers fulfillment, billing and
portal negotiation; the Phase 5 screens are not yet in its script (see its own changelog note).

## Remaining Work

**All of PLAN.md Section 18's Core (🔴) and Supporting (🟡) scope is now complete.** Phase 3
(Core) and every originally-listed Phase 5 (Supporting) item — deal health, reporting/export,
admin config screens, product catalogue — are implemented, tested, and verified against the
real running system. See `IMPLEMENTATION_LOG.md` 2026-09-06 "Complete Supporting Scope" for
the full entry. Only 🟢 Bonus scope (multi-currency, multi-company — PLAN.md explicitly calls
these optional) and the items below remain.

### Deferred deliberately

- **HttpOnly cookie auth** — the refresh token currently lives in `sessionStorage`, mirrored to
  `localStorage` purely as a same-browser "last active session" bootstrap for a brand-new tab
  (see IMPLEMENTATION_LOG.md 2026-09-05 for the original cross-tab bug this design fixes, and
  2026-09-06 for the deep-link-in-a-new-tab bug the localStorage fallback fixes on top of it).
  SECURITY_SPEC Section 7 prefers cookies and that remains the right end state; it needs CSRF
  handling and a same-site story the split localhost origins do not currently allow
- **`PATCH /api/v1/admin/users/{id}/role`** — superseded, not merely deferred. Locked Business
  Rules #5 originally intended this for promoting a self-registered Sales Rep, but
  `POST /admin/users/invite` (2026-09-06, part 2) now lets an Admin provision a user straight
  into the right role from the start, which is the pattern real ERPs actually use. A dedicated
  role-change endpoint for an *existing* user (demotion, or correcting a mis-provisioned role)
  is still genuinely absent — an Admin edits the row directly for that narrower case
- **Fully-automatic backorder consolidation** — PRD B6's "prompt appears automatically" needs a
  background job watching for restocks. What exists now (`POST
  /fulfillment/{id}/backorders/{id}/consolidate`) is the manual trigger that prompt would call;
  an ops/finance user has to check and click it themselves rather than being notified
- **Automatic subscription cycle renewal and dunning** — nothing rolls `current_cycle_start`/
  `current_cycle_end` forward when a cycle ends, or generates the next `recurring`
  `BillingSchedule` row automatically. Every subscription created by the demo stays on its first
  cycle indefinitely. Same category of gap as backorder consolidation — needs a scheduler
- **Restricting public signup** — signup grants an empty internal workspace to anyone. Acceptable
  for a hackathon, wrong for production; belongs in the "what we'd build next" deliverable
- **`deal.assign`** ("Reassign a quotation to another rep") is a real permission in `app/seed.py`
  with no endpoint or UI behind it anywhere — found during the 2026-09-06 bug sweep below, not
  built (out of scope for that pass, not forgotten)
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
  hypothetical — it caused three real bugs in this codebase (`auth.py`'s `_USER_LOADS`,
  `generate_fulfillment`'s missing refresh, and `modify_subscription`/`cancel_subscription`/
  `record_payment`'s missing refresh — all `MissingGreenlet` or silently-stale-collection
  failures under async). **"The caller re-queries afterward" is not a safe substitute even
  when it looks like one**: if the caller's re-query runs in the SAME session and the parent
  object is already in that session's identity map (already loaded once earlier in the same
  request), SQLAlchemy returns the cached object with its already-populated collections
  UNCHANGED — a second `SELECT ... selectinload(...)` does not force a reload of a collection
  that object already has loaded. This is exactly how the billing bug survived pytest (each
  test read the function's *return value*, never the parent's collection) but was caught
  immediately by the live-API script (the API layer's own re-fetch-after-commit pattern hit
  it on the very first request). Fix it at the source, in the service function, always
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
