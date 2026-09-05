# Project Context — DealFlow360

## Current Objective
Build the full PRD scope per its own Core/Supporting/Bonus classification (PLAN.md Section 18), sequenced: 🔴 Core workflow fully working first, then 🟡 Supporting, then 🟢 Bonus only if ahead of schedule. Database and business-logic correctness are being treated as first-class judging criteria, not implementation afterthoughts.

**Where we are right now:** Phases 1 (Foundation) and 2 (Core Data Model) are complete and
validated. 30 tables are under Alembic migration control, six state machines are enforced in
code, and the ERD is checked in at `docs/erd.md`. **Phase 3 (Core Business Workflow) is
next**, starting with the blended risk engine, whose formula is already locked below.

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
- **Frontend:** React 18 + TypeScript, built with Vite. **Design system/mockup input still pending** — an Excalidraw mockup exists; Claude must ask for a markdown resource file before building any screen (PLAN.md Section 13/Phase 8). The current page is an unstyled connectivity placeholder, not a design decision.
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
                      lifecycle entities, plus assert_transition(). Pure, no
                      I/O. Phase 3 business logic joins it here.
    api/
      deps.py         SessionDep. Auth/permission dependencies land here in Phase 6.
      v1/router.py    Aggregate router; feature routers registered here.
      v1/endpoints/   health.py only so far.
  tests/              test_health.py (endpoints), test_state_machines.py
                      (pure), test_db_constraints.py (runs against the real
                      PostgreSQL schema, each test rolled back).
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

## Core Workflows
1. Rep builds quotation → adds lines → applies discounts
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

**JWT security checklist:** see SECURITY_SPEC.md Section 11 — complete before final submission (tracked in IMPLEMENTATION_LOG.md).

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

**Assumption made and flagged for confirmation (PLAN.md Section 0.6):**
- **The quotation state machine is a deliberate SUPERSET of the list in PLAN.md Section 7.**
  PLAN gives `draft → pending_approval → approved → confirmed → fulfilled / cancelled`.
  Three further states were added because the PRD itself requires them, and PLAN.md Section 1
  says the PRD wins on *what* to build:
    * `sent` and `under_negotiation` — PRD B8 requires the customer portal to display
      "Sent, Under Negotiation, Confirmed" as the quotation status.
    * `rejected` — PRD A7 requires reporting to filter by "pending, approved, or rejected
      quotations", which needs a quotation-level state, not just an approval-record state.
  Full transition table in `docs/erd.md` and `app/services/state_machine.py`. **Please confirm
  this reading**; it is cheap to change now and expensive once Phase 3 depends on it.

**Still open — needed before the phase that depends on each (PLAN.md Section 0.6):**
- **Deal health anomaly thresholds not yet defined** — blocks the Phase 5 dashboard.
  Specifically: how many days of inactivity makes a quote "stalled", and how far above a
  rep's own historical average a discount must sit to count as an anomaly. Neither affects
  the Phase 2 schema (both are configuration rows), so this can wait.
- **Warehouse selection tie-breaking rule not yet defined** — blocks Phase 3 step 5. When
  two warehouses can equally satisfy a line: lowest shipping-cost weight, then highest
  remaining stock, then lowest warehouse id? Does not affect the schema either.

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

**Phase 3 onward: not started.**

## Remaining Work
Mirrors PLAN.md Section 18. No 🔴 Core / 🟡 Supporting / 🟢 Bonus *behaviour* is implemented
yet — Phases 1 and 2 delivered the foundation and the schema that every feature sits on.

Next: **Phase 3 (Core Business Workflow)**, in the order PLAN.md Section 8 gives:
1. Login for all five roles
2. Quotation builder (lines, discounts, live totals and margin)
3. Blended risk engine — formula already locked, see Locked Business Rules #1
4. Approval routing — reads `approval_chains`, applies the single-line gate
5. Multi-warehouse split + backorders
6. Hybrid billing + proration
7. Customer portal negotiation with automatic re-approval
8. Audit trail on every approval/rejection/edit

Seed data (roles, permissions, the five demo users, discount tiers, the three approval-chain
rows, warehouses, products) is a prerequisite for step 1 and does not exist yet.

## Do Not Change / Do Not Break
- **Blended risk score formula — now locked.** See Locked Business Rules #1. Do not let a
  later session silently redefine it, and do not add a redundant "any line over ceiling"
  check to decide *whether* approval is needed — that already falls out of the formula
- **The single-line Finance gate (`max(line_excess) > 15`) is a real, separate rule.** It
  overrides the score band and must not be folded into the blended score
- **Approval score bands live in `approval_chains` rows, not in code.** Do not hardcode them
- **Proration uses `Decimal` + explicit `ROUND_HALF_UP`.** Never `float`, never Python's
  built-in `round()`, which is banker's rounding and gives different answers
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
