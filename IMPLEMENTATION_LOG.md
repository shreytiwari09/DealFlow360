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

---

## 2026-09-05 — Phase 3 (part 1): Risk Engine, Routing and Seed Data

### Goal
Begin PLAN.md Phase 3. Run the Section 0.5 checkpoint, then build the two things every later step depends on: demo seed data, and the blended discount risk engine with its approval router — unit-tested against the PRD's own worked examples *before* being wired into any workflow.

### Implemented

**Section 0.5 checkpoint — three dependencies adopted after review.** Unlike Phases 1 and 2, this phase surfaced real gaps the stack cannot fill:
- **argon2-cffi** — SECURITY_SPEC §3 requires Argon2id or bcrypt; stdlib has neither. Argon2id encodes its work-factor parameters inside the hash string, so cost can be raised later with rehash-on-login rather than a migration. Rejected: bcrypt directly (silently truncates passwords at 72 bytes), passlib (unmaintained since 2020, breaks against bcrypt 4.x).
- **PyJWT** — `algorithms=[...]` is a *required* argument to `decode()`, so the allowlist SECURITY_SPEC §9 demands cannot be forgotten and `alg:none` is structurally impossible. Rejected: python-jose (slower releases, algorithm-confusion CVE history — the exact attack the spec lists second).
- **slowapi** — for login rate limiting. Chosen over a hand-rolled limiter on the user's reasoning: a dict-pruned-on-read window has a genuine read-then-write race under async, and nobody writes tests for a rate limiter at 2am. Defaults to an in-memory backend, so "no Redis" is the default path rather than a workaround, and the backend swaps later without touching call sites. Rate limiting will go in inline with login, not deferred to Phase 6.

**Risk engine** (`app/services/risk.py`) — pure, `Decimal` throughout, no DB or ORM:
- `assess_lines()` — the locked value-weighted formula, returning the score, the max line excess, order value, and a per-line breakdown so an approver can see *why* a quote scored what it did.
- `plan_approval_steps()` — reads bands from `approval_chains` and applies the single-line gate *on top* of whatever the bands return, so retuning the bands cannot silently disable the gate. Marks a gate-forced step so a low score with Finance attached does not look like a bug.
- `distribute_order_discount()` — the overwrite-not-stack rule from Locked Business Rules #4.

**Argon2id hashing** (`app/core/security.py`), including `needs_rehash` for the login-time upgrade path. `verify_password` returns False rather than raising on a malformed stored hash, so a corrupt row reads as "wrong password" instead of a 500 that confirms the account exists.

**Seed data** (`app/seed.py`) — idempotent by natural key: 5 roles, 16 permissions, 36 grants, 5 users (one per role), 3 customers, 3 categories, 7 products, 2 variants, 2 price lists with a volume break, the full 9-cell ceiling matrix, 3 approval-chain rows, 2 warehouses, 6 stock rows, 3 subscription plans, 7 upsell rules.

### Files Changed
- `backend/requirements.txt` (argon2-cffi, PyJWT, slowapi)
- `backend/app/core/security.py`
- `backend/app/services/risk.py`
- `backend/app/seed.py`
- `backend/tests/test_risk_engine.py`, `backend/tests/test_seed_data.py`
- `backend/tests/test_db_constraints.py` (role fixture now get-or-create)
- `README.md` (converted from UTF-16 to UTF-8; brought current)
- `PROJECT_CONTEXT.md`

### Important Decisions

- Decision: `requires_approval` derives from the unrounded per-line excess, not from `blended_score > 0`; and any non-zero raw score is floored at 0.01.
- Reason: a single line one point over its ceiling inside a very large order produces a raw score around 0.0005, which quantizes to 0.00 — a stored score claiming "no breach" for a quotation that has one, falling outside the `[0.01, 25)` Manager band and escaping approval entirely. A real breach must never round away to nothing.

- Decision: the single-line gate is applied on top of the band result, and the escalation step is taken from the configured chain rather than invented.
- Reason: it keeps the gate independent of whatever the band values happen to be, so an Admin retuning `approval_chains` cannot accidentally disable it, and the escalation role always matches what was configured.

- Decision: empty and zero-value quotations short-circuit to a zero score.
- Reason: the builder scores a half-built quotation live, and a `ZeroDivisionError` on the first line added would break the primary screen.

- Decision: seed stock is 6 in Main and 3 in East against a 10-unit demo order.
- Reason: one order then exercises both the warehouse split *and* a backorder, instead of needing two contrived scenarios. A test asserts these numbers so a later "helpful" top-up fails loudly.

### Validation
- Tests: **124 passed** (up from 69). 35 new risk-engine tests and 20 new seed tests.
  - Both PRD §10 worked examples reproduce exactly: the Laptop/Setup-Service case scores 1.33 → Manager, and the many-small-violations case scores 2.33 → Manager.
  - Every band boundary tested at its exact edge, independently of the demo scenarios — including score exactly 25.00, which must escalate (`>=`, not `>`); a `>` there would be invisible on every demo path.
  - The gate tested independently: not tripped at exactly 15 points over, tripped at 15.01, and forcing Finance on a 0.10 score where a severe small line is dwarfed by a large compliant one.
  - Rounding: half-up not banker's; a real breach floored to 0.01 rather than rounding away.
  - Seed tests drive the *real* engine from *real* seeded rows, so a typo in the matrix fails in CI rather than during the demo.
  - RBAC boundary tests: the customer role holds exactly two portal permissions and nothing else; only Finance holds `deal.approve_finance`; the rep holds no approval permission at all.
- Build: image rebuilds; argon2-cffi 25.1.0, PyJWT 2.13.0, slowapi present.
- Lint: `ruff check .` clean, `ruff format --check .` clean across 44 files.
- Manual verification: seed run three times consecutively with no duplicate rows; seeded ceiling matrix and approval chains inspected directly in psql and match the locked rules exactly.

**Three defects found and fixed:**
1. **Seed crashed with `MissingGreenlet`.** Assigning to `role.permissions` makes SQLAlchemy load the existing collection to diff against, and on a freshly inserted row that collection has never been fetched — under asyncio the implicit load raises instead of quietly issuing IO. Fixed with an explicit `session.refresh(role, ["permissions"])`.
2. **Seeding broke 14 constraint tests.** Their `role` fixture created a `sales_rep` row that now collides with the seeded one; `roles.code` is UNIQUE over a fixed enum, so unlike the other fixtures it cannot sidestep the collision with a generated code. Changed to get-or-create.
3. **README.md was UTF-16LE**, inherited from the original stub and preserved through later edits — every second byte NUL, so `grep` could not read it. Converted to UTF-8.

### Known Issues
- **FINDING: the `>= 25` approval band is unreachable.** The blended score is a value-weighted *mean* of the per-line excesses, so `score <= max_line_excess` always. Therefore `score >= 25` implies some line is at least 25 points over, which already tripped the `> 15` gate. Routing is correct and both demo paths work, but the band never independently decides anything. Options recorded in PROJECT_CONTEXT: lower the band below 15 so it can fire on a broad pattern of moderate breaches, or accept the gate as the sole Finance trigger. Encoded as a test that fails if the band is ever retuned below 15.
- `tests/test_seed_data.py` requires the seed to have been run; it fails with a pointed message rather than skipping.
- Demo passwords are shared across the five seeded accounts. Dev-only fixtures, overridable via `SEED_DEFAULT_PASSWORD`.

### Current State
The risk engine — the product's signature feature and the calculation the build is judged on — is implemented, exhaustively tested, and proven against the actual seed data. Demo data exists and is idempotent. Password hashing is ready.

No HTTP surface yet: no login, no quotation endpoints, no approval workflow. The engine is not yet wired to anything.

### Next Recommended Step
Continue Phase 3 in PLAN.md §8 order:
1. **Login** — JWT issue/verify with the algorithm allowlist, `slowapi` rate limiting on the endpoint, generic auth failures, `LOGIN_SUCCESS`/`LOGIN_FAILED` audit rows. Include the one-line comment at the signup endpoint explaining why it must never accept `customer_id`.
2. **Permission dependencies** in `app/api/deps.py` — `require_permission(...)` plus resource-ownership checks, so authorization lives in exactly one place.
3. **Quotation builder endpoints** — CRUD with live totals, margin and risk score computed through `assess_lines()`.
4. **Approval routing endpoints** — persisting `ApprovalRequest` and its steps from `plan_approval_steps()`.

---

## 2026-09-06 — Warehouse Split, Backorders and Fulfillment (Phase 3 step 5)

### Goal
Continue Phase 3 from PROJECT_CONTEXT.md's ordered backlog: multi-warehouse fulfillment
splitting and backorder handling (PRD B6, FRONTEND.md Screens 7-8), the next item after the
demo-prep detour. Also removed the demo-only click-to-fill login buttons per the user's
request, now that the interview demo phase is done and normal development resumes.

### Implemented

**Locked decision, recorded before writing code (PLAN.md §0.6):** a warehouse split can only
be generated once a quotation is `CONFIRMED`. The PRD has two slightly different sentences on
when fulfillment starts ("once approved..." vs "once confirmed..."); resolved in favour of
`CONFIRMED` because that is what the Phase 2 state machine was actually built around —
`CONFIRMED` is the sole legal predecessor of `FULFILLED`. Since the customer portal
negotiation screen (the real source of a "confirmed" quotation) is not built yet, a small
internal `POST /quotations/{id}/confirm` stand-in was added, explicitly documented as
temporary and to be retired once the portal exists.

**`app/services/fulfillment.py`** — mirrors `risk.py`'s shape:
- `compute_split()` — pure, no I/O. Greedy fill: lowest shipping-cost weight first, then
  highest available stock, then lowest warehouse id as a final deterministic tiebreak (the
  locked warehouse-selection rule from earlier in the backlog).
- `generate_fulfillment()` — locks every stock row for a product with `SELECT ... FOR UPDATE`
  (ordered by warehouse id, to give every caller the same lock order and avoid deadlocks),
  computes the split, and **reserves stock immediately in the same transaction** — not
  deferred to "accept". A line whose product has no `stock_levels` rows at all (a Service or
  Subscription) is skipped entirely, needing no warehouse.
- `accept_fulfillment()` — a pure status transition (no stock movement, since reservation
  already happened). Resolves to `FULFILLED` (no open backorder), `BACKORDERED` (nothing
  allocated), or `PARTIALLY_FULFILLED` in between, and only advances the quotation itself to
  `FULFILLED` once the fulfillment is fully covered.
- `override_fulfillment()` — releases every reservation on the touched lines, then re-reserves
  per the caller's chosen distribution, inside one transaction so no concurrent reader can
  observe stock in the gap between release and re-reserve. Validates against live stock under
  lock, so an override cannot itself oversell.
- `consolidate_backorder()` — PRD B6's "Consolidate Remaining Backorder" action. All-or-
  nothing: a partial restock that cannot fully cover the backorder leaves it open rather than
  silently shrinking `quantity_outstanding`.

**Endpoints** (`app/api/v1/endpoints/fulfillment.py`): `GET /fulfillment` (stock table +
orders awaiting fulfillment), `GET /fulfillment/{quotation_id}` (auto-generates the suggested
split on first view — no separate "compute" action to remember), `POST .../accept`,
`POST .../override`, `POST .../backorders/{id}/consolidate`. Gated by the existing
`fulfillment.manage` permission, already seeded to Finance/Ops in Phase 3 part 1.

**Frontend:** Screens 7 (`FulfillmentList.tsx`) and 8 (`FulfillmentDetail.tsx`) per
FRONTEND.md — stock table, orders-awaiting table, warehouse split table, Accept/Manual
Override actions (override renders an editable per-line, per-warehouse table populated from
live availability), backorders section with a Consolidate action. Added a "Confirm
Quotation" button to the builder so the whole chain is reachable by clicking, not just via
curl. Enabled the "Fulfillment" sidebar item (was `pending: true`).

**Removed:** the demo click-to-fill account buttons on the Login screen, per explicit user
request now that interview-demo prep is done. Plain email/password form remains, matching
FRONTEND.md Screen 1's actual spec.

**Also fixed while wiring this in:** `QuotationDetail.tsx`'s `editable` flag was permission +
ownership only, with no status check — a rep would see live-editable discount fields on an
*approved* quotation, which the backend would then reject with 409 on save. Now also requires
`status` to be `draft` or `rejected`, matching what the backend actually allows.

### Files Changed
- `backend/app/services/fulfillment.py` (new)
- `backend/app/api/v1/endpoints/fulfillment.py` (new)
- `backend/app/api/v1/endpoints/quotations.py` (added `POST /{id}/confirm`)
- `backend/app/api/v1/router.py` (wired the new router)
- `backend/app/models/audit.py` (four new `AuditAction` constants; two already existed)
- `backend/app/schemas/api.py` (fulfillment DTOs)
- `backend/tests/test_fulfillment.py` (new — 21 tests)
- `frontend/src/screens/FulfillmentList.tsx`, `FulfillmentDetail.tsx` (new)
- `frontend/src/screens/QuotationDetail.tsx` (Confirm button; `editable` status gate)
- `frontend/src/screens/Login.tsx` (demo buttons removed)
- `frontend/src/layouts/InternalShell.tsx`, `App.tsx` (Fulfillment routes/nav enabled)
- `frontend/src/lib/api.ts` (fulfillment types)
- `PROJECT_CONTEXT.md`, `IMPLEMENTATION_LOG.md`

### Important Decisions
- Decision: fulfillment trigger is `CONFIRMED`, not `APPROVED`, with a temporary internal
  confirm endpoint bridging the gap until the customer portal exists.
- Reason: `CONFIRMED` is the state machine's actual sole predecessor of `FULFILLED`; treating
  `APPROVED` as the trigger would generate fulfillments for quotations with no legal route to
  ever finish one.

- Decision: reserve stock at split *generation*, not at *accept*.
- Reason: a suggestion that only reserves on accept leaves a window where a second
  confirmation could be offered the same nominally-available stock. Locking and reserving in
  the same transaction as the computation is what makes the suggestion actually binding.

- Decision: a non-stocked product line (no `stock_levels` rows at all) is silently skipped by
  the split algorithm rather than erroring.
- Reason: Services and Subscriptions have nothing physical to ship; forcing them through
  warehouse logic would be modelling something that isn't there.

### Validation
- Tests: **145 backend tests pass** (124 prior + 21 new). Pure-logic coverage: the exact
  staged demo scenario (10 requested, 6+3 available → split + 1 backorder), shipping-weight
  ordering overriding raw stock quantity, both tiebreak levels (available stock, then
  warehouse id) tested independently, zero-candidate and zero-stock backorder cases, exact-
  match with no backorder, three-warehouse splits, and the shipping-cost estimate function.
  DB-level coverage: the CONFIRMED-status gate, actual reservation verified against
  `stock_levels` rows, duplicate-generation rejection, both `accept` outcomes (partially
  fulfilled vs. fully fulfilled, including that the *quotation* only advances on the latter),
  non-stocked products, and override's release-then-reserve with an oversell rejection.
- Lint: `ruff check .` clean, `ruff format --check .` clean. Frontend `tsc --noEmit` clean.
- Manual verification, against real seeded PostgreSQL (not assumed): two rounds of hand-
  written verification scripts (86 checks total, separate from the pytest suite) driving the
  actual HTTP API — reproducing the seed's own staged numbers exactly (Laptop: 6 from Main +
  3 from East + 1 backordered), confirming the reservation is real (`quantity_reserved`
  visible in the stock table afterward), idempotent viewing (second view doesn't duplicate),
  permission gating (rep 403, Finance 200), a fully-covered order going straight to
  `fulfilled`, the not-yet-confirmed 409 guard, backorder consolidation after a simulated
  restock, manual override redistributing correctly, and override rejecting an oversell
  attempt with a clear error rather than silently succeeding.
- Manual verification through the real UI, headlessly: signed in as the rep, built a 10-unit
  compliant order (discount 0%, skips approval), clicked Submit, clicked Confirm, and the
  Fulfillment Detail screen auto-generated and displayed exactly "Main Warehouse ... 6 units",
  "East Depot ... 3 units", and a "1.00 pt" open backorder — with no runtime errors. Then
  signed in as Finance in a second run, opened the same order, clicked "Accept Suggested
  Split", and the status badge correctly updated to "Partially Fulfilled".

**Two real bugs found and fixed during this work, both the same failure class:**
1. `consolidate_backorder()` set `backorder.status` directly without validating the
   transition through `assert_transition()`, unlike every other status change in the
   codebase. Not a live bug (both transitions it used are legal), but an unguarded one — the
   entire point of `state_machine.py` is that invalid transitions are *rejected*, not merely
   unused by accident. Fixed to call `assert_transition("Backorder", ...)` explicitly for
   both the `OPEN → CONSOLIDATED` and `CONSOLIDATED → FULFILLED` hops.
2. `generate_fulfillment()` returned its `Fulfillment` object without refreshing its
   `splits`/`backorders` relationship collections. Every split/backorder was added via bare
   `session.add(...)`, not `fulfillment.splits.append(...)`, so the in-memory collection
   stayed empty until something re-queried it. The API endpoints always called
   `load_fulfillment()` again afterward and never noticed; the new pytest tests, calling
   `generate_fulfillment()` directly, hit `MissingGreenlet` immediately on the very first
   attempt to read `.splits`. This is the exact same failure class as the `auth.py`
   `_USER_LOADS` bug from Phase 3 part 1 — fixed the same way, with an explicit
   `session.refresh(fulfillment, attribute_names=["splits", "backorders"])` before return,
   and written up in "Do Not Change" as a standing rule for any future service function of
   this shape.

### Known Issues
- **Consolidating a backorder is a manual action**, not the automatic "prompt appears" PRD B6
  describes. The manual endpoint is what that prompt would call; nothing yet watches for a
  restock and surfaces it unprompted — needs a background job, not built.
- **`DEMO.md` does not yet cover this flow.** It still only documents the two approval-routing
  flows from Phase 3 part 1. The fulfillment flow's exact expected numbers are recorded here
  and in Locked Business Rules #7 instead; `DEMO.md` should be extended before the next demo
  that needs to show it.
- The internal `POST /quotations/{id}/confirm` endpoint is a deliberate, temporary stand-in —
  see Locked Business Rules #7. It should be retired or restricted once the customer portal
  negotiation screen exists.
- `estimated_shipping_cost` is a simple `quantity × shipping_cost_weight` proxy, not a real
  costing model — the PRD never specifies one, and weight is defined only as what drives the
  split, not a currency figure.

### Current State
Phase 3 steps 1-5 and 8 are complete. A rep can build a compliant quotation, submit it
(skipping approval when nothing breaches a limit), confirm it, and see a warehouse split
suggestion appear automatically — split across warehouses correctly, backordering whatever's
left, with Finance able to accept, manually override, or consolidate a backorder once stock
arrives — all verified against the real database and the real UI, not assumed.

### Next Recommended Step
**Hybrid billing + proration** (PRD B7, backlog item 1). One prerequisite noted previously
still stands: `quotation_lines` requires a subscription line to carry a plan, but the builder
has no plan picker yet, so a subscription product cannot currently be added to a quote — that
gap needs closing before proration logic has anything to operate on.

---

## 2026-09-06 — Full Document Audit: Security Checklist, State-Machine Guards, Stale Docs

### Goal
User asked to re-analyze all the source-of-truth documents against the current codebase and
fix whatever bugs that turns up, rather than continuing straight to the next feature. Treated
as a proper audit pass: check every claim, don't just re-read and assume.

### Implemented

**1. Hunted for more instances of the bug class already found twice** (auth.py's
`_USER_LOADS`, `generate_fulfillment`'s missing refresh). Grepped every direct `.status = `
assignment across the service and endpoint layers and checked each one against a preceding
`assert_transition()` call.

Found one real gap: `ApprovalRequest.status` was set directly in `approvals.py`'s `decide()`
endpoint (three branches — approved/rejected/returned) with no `assert_transition()` call,
unlike the `ApprovalStep.status` change three lines above it and the `Quotation.status`
change below it in the same function. Not a *live* bug — by the time that code runs,
`request.status` is provably `PENDING` (checked earlier in the same function), and all three
outcomes are legal from `PENDING`. But it is exactly the pattern the "Do Not Change" rule
written after the last bug warns about: correct by circumstance, not provably guarded. Fixed
by factoring the three branches through one `_finish_request()` helper that calls
`assert_transition("Approval", ...)` before writing the status, matching every other status
change in the codebase.

Checked every other direct `.status =` write (`fulfillment.py` x4, `quotations.py` x2): all
were already correctly preceded by `assert_transition()`.

**2. Confirmed the bare-`session.add()`-without-refresh pattern is fully closed.** All three
functions in `fulfillment.py` that add child rows via `session.add()` rather than
`parent.children.append()` (`generate_fulfillment`, `override_fulfillment`,
`consolidate_backorder`) correctly call `session.refresh(fulfillment, attribute_names=[...])`
before returning. Checked `approval.py`'s `raise_approval_request` and `quotation.py`'s line
replacement too — both are safe because neither returns the ORM parent object for a caller to
read a stale collection off of; callers re-fetch with `load_quotation()`/`load_fulfillment()`
afterward.

**3. Grepped for locked-rule violations.** No bare `round()` calls and no `float()` used for
money/percentage arithmetic anywhere in `app/`. The `Decimal` + `ROUND_HALF_UP` rule (Locked
Business Rules #3) holds everywhere it applies.

**4. Full item-by-item audit of SECURITY_SPEC.md Section 11's pre-submission checklist**,
verified against the actual code rather than assumed from memory:

| Item | Status | Evidence |
|---|---|---|
| Passwords Argon2id, never plaintext/logged | ✅ | `core/security.py` |
| JWT algorithm whitelisted, `alg:none` rejected | ✅ | `core/tokens.py` — `algorithms=` is a required `jwt.decode()` argument |
| Access tokens short-lived, refresh rotated | ✅ | 15 min access; `rotate_refresh_token()` with reuse detection |
| JWT payload has no PII/secrets | ✅ | payload is `sub`/`jti`/`type`/`iat`/`exp`/`iss`/`aud` only |
| `exp`/`iss`/`aud` validated | ✅ | `jwt.decode(..., issuer=, audience=, options={"require": [...]})` |
| Login/reset/MFA rate-limited | ⚠️ partial | Login + refresh limited via slowapi; reset and MFA are not built at all (outside PRD scope) — nothing to rate-limit yet, recorded rather than silently checked off |
| All 5 roles enforced server-side | ✅ | Permission-based via seeded `role_permissions`, checked in `api/deps.py` |
| Resource-ownership checked on quotation/approval endpoints | ✅ | `assert_can_view/edit_quotation` used consistently — **also confirmed for the newer fulfillment endpoints during this audit**, which hadn't been explicitly checked against this checklist before |
| No client-supplied `role`/`ownerId`/`customerId` trusted | ✅ | `owner_id` always derived from `user.id`; signup ignores any `role` in the body |
| All approval/rejection/edit actions audited | ✅ | confirmed for quotations, approvals, and fulfillment actions |
| CORS explicit allowlist | ✅ | two explicit origins in `.env`, no wildcard |
| No secrets committed | ✅ | `.env` gitignored, only `.env.example` tracked |
| DB queries parameterized/ORM-only | ✅ | grepped `app/` — no raw string SQL anywhere |
| API errors don't leak internals | ✅ | generic handlers in `core/errors.py`, covered by `test_error_response_does_not_leak_internals` |

**13 of 14 fully verified, 1 partial for a reason (feature doesn't exist yet), 0 failures.**
This had never actually been checked off anywhere despite PROJECT_CONTEXT.md claiming it was
"tracked in IMPLEMENTATION_LOG.md" — that claim was itself stale until this entry.

**5. Fixed two stale documentation claims in PROJECT_CONTEXT.md:**
- The warehouse selection tie-break was still listed under "Still open... proceeding on this
  assumption," despite being fully implemented and unit-tested as part of the fulfillment
  feature. Moved to "Resolved."
- The JWT security checklist reference pointed at a tracking entry that never existed until
  this one.

### Files Changed
- `backend/app/api/v1/endpoints/approvals.py` (guarded `ApprovalRequest.status` transitions)
- `PROJECT_CONTEXT.md` (two stale-claim fixes)
- `IMPLEMENTATION_LOG.md`

### Important Decisions
- Decision: audit by grepping for the exact mechanical pattern of two already-found bugs
  (unguarded status writes; bare-add-without-refresh), rather than re-reading files hoping to
  spot something.
- Reason: "read the docs again" does not reliably surface the same class of bug a second
  time; a targeted, repeatable search across the whole codebase does, and did — it found a
  real instance the first two passes missed.

### Validation
- Tests: **145 backend tests still pass** after the `approvals.py` fix — no regression.
- Re-ran the full 56-check API verification script (login, PRD-example approval, two-step
  Manager+Finance chain, reject, return-for-revision, security/IDOR checks) against a freshly
  reset seed, specifically because the fix touched the exact function handling all of those
  outcomes. All 56 still pass.
- `ruff check .` clean.

### Known Issues
No new ones. The rate-limiting partial (item 6 above) is a scope statement, not a defect —
password reset and MFA are not PRD requirements for this build.

### Current State
No functional behaviour changed for any user-visible flow — every one of the transitions this
audit touched was already reachable only via the paths the state machine allows. What changed
is that those paths are now provably guarded rather than incidentally correct, which is the
exact standard `state_machine.py` was built to (PLAN.md Section 7: "invalid transitions must
be rejected, not just unused"). Documentation now says only things that are currently true.

### Next Recommended Step
Unchanged: hybrid billing + proration (PRD B7), blocked first on adding a subscription-plan
picker to the quotation builder so a subscription line can be created at all.
