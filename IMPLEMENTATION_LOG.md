# Implementation Log — DealFlow360

This file records what has actually happened during implementation, in chronological order. Every meaningful session appends a new entry below. Do not delete or rewrite past entries — this is a history, not a status doc (that's PROJECT_CONTEXT.md's job).

Use this exact format for every entry:

```
## [DATE] — [SHORT TASK NAME]
### Goal
What were we trying to accomplish?
### Implemented
What was actually changed?
### Files Changed
- `path/to/file`
### Important Decisions
- Decision:
- Reason:
### Validation
- Tests:
- Build:
- Manual verification:
### Known Issues
- ...
### Current State
What works now?
### Next Recommended Step
What should be implemented next?
```

---

<!-- Add new entries below this line, most recent at the bottom -->

## 2026-09-05 — Phase 0 Reconnaissance + Phase 1 Foundation

### Goal
Establish the runnable project skeleton per PLAN.md Phase 1: FastAPI + React + PostgreSQL under Docker Compose, with Alembic migrations and dev tooling wired up. Also commit the four source-of-truth documents, which existed only outside the repository.

### Implemented

**Phase 0 — Reconnaissance.** Repository contained only a stub `README.md` (UTF-16, one line) and a single commit. No code, no config, no dependencies. Per PLAN.md Section 0 item 9, proceeded directly to Phase 1. Host toolchain confirmed: Python 3.14.5, Node 24.15.0, Docker 29.7.2 with Compose v5.3.1.

**Source-of-truth documents.** `PLAN.md`, `PROJECT_CONTEXT.md`, `IMPLEMENTATION_LOG.md`, and `SECURITY_SPEC.md` were supplied in conversation but were not in the repository — PLAN.md Section 22 (Handoff Protocol) requires incoming sessions to read them from the repo. All four are now committed. The supplied copies had mojibake from a bad encoding round-trip (`â`, `ð´`); they were rewritten as clean UTF-8 with the intended characters (`—`, `🔴`). Content is otherwise unchanged.

**Phase 1 — Foundation.**
- FastAPI application with lifespan management, versioned router mounted at `/api/v1`, and liveness + readiness health endpoints.
- Async SQLAlchemy 2 engine (`asyncpg`) with a bounded pool and a request-scoped session dependency that rolls back on unhandled exceptions.
- Declarative `Base` with an explicit metadata naming convention, plus a `TimestampMixin` supplying `created_at` / `updated_at`.
- Alembic configured with an async `env.py`; the database URL is injected from application settings so credentials never live in `alembic.ini`. `compare_type` and `compare_server_default` are on.
- Pydantic settings module reading everything from the environment.
- Global exception handlers returning generic client messages with a correlation id, logging full detail server-side only.
- React 18 + TypeScript via Vite, with a deliberately unstyled placeholder page that checks backend readiness.
- Docker Compose: Postgres 16 (healthcheck-gated), backend (non-root, `--reload`), frontend (Vite HMR with polling for the Windows bind mount).
- Tooling: ruff (including bandit-style `S` rules) and pytest, both configured in `pyproject.toml`.

### Files Changed
- `PLAN.md`, `PROJECT_CONTEXT.md`, `IMPLEMENTATION_LOG.md`, `SECURITY_SPEC.md` (committed to repo)
- `README.md` (replaced stub)
- `.gitignore`, `.env.example`, `docker-compose.yml`
- `backend/Dockerfile`, `backend/.dockerignore`, `backend/requirements.txt`, `backend/requirements-dev.txt`, `backend/pyproject.toml`
- `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`
- `backend/app/main.py`
- `backend/app/core/config.py`, `backend/app/core/errors.py`, `backend/app/core/logging.py`
- `backend/app/db/base.py`, `backend/app/db/session.py`
- `backend/app/models/__init__.py`, `backend/app/schemas/health.py`
- `backend/app/api/deps.py`, `backend/app/api/v1/router.py`, `backend/app/api/v1/endpoints/health.py`
- `backend/tests/conftest.py`, `backend/tests/test_health.py`
- `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/Dockerfile`, `frontend/.dockerignore`
- `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/lib/api.ts`

### Important Decisions

- Decision: Async SQLAlchemy 2 + `asyncpg`, not sync SQLAlchemy + `psycopg2`.
- Reason: FastAPI is async; a sync driver in an async endpoint blocks the event loop silently. The two hardest upcoming correctness requirements — `SELECT … FOR UPDATE` for stock deduction and optimistic locking on concurrent approvals — behave identically either way, so nothing is lost. Cost is `greenlet`, an async Alembic `env.py`, and discipline about blocking calls.

- Decision: `POSTGRES_PASSWORD` and `JWT_SECRET_KEY` are required settings with no defaults in code.
- Reason: SECURITY_SPEC.md Section 8 forbids hardcoded secrets. A default is exactly how a placeholder secret reaches production unnoticed. The app now fails loudly at startup instead. This also removed two legitimate ruff `S105` findings at the source rather than suppressing them.

- Decision: Python 3.12 pinned in the container, though the host runs 3.14.
- Reason: Prebuilt wheels for every dependency exist on 3.12, avoiding a source-compile stall during a 24-hour build.

- Decision: Metadata naming convention set on `Base` before the first migration exists.
- Reason: Without it, Alembic autogenerate emits unnamed CHECK/UNIQUE constraints that a later migration cannot drop. PLAN.md Section 7 expects the schema to keep evolving, so this had to be in place before any table is created — it cannot be retrofitted cheaply.

- Decision: The React page is an explicitly-labelled unstyled placeholder.
- Reason: PLAN.md Phase 8 holds all UI work until design input arrives. Proving the React → FastAPI → PostgreSQL path works is foundation, not design; the file says so in a comment so a later session does not mistake it for a design decision.

- Decision: Redis rate limiting deferred rather than rejected outright.
- Reason: SECURITY_SPEC.md Section 5 requires login rate limiting, but no login endpoint exists yet. Re-evaluated at the Phase 6 checkpoint against a real endpoint.

### Validation

- Tests: `docker compose exec backend pytest` → **3 passed**. Covers liveness without a database, readiness returning 503 (not 500) when the database is unreachable, and an assertion that error responses contain no `traceback` / `asyncpg` / `sqlalchemy` / `password` strings.
- Build: `docker compose build` succeeded for both images. `docker compose exec frontend npm run build` produced a production bundle (144.64 kB, 46.58 kB gzip). `tsc --noEmit` clean.
- Lint: `ruff check .` → all checks passed. `ruff format --check .` → 24 files already formatted.
- Manual verification:
  - `docker compose up -d` → `db` healthy, `backend` healthy, `frontend` serving.
  - `GET /api/v1/health` → `200 {"status":"ok","environment":"development","database":"not_checked"}`.
  - `GET /api/v1/health/ready` → `200 {"status":"ok","environment":"development","database":"ok"}` — a real `SELECT 1` through the async engine, so the full React→API→Postgres path is proven, not assumed.
  - `alembic current` and `alembic upgrade head` run; `alembic_version` table confirmed present via `psql`.
  - `alembic revision --autogenerate` generated a migration file successfully (throwaway probe, deleted) — proves `target_metadata` wiring works before Phase 2 depends on it.
  - CORS: request with `Origin: http://localhost:5173` returns `access-control-allow-origin`; request with `Origin: http://evil.example` returns none. No wildcard.
  - `GET /docs` returns 200 in development.
  - Frontend dev server returns the app shell at `http://localhost:5173`.

**Three defects were found by running the stack and were fixed, not worked around:**
1. Backend crash-looped on boot: `pydantic-settings` JSON-decodes complex-typed env vars *before* field validators run, so the comma-separated `CORS_ORIGINS` raised `SettingsError`. Fixed with `Annotated[list[str], NoDecode]`.
2. The "database unreachable" test passed against a *healthy* database — `conftest.py` used `os.environ.setdefault`, which is a no-op inside Compose where those variables are already set to the live DB. Changed to direct assignment; the test now genuinely exercises the failure path.
3. ruff `B008` on `Depends()` in an argument default. Replaced with an `Annotated` `SessionDep` alias in `app/api/deps.py`, which also gives every future endpoint one reusable session dependency.

### Known Issues

- **Four business rules remain unlocked and block later phases** (PLAN.md Section 0.6): blended risk score formula, proration rounding rule, deal-health anomaly thresholds, warehouse tie-breaking rule. The risk score formula is the most urgent — it partly shapes the Phase 2 schema.
- **`DealFlow360_PRD_Merged.md` is missing from the repository.** PLAN.md names it authoritative for feature scope. `DealFlow360.pdf` was supplied in conversation but not committed. Both should be added to `docs/`.
- **No design input yet** — Phase 8 hold remains in force; `frontend/src/App.tsx` must be replaced wholesale once a mockup/design resource arrives.
- `backend/app/models/` is empty. Until Phase 2, the database contains only `alembic_version`.
- The frontend Dockerfile is dev-mode only; a production multi-stage build is deferred to Phase 10 as there is no deploy target during the hackathon.

### Current State
The project runs. `docker compose up --build` yields a healthy three-service stack where the React page successfully reads live database status through the FastAPI backend. Migrations, tests, linting, formatting, and the frontend production build all work. There is no data model, no authentication, no business logic, and no designed UI.

Phase 1 exit condition ("the project starts successfully and the basic foundation is verified") is met.

### Next Recommended Step
**Phase 2 — Core Data Model**, after the Section 0.5 checkpoint for that phase.

Blocked-on-input first: lock the blended discount risk score formula, since it determines which computed fields `quotations` must persist and how `discount_tiers` / `approval_chains` are shaped. Schema work that does not depend on it (users/roles/permissions, customers, products + variants, warehouses, stock levels) can begin in parallel.

---

## 2026-09-05 — Phase 2: Core Data Model

### Goal
Implement the full data model behind every PRD feature (Core, Supporting and Bonus-if-time), under Alembic migration control, with explicit state machines and a checked-in ERD. PLAN.md treats this as a primary judging criterion, so it got rigour rather than a quick schema pass.

### Implemented

**Section 0.5 checkpoint — no new technology adopted.** Considered and rejected `eralchemy2`/`sqlalchemy-schemadisplay` for ERD generation (needs Graphviz in the image; generated output has no room for the "why" annotations that earn marks) and `python-statemachine` for the lifecycle machines (plain dict transition tables are ~60 lines, dependency-free and easier to defend in a viva). One in-stack decision recorded: enums as VARCHAR + named CHECK rather than native PostgreSQL ENUM.

**30 tables**, grouped by domain across eleven model modules:
- Identity/access: `roles`, `permissions`, `role_permissions`, `users`, `sales_teams`
- Commercial master data: `customers`, `product_categories`, `products`, `product_variants`, `price_lists`, `price_list_items`
- Discount governance: `discount_tiers` (the tier × category ceiling lookup), `approval_chains` (the routing bands, as configurable rows)
- Quotations: `quotations`, `quotation_lines`
- Approvals: `approval_requests`, `approval_steps`
- Inventory: `warehouses`, `stock_levels`, `fulfillments`, `fulfillment_splits`, `backorders`
- Billing: `subscription_plans`, `subscriptions`, `billing_schedules`, `proration_records`, `payments`
- Supporting: `upsell_rules`, `deal_health_snapshots`
- Audit: `audit_logs`

**Applied to every table:** audit columns via `AuditMixin`; archival flags on all master data; deliberate ON DELETE behaviour on all 70 foreign keys (RESTRICT by default, CASCADE only where a child has no independent existence); indexes on foreign keys and on the columns the pipeline, approval queue and dashboard actually filter by; CHECK constraints on percentages, quantities, money, date ordering and cross-column invariants.

**Six state machines** in `app/services/state_machine.py` — pure, no I/O — with `assert_transition()` raising `InvalidStateTransition`.

**ERD** at `docs/erd.md`: system architecture flowchart, three ER diagrams, six state diagrams, and a table of modelling decisions with their justification.

### Files Changed
- `backend/app/models/` — `enums.py`, `rbac.py`, `customer.py`, `catalog.py`, `policy.py`, `quotation.py`, `approval.py`, `inventory.py`, `billing.py`, `upsell.py`, `dealhealth.py`, `audit.py`, `__init__.py`
- `backend/app/db/base.py` (added `IdMixin`, `AuditMixin`, `ArchivableMixin`)
- `backend/app/services/state_machine.py`
- `backend/alembic/versions/20260905_1056-809cac63fb15_initial_core_data_model.py`
- `backend/tests/conftest.py`, `backend/tests/test_health.py`, `backend/tests/test_state_machines.py`, `backend/tests/test_db_constraints.py`
- `docs/erd.md`
- `PROJECT_CONTEXT.md`

### Important Decisions

- Decision: Quotation status is a **superset** of PLAN.md Section 7's list — adds `sent`, `under_negotiation` and `rejected`.
- Reason: PRD B8 requires the portal to show "Sent, Under Negotiation, Confirmed", and PRD A7 requires reporting to filter by rejected quotations. PLAN.md Section 1 says the PRD wins on *what* to build. **Flagged in PROJECT_CONTEXT.md for confirmation** — cheap to change now, expensive once Phase 3 depends on it.

- Decision: Snapshot `unit_list_price`, `unit_cost_price` and `allowed_discount_percent` onto each quotation line.
- Reason: master data changes. An approved quotation must stay reproducible, and `allowed_discount_percent` is what answers "what was the policy when this was approved?" — the question an auditor actually asks.

- Decision: Approvals modelled as request then ordered steps, with `required_role_id` snapshotted onto each step.
- Reason: each step is a different person, time and reason, so one row per decision is what makes the audit trail complete. Snapshotting the role means an Admin reconfiguring `approval_chains` later cannot retroactively rewrite who was supposed to approve a past deal.

- Decision: Enums stored as VARCHAR + named CHECK, not native PostgreSQL ENUM.
- Reason: `ALTER TYPE ... ADD VALUE` cannot always run in a transaction and is awkward to reverse in a downgrade. The schema is expected to keep moving; a CHECK constraint is ordinary DDL. The database still rejects invalid values.

- Decision: `NULLS NOT DISTINCT` on the `stock_levels` unique index.
- Reason: PostgreSQL treats NULLs as distinct by default, so a plain UNIQUE would silently permit duplicate stock rows whenever `variant_id` is NULL — and the warehouse split would then read one row and under-count available stock. Requires PostgreSQL 15+; we run 16.

- Decision: `audit_logs` deliberately omits `updated_at` and `created_by`.
- Reason: an audit row is never updated, and `user_id` already names the actor. A mutable timestamp on an audit table invites the tampering the table exists to detect.

- Decision: `version` column with SQLAlchemy `version_id_col` on quotations.
- Reason: PLAN.md Section 14 names two managers approving simultaneously. Optimistic locking turns a silent last-write-wins into a visible `StaleDataError`, without holding row locks across a user's think-time.

### Validation

- Tests: **69 passed**. State machine transitions and rejections; transition-table completeness (a new enum value with no transition entry now fails a test rather than raising KeyError mid-demo); database constraints proven against real PostgreSQL — over-100% discount ceilings, duplicate (tier, category) ceilings, zero quantities, duplicate line numbers, subscription lines without a plan, one-time lines carrying a plan, reserved stock exceeding on-hand, duplicate stock rows with NULL variant, decided approval steps missing an actor, recurring billing rows without a subscription, impossible proration day counts, self-referencing upsell rules, and the optimistic-lock version bump.
- Build: `docker compose build` succeeds; frontend `tsc --noEmit` clean.
- Lint: `ruff check .` all checks passed; `ruff format --check .` 39 files already formatted.
- Manual verification:
  - `alembic upgrade head` from empty creates 30 tables plus `alembic_version`; 70 foreign keys present.
  - `alembic downgrade base` returns the database to only `alembic_version`, then `upgrade head` rebuilds it — the migration is genuinely reversible.
  - **Drift check:** a second `alembic revision --autogenerate` produces an empty migration, proving models and database agree.
  - Every table in the live database appears in `docs/erd.md` (scripted check).
  - All 10 Mermaid blocks in `docs/erd.md` parsed with the real Mermaid parser — the diagrams render, not merely look plausible.
  - `GET /api/v1/health/ready` still returns `{"database":"ok"}`.

**Three defects were found by verification and fixed:**

1. **Alembic silently omitted every `use_alter` foreign key.** Autogenerate renders foreign keys inline inside `create_table` and drops the ones marked `use_alter=True`, so the first migration created all 30 tables but *none* of the `created_by`, `users.customer_id` or `sales_teams.manager_id` constraints — 30 columns with no referential integrity at all, which would have passed every smoke test. Caught only by the idempotency probe. The 30 constraints were merged by hand into the initial migration, with matching drops at the head of `downgrade()` (without them `DROP TABLE` fails on the still-referencing constraints).
2. **Two ambiguous relationship joins.** `AuditMixin.created_by` gives several tables a second foreign-key path to `users`, so `ApprovalStep.actor` and `Role.users` could not resolve. Fixed with explicit `foreign_keys` — and the distinction matters: on an approval step, `created_by` is who *raised* it and `actor_id` is who *decided* it.
3. **A test that could not fail.** The "database unreachable" health test raised during dependency resolution, so it exercised the global 500 handler rather than the endpoint's 503 path — asserting against a situation that cannot occur in production, where asyncpg connects lazily on first `execute`. Replaced with a stub session that fails on `execute`.

### Known Issues
- **Quotation state machine superset needs user confirmation** (see Important Decisions above).
- **Seed data does not exist yet** — no roles, permissions, users, discount tiers or approval-chain rows. This is a prerequisite for Phase 3 step 1 and for both demo flows.
- The `users` invariant "role is customer if and only if `customer_id` is set" is enforced in the service layer, not by a CHECK constraint: PostgreSQL CHECK cannot read another table, and the role code lives in `roles`. Documented in `rbac.py` so the omission reads as considered rather than overlooked.
- Database tests run against the development database. Each test is wrapped in a rolled-back transaction so it leaves no residue, but a dedicated test database would be cleaner if time allows.
- Deal-health thresholds and the warehouse tie-break rule remain unanswered; neither affects the schema.

### Current State
The full data model exists, is migrated, is diagrammed, and its constraints and state machines are proven by tests. `docker compose up --build` still brings up a healthy stack. There is still no authentication, no business logic and no designed UI — Phase 2 delivered the foundation those sit on, not behaviour.

Phase 2 exit condition ("the full data model supports every Core and Supporting workflow in the PRD, is diagrammed, and is under migration control") is met.

### Next Recommended Step
**Phase 3 — Core Business Workflow**, after its Section 0.5 checkpoint, in PLAN.md Section 8's order. Two things to do first:

1. **Seed data** — roles and permissions, one user per role, discount tiers (Bronze 5 / Silver 10 / Gold 15, with a stricter Services ceiling so the PRD's own worked example reproduces), the three `approval_chains` rows, two warehouses with deliberately partial stock, and a product mix spanning Hardware / Services / Subscriptions.
2. **The blended risk engine** — the formula and the single-line gate are locked in PROJECT_CONTEXT.md; implement with `Decimal` and unit-test against both worked examples from PRD Section 10 before wiring it into routing.
