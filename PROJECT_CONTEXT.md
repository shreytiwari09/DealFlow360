# Project Context — DealFlow360

## Current Objective
Build the full PRD scope per its own Core/Supporting/Bonus classification (PLAN.md Section 18), sequenced: 🔴 Core workflow fully working first, then 🟡 Supporting, then 🟢 Bonus only if ahead of schedule. Database and business-logic correctness are being treated as first-class judging criteria, not implementation afterthoughts.

**Where we are right now:** Phase 1 (Foundation) is complete and validated. Phase 2 (Core Data Model) is next, but is blocked on locking the blended risk score formula — see Known Issues.

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
                      in committed config). versions/ is empty until Phase 2.
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
    models/           EMPTY — Phase 2. Every model must be imported in
                      models/__init__.py or Alembic autogenerate will not see it.
    schemas/          Pydantic response DTOs (health.py only so far).
    services/         EMPTY — Phase 3 business logic.
    api/
      deps.py         SessionDep. Auth/permission dependencies land here in Phase 6.
      v1/router.py    Aggregate router; feature routers registered here.
      v1/endpoints/   health.py only so far.
  tests/              Phase 1 foundation tests (deliberately run without a DB).
frontend/
  src/App.tsx         Unstyled Phase 1 placeholder — replace entirely at Phase 8.
  src/lib/api.ts      Thin fetch client; base URL from VITE_API_BASE_URL.
docs/                 ERD + architecture diagram — Phase 2 deliverable.
```

## Core Data Model (target schema — finalize during Phase 2, diagram as ERD)

**Status: not yet implemented.** `backend/app/models/` is empty; the only table in the database is `alembic_version`.

**Entities:** users, customers (tier), products (with variants), price_lists, discount_tiers (customer tier × category → max %), approval_chains, quotations, quotation_lines, warehouses, stock_levels, fulfillment_splits, backorders, subscription_plans, billing_schedules, proration_records, upsell_rules, deal_health_snapshots, approval_logs (audit trail).

**Standards applied to every table:**
- Audit columns: `created_at`, `updated_at`, `created_by` (`TimestampMixin` in `app/db/base.py` already provides the first two; `created_by` is added in Phase 2 once `users` exists so the FK can be declared properly)
- Archival, not hard delete, for master data (products, customers): `is_active` / `archived_at`
- Explicit FK behavior (RESTRICT vs CASCADE) decided per relationship, not left as an ORM default
- Indexes on all foreign keys and frequently filtered columns (customer_id, status, created_at)
- CHECK constraints where meaningful (e.g., discount percentage within valid range)
- A metadata naming convention is already configured, so constraints get stable names and can be altered/dropped by later migrations

**Explicit state machines (document transitions, enforce in code, reject invalid moves):**
- Quotation: `draft → pending_approval → approved → confirmed → fulfilled / cancelled`
- Approval: `pending → approved / rejected / returned_for_revision`
- Subscription: `active → modified → cancelled`
- Fulfillment: `pending → partially_fulfilled → fulfilled / backordered`

**ERD status:** _(not yet created — required deliverable of Phase 2, kept current as schema evolves)_

## Core Workflows
1. Rep builds quotation → adds lines → applies discounts
2. Blended risk score computed live across all lines (**exact formula not yet locked — see Known Issues**)
3. Threshold exceeded → auto-routes to Manager (and Finance if higher threshold)
4. Approved → stock deducted/split across warehouses; backorder created if insufficient
5. Subscription lines get billing schedule + proration on mid-cycle change (**rounding rule not yet locked — see Known Issues**)
6. Customer negotiates via portal → counter-offer may re-trigger step 3 automatically
7. Deal health dashboard surfaces stalled/anomalous deals from the above activity

## Important APIs

Base prefix: `/api/v1`. Implemented so far:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Liveness. Does not touch the database. |
| GET | `/api/v1/health/ready` | Readiness. Returns 503 (not 500) when the DB is unreachable, so "not ready yet" is distinguishable from "broken". |

Feature routers are registered in `app/api/v1/router.py` as they are built.

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
| **Secrets have no in-code defaults** | `POSTGRES_PASSWORD` / `JWT_SECRET_KEY` are required settings, so the app fails loudly rather than silently running on a placeholder | Defaults for developer convenience | A missing `.env` is now a startup error — which is the intended behaviour |

### Section 0.5 Technology Evaluation Checkpoints (log)

**Phase 1 — Foundation.** *Outcome: no new technology adopted.*
1. Anything the current stack cannot cleanly satisfy? **No.** Phase 1 is scaffolding; FastAPI + React + PostgreSQL + Docker Compose covers it, and Alembic is already mandated by PLAN.md Section 6 rather than being a new choice.
2. Candidates genuinely considered:
   - **`uv`** (Astral) instead of `pip` + `requirements.txt`. *Problem it would solve:* Docker rebuild latency during a 24h build. *Why the current stack is enough:* pip plus Docker layer caching keeps rebuilds acceptable, and dependencies change rarely after Phase 2. *What breaks without it:* nothing — only slower rebuilds. **Rejected**; revisit only if rebuild time becomes a felt cost.
   - **A Redis-backed rate limiter** for the login endpoint required by SECURITY_SPEC.md Section 5. *Why deferred:* login does not exist until Phase 3/6, and at single-instance demo scale an in-process limiter is sufficient and has no extra failure mode. **Deferred to the Phase 6 checkpoint**, where it will be evaluated against a real endpoint.
3. Two in-stack architectural decisions were made and recorded in the table above (async SQLAlchemy, Vite) — these are choices within the sanctioned stack, not new dependencies.

## Known Constraints
- 3-person team, 24-hour hackathon
- Team strengths: FastAPI, React (used together before); some DevOps
- Team weaknesses: JS depth, heavy full-stack polish
- No prior Odoo experience (not required — any stack allowed)
- This is treated as an ERP-grade build — data model and business logic correctness are weighted above UI polish

## Known Issues

**Blocking questions — must be answered before the dependent phase begins (PLAN.md Section 0.6):**
- **Blended risk score exact formula not yet locked** — blocks Phase 3 step 3, and partly shapes Phase 2 (which computed fields the `quotations` table stores). The PRD (Section 10) explains the *intent* — per-line limits by customer tier × product category, and an aggregate that catches many small violations — but never gives the arithmetic or the Manager/Finance cut-offs.
- **Proration rounding rule not yet locked** — blocks Phase 3 step 6.
- **Deal health anomaly thresholds not yet defined** — blocks the Phase 5 dashboard.
- **Warehouse selection tie-breaking rule not yet defined** — blocks Phase 3 step 5.

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

**Phase 2 onward: not started.**

## Remaining Work
Mirrors PLAN.md Section 18. Nothing in the 🔴 Core / 🟡 Supporting / 🟢 Bonus feature set is implemented yet — Phase 1 delivered scaffolding only. Next: Phase 2 (Core Data Model).

## Do Not Change / Do Not Break
- Blended risk score formula, once locked — do not let a later session silently redefine it
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
