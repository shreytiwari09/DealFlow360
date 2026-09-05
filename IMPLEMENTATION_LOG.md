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

---

## 2026-09-06 — Rotate Postgres and JWT Secrets to Real Values

### Goal
User asked to move off the dev placeholder secrets (`POSTGRES_PASSWORD=change-me-locally`,
`JWT_SECRET_KEY=dev-only-not-a-real-secret-replace-before-any-deploy`) to real, cryptographically
generated values, without losing the data already seeded in the running database.

### Implemented
Generated both secrets with `secrets.token_urlsafe()` (32 bytes for the Postgres password, 48
for the JWT signing key) run inside the backend container, so the values were never typed by a
human and are never printed in full anywhere in this log or in the terminal transcript.

Postgres only applies `POSTGRES_PASSWORD` when its data volume is first initialized — changing
`.env` alone would leave the actual database role's password unchanged while the app tried to
authenticate with the new one. Applied the new password live instead:
`ALTER USER dealflow WITH PASSWORD '<new>';` run directly against the running `db` container,
which changes the role in place with zero data loss. Verified row counts (`users`, `quotations`)
before and after — unchanged.

Updated `.env` with both new values, then hit a second real gotcha: `docker compose restart
backend` does **not** re-read `.env` — it recreates the process but reuses the container's
already-resolved environment from when it was created. The app kept authenticating with the
stale password and 500'd (`asyncpg.exceptions.InvalidPasswordError`). Fixed by using `docker
compose up -d backend` instead, which recreates the container and re-resolves its environment
from the current `.env`.

### Files Changed
- `.env` (gitignored, not committed — values not reproduced here)

### Important Decisions
- Decision: rotate the Postgres password via `ALTER USER` against the live database rather than
  recreating the `db` volume.
- Reason: recreating the volume is destructive (wipes all seeded and demo data); `ALTER USER` is
  the data-preserving equivalent and is exactly what a real production rotation would do.

### Validation
- Manual verification: health check returned `{"status":"ok",...,"database":"ok"}` after the
  fix; logged in successfully as `rep@dealflow360.example`; `SELECT count(*) FROM users` still
  returned 5 (unchanged) before and after; confirmed `.env` remains gitignored via `git
  check-ignore -v .env`.

### Known Issues
Rotating the JWT signing key invalidates every previously issued access/refresh token — any
browser tab still signed in from before this change needs to sign in again. Expected and
correct, not a defect.

### Current State
The stack now runs on real, non-placeholder secrets for both Postgres and JWT signing, with no
data loss. `.env.example` still documents the placeholder shape for a fresh clone to fill in
its own values.

### Next Recommended Step
Hybrid billing + proration (PRD B7) — unchanged from the previous entry.

---

## 2026-09-06 — Hybrid Billing and Proration (Phase 3 step 6)

### Goal
Implement the last item in Phase 3's core backlog: hybrid billing (one-time + recurring lines
on a single order) with mid-cycle proration, per PRD B7 and the formula locked in
PROJECT_CONTEXT.md Locked Business Rules #3. Closes the prerequisite gap noted in every prior
entry's "Next Recommended Step": the builder had no subscription-plan picker, so a subscription
product could not be added to a quote at all.

### Implemented

**1. Closed the plan-picker gap.** `LineRequest` gained `subscription_plan_id`. `replace_lines`
now validates it against the product's real `item_type` — a subscription product without a
valid, active plan id is rejected (422), and a one-time product WITH one is equally rejected,
rather than silently accepted or silently dropped. `_default_plan_id`, the stub that always
returned `None`, is gone. `GET /catalog/subscription-plans` (used by both the builder's picker
and the new billing screens) and `QuotationLineResponse.subscription_plan_id/_name` (so the
builder can show and edit the current selection, not just set it once) round out the gap.

**2. `app/services/billing.py`** — mirrors `risk.py`'s and `fulfillment.py`'s shape:
- `compute_proration()` — pure, no I/O. Daily basis, `ROUND_HALF_UP` to 2dp, exactly the locked
  formula. Reproduces the locked worked example's *intent* exactly (see Important Decisions for
  a correction to the example's own numbers).
- `add_billing_interval()` — pure calendar-month arithmetic for advancing a plan's cycle
  (monthly/quarterly/yearly x `interval_count`), clamping day-of-month for shorter/leap-adjacent
  months (Jan 31 + 1 month lands on Feb 28/29, never overflows into March).
- `generate_billing_for_quotation()` — called from the same `CONFIRMED` transition that unlocks
  fulfillment (Locked Business Rules #7's precedent: CONFIRMED is where every other part of this
  system treats the order as real). Creates one `one_time` `BillingSchedule` row covering every
  one-time line's tax-inclusive total, plus one `Subscription` + first-cycle `recurring`
  `BillingSchedule` row per subscription line. Idempotent, same guard shape as
  `generate_fulfillment`.
- `modify_subscription()` / `cancel_subscription()` — mid-cycle quantity/plan change and
  cancellation, both priced via `compute_proration()` and both recording a `ProrationRecord`
  with every input alongside the result (Locked Business Rules #3's explicit requirement). A
  plan's `refund_policy` (`none`/`prorated`/`full`) governs what cancellation credits.
- `issue_invoice()` / `record_payment()` — `SCHEDULED -> INVOICED -> PAID`, each transition
  guarded by `assert_transition()` like everything else in this codebase. Full-payment model:
  no partial-payment ledger, matching PLAN.md's own quick-test flow ("record a payment, check
  the invoice status updates").

**3. Endpoints** (`app/api/v1/endpoints/billing.py`, prefix `/billing`): subscriptions
list/detail/modify/cancel, invoices list/detail/issue/payments. View is open to any internal
role, scoped by ownership the same way the quotations list is (a rep sees only their own
orders' billing); every mutating action requires `billing.manage` (Finance/Ops + Admin), per
FRONTEND.md's own "Roles" line for Screens 9-10 and 12-13.

**4. Frontend:** Screens 9 (`SubscriptionsList.tsx`), 10 (`SubscriptionDetail.tsx` — the
two-table one-time/recurring layout PRD B7 calls for, plus Modify/Cancel and the proration
history table), 12 (`InvoicesList.tsx`), 13 (`InvoiceDetail.tsx` — Scheduled → Invoiced → Paid
stepper, Issue Invoice and Record Payment actions). The quotation builder (Screen 4) gained a
Plan column with a picker for subscription lines. Enabled the "Subscriptions" and "Invoices"
sidebar items (were `pending: true`).

### Files Changed
- `backend/app/services/billing.py` (new)
- `backend/app/api/v1/endpoints/billing.py` (new)
- `backend/app/api/v1/endpoints/quotations.py` (plan-id validation; billing generation on confirm)
- `backend/app/api/v1/endpoints/catalog.py` (`GET /subscription-plans`)
- `backend/app/api/v1/router.py` (wired the new router)
- `backend/app/services/quotation.py` (eager-load `QuotationLine.subscription_plan`)
- `backend/app/models/audit.py` (`BILLING_SCHEDULE_GENERATED`, `INVOICE_ISSUED`)
- `backend/app/schemas/api.py` (billing DTOs; `subscription_plan_id` on `LineRequest` and
  `QuotationLineResponse`)
- `backend/tests/test_billing.py` (new — 25 tests)
- `frontend/src/screens/SubscriptionsList.tsx`, `SubscriptionDetail.tsx`, `InvoicesList.tsx`,
  `InvoiceDetail.tsx` (new)
- `frontend/src/screens/QuotationDetail.tsx` (Plan column and picker)
- `frontend/src/layouts/InternalShell.tsx`, `App.tsx` (routes/nav enabled)
- `frontend/src/lib/api.ts`, `frontend/src/components/ui.tsx` (billing types; new status tones)
- `PROJECT_CONTEXT.md`, `IMPLEMENTATION_LOG.md`

### Important Decisions

- **Correction to the locked worked example.** PROJECT_CONTEXT.md's Locked Business Rules #3
  worked example claimed credit 800.04 / charge 1200.06 / proration 400.02 for "1200 upgraded to
  1800 on day 10 of a 30-day cycle." The exact fraction there is 20/30 = 2/3, and 1200 x 2/3 =
  800 exactly (1200/3 x 2), not 800.04 — the original numbers came from hand-rounding 0.666... to
  "0.6667" before multiplying, an artifact of doing the arithmetic by hand rather than an
  intentional part of the formula. The FORMULA itself was never in question (daily basis,
  `ROUND_HALF_UP` on the final `proration` figure) — only the example's own arithmetic was wrong.
  Corrected the worked example in PROJECT_CONTEXT.md and added
  `test_locked_worked_example_exactly` plus a second test
  (`test_rounding_is_half_up_not_bankers_rounding`, 17 x 1/8 = 2.125 exactly) that actually
  exercises a genuine rounding tie, since the original example turned out to have none.

- Decision: billing generation triggers at `CONFIRMED`, the same point fulfillment does.
- Reason: consistency with Locked Business Rules #7's own reasoning — CONFIRMED is the state
  machine's agreed "this order is now real" point everywhere else in the codebase; inventing a
  second trigger point for billing specifically would be arbitrary.

- Decision: cancellation refund behavior branches on the plan's `refund_policy` (none/prorated/
  full), with `full` crediting the entire current-cycle amount regardless of days remaining.
- Reason: the model already commits to three named policies (PRD A5); implementing only
  `prorated` and silently treating `full`/`none` the same would make two of three seeded values
  meaningless.

- Decision: Screen 10 (Billing Detail) fetches the order's other invoice rows client-side by
  filtering `GET /billing/invoices` on `quotation_id`, rather than adding a dedicated
  "one-time lines for this subscription's order" backend endpoint.
- Reason: at this data scale a second network call plus a client-side filter is simpler than a
  new endpoint shape, and keeps `/billing/subscriptions/{id}`'s response scoped to what it's
  actually named for — that one subscription.

### Validation
- Tests: **170 backend tests pass** (145 prior + 25 new). Pure-logic coverage: the corrected
  worked example, a downgrade (negative proration = credit note), change on the first/last day
  of a cycle, an out-of-cycle change date rejected, `cycle_end <= cycle_start` rejected, a
  genuine `ROUND_HALF_UP` vs. banker's-rounding tie, and `add_billing_interval` across
  monthly/quarterly-with-count/yearly/leap-year/short-month cases. DB-level coverage: a hybrid
  quotation generates both schedule types correctly, generation is idempotent, a subscription-
  only order skips the one-time row, quantity/plan modification produces a correct proration
  record and settles back to ACTIVE, all three refund policies on cancel, double-cancel
  rejected, issue-then-pay settles an invoice, payment-before-invoicing rejected, invoice
  numbers are sequential.
- `ruff check .` / `ruff format --check .` clean. Frontend `tsc -b && vite build` clean.
- Manual verification against real seeded PostgreSQL via a 40-check hand-written script driving
  the actual HTTP API end to end: plan-picker validation in both directions (subscription line
  without a plan rejected, one-time line with a plan rejected), a real hybrid order (one-time
  Monitor + subscription Premium Support) built, submitted (skips approval, no discount),
  confirmed, and its billing schedule inspected; quantity modify producing a positive proration
  and settling back to `active`; issue → pay settling an invoice to `paid`; cancel producing a
  negative (credit) proration; double-cancel rejected; and the rep's own view-only access to
  their own order's subscriptions/invoices (`can_act: false`) confirmed separately from
  Finance's full access.

**One real bug found and fixed during this work, the same failure class as before but in a new
shape:** `modify_subscription()`, `cancel_subscription()` and `record_payment()` each added a
child row (`ProrationRecord`, an adjustment `BillingSchedule`, a `Payment`) via `session.add(...)`
rather than the parent's relationship `.append(...)` — the now-familiar pattern. What made this
instance new: the *unit tests* didn't catch it, because each test called the service function
directly and inspected the *returned* record, never the parent object's collection. The 40-check
live-API script did catch it immediately, because the API layer re-fetches the parent inside the
*same request session* right after committing — and since that parent object was already sitting
in the session's identity map (loaded once, earlier in the same request, with the affected
collection eager-loaded as empty), a second `SELECT ... selectinload(...)` does not force a
reload of an already-populated collection on an identity-mapped object. The commit succeeded and
the row genuinely existed in the database; the in-memory object handed back to the client just
still showed the pre-write snapshot. Fixed with an explicit `session.refresh(parent,
attribute_names=[...])` at the end of all three functions, matching `generate_fulfillment`'s
existing fix — and added regression assertions to the unit tests that read the collection off
the *same* object `modify_subscription`/`cancel_subscription`/`record_payment` was given,
which is the only way those tests could have caught this themselves.

### Known Issues
- Screen 10's two-table layout is assembled from two separate API calls
  (`/billing/subscriptions/{id}` + a client-side filter of `/billing/invoices`) rather than one
  purpose-built response — see Important Decisions. Fine at this data scale; would need
  revisiting if an order's invoice list ever got large enough to paginate.
- No background job renews a subscription's cycle when `current_cycle_end` passes, or notifies
  anyone a recurring instalment is due — both would need a scheduler, out of scope here (same
  category of gap as fulfillment's "backorder consolidation isn't automatically prompted").
- The frontend's Modify Subscription form always shows the full plan list, including the plan
  the subscription is already on — harmless, but means "no plan change" always sends
  `new_plan_id` equal to the current value rather than omitting it, which the backend already
  ignores as a no-op.
- Full browser click-through (as opposed to the 40-check live-API script, which exercises the
  same endpoints the UI calls) was not run this round for the four new screens — `tsc -b && vite
  build` confirms they compile and type-check against the real API responses, but no one has
  clicked through them in an actual browser yet.

### Current State
Phase 3 is now complete end to end: a rep can build a hybrid quotation (one-time + subscription
lines), submit, confirm, and see fulfillment and billing both generate automatically at the same
trigger point. Finance can accept/override a warehouse split, modify or cancel a subscription
with correct mid-cycle proration, and take an invoice through Scheduled → Invoiced → Paid. Every
number involved — risk score, proration, invoice amounts — is computed with `Decimal` and an
explicit rounding rule, never `float` or the builtin `round()`.

### Next Recommended Step
PROJECT_CONTEXT.md's backlog, next two items: (1) Customer portal negotiation (PRD B8, Screen
11) — the portal shell exists and correctly refuses internal screens, but the negotiation screen
itself is still a placeholder; (2) Upsell panel wired to real `upsell_rules` data (PRD B5) — 7
rules are seeded but the builder currently just shows promoted products as a stand-in.

---

## 2026-09-06 — Customer Portal Negotiation (PRD B8, Screen 11) — Phase 3 complete

### Goal
Implement the last item in Phase 3's core backlog: the customer-facing negotiation screen, per
PRD B8 and FRONTEND.md Screen 11. Before writing code, three genuine ambiguities were confirmed
with the user (PLAN.md §0.6 — see Locked Business Rules #8 for the full reasoning):
(a) a counter-offer is an order-level discount, comments are free text; (b) negotiation history
is stored in `audit_logs` (reusing the existing `PORTAL_COUNTER_OFFER` action), not a new table;
(c) "Requested Delivery Date" is informational, folded into the comment text, no new column.
Also confirmed: the temporary internal `POST /quotations/{id}/confirm` stand-in (Locked Business
Rules #7) should now be restricted to Admin, as its own docstring always said it should be once
this screen existed.

### Implemented

**1. `app/services/portal.py`** — the customer's two actions, deliberately built on the SAME
code paths an internal user's equivalent action uses, not a parallel set of rules:
- `submit_counter_offer()` — "Submit Request." A counter discount is written onto every line
  exactly like the internal order-level discount (Locked Business Rules #4), then re-scored by
  the same `recalculate()`. A comment-only request (no counter) still moves `sent -> under_
  negotiation` but changes no numbers.
- `confirm_from_portal()` — "Confirm Quotation," including PRD B8's automatic re-approval loop:
  re-scores the current terms, and either raises a NEW approval request (decided approvals are
  terminal) or calls the same `quotation.confirm()` the Admin override uses, so billing
  generation can never drift between the two paths.
- `terms_already_approved()` — the one genuinely subtle rule (Locked Business Rules #8d): a
  quotation approved at 18% and then sent still SCORES as breaching when re-scored on confirm,
  because nothing about it changed. Routing on the score alone would bounce it back to the same
  manager forever, and no quotation that ever needed an approval could ever be confirmed. Instead,
  an approval is required unless a PREVIOUS `ApprovalRequest` that reached `APPROVED` for this
  quotation matches **both** the current `blended_risk_score` and `max_line_excess` exactly — a
  counter that changes either number correctly re-enters approval; identical terms do not.

**2. `app/services/quotation.py`** gained `confirm()`, the single shared implementation of
"transition to CONFIRMED and generate billing," used by both the portal and the now-restricted
internal override — two copies of this would eventually disagree about whether billing was
generated.

**3. Endpoints** (`app/api/v1/endpoints/portal.py`, prefix `/portal`): a genuinely separate
surface per PLAN.md and the PRD's own technical guidelines — every route requires a `portal.*`
permission no internal role holds, every query is scoped by `customer_id` from the token (never
the request), and every response uses portal-only schemas with no internal field to leak
(`allowed_discount_percent`, `margin_*`, `blended_risk_score`, `owner_name` etc. simply do not
exist on `PortalQuotationDetailResponse`). Internal statuses are mapped down to the three PRD
names ("Sent, Under Negotiation, Confirmed") rather than shown verbatim.

**4. Internal confirm endpoint restricted.** `POST /quotations/{id}/confirm` now requires a new
`deal.confirm_override` permission, seeded to Admin only — gated by *permission*, not a role
check, per SECURITY_SPEC.md Section 4 (Admin holds it only because Admin is seeded with every
permission).

**5. Frontend:** `PortalShell.tsx` (a completely separate shell — no sidebar, no internal nav,
matching the wireframe's own separate top bar), `PortalQuotationsList.tsx` ("My Quotations," the
minimum viable list FRONTEND.md Section 2.2 calls for), `PortalQuotationDetail.tsx` (Screen 11 —
lines, comment thread, Counter Discount % + Requested Delivery Date fields, Submit Request /
Confirm Quotation). The old `PortalPlaceholder` in `App.tsx` is gone.

### Files Changed
- `backend/app/services/portal.py` (new)
- `backend/app/api/v1/endpoints/portal.py` (new)
- `backend/app/services/quotation.py` (`confirm()`)
- `backend/app/api/v1/endpoints/quotations.py` (confirm endpoint restricted + reuses `confirm()`)
- `backend/app/services/state_machine.py` (`approved -> under_negotiation` edge — see below)
- `backend/app/schemas/api.py` (portal DTOs)
- `backend/app/seed.py` (`deal.confirm_override` permission, Admin only)
- `backend/tests/test_portal.py` (new — 15 tests)
- `frontend/src/layouts/PortalShell.tsx` (new)
- `frontend/src/screens/PortalQuotationsList.tsx`, `PortalQuotationDetail.tsx` (new)
- `frontend/src/App.tsx` (portal routes; removed `PortalPlaceholder`)
- `frontend/src/lib/api.ts`, `frontend/src/styles/app.css` (portal types and shell styles)
- `PROJECT_CONTEXT.md`, `IMPLEMENTATION_LOG.md`

### Important Decisions
See Locked Business Rules #8 (a-e) in full. The one decision made mid-implementation rather
than up front:

- Decision: `approved` is a negotiable status, with a new `approved -> under_negotiation`
  state-machine edge.
- Reason: found live, not designed for. PRD B3's own flow has no "send to customer" step after
  an internal approval clears — a quotation that needed approval before it ever reached the
  customer sits at `approved`, not `sent`. The first cut of `NEGOTIABLE_STATUSES` followed PRD
  B8's wording literally (`sent`, `under_negotiation` only) and the live-API script immediately
  showed the consequence: a rep-approved quote could never reach the customer at all, and a
  quote that re-entered approval via a counter-offer would land back on `approved` with no path
  forward. See Known Issues below for how this was caught.

### Validation
- Tests: **185 backend tests pass** (170 prior + 15 new). Coverage: counter-offer moves
  `sent -> under_negotiation`; a counter discount lands on every line and is re-scored; a
  comment-only request changes no numbers; a second counter round does not re-assert an
  already-satisfied transition; negotiating a draft is rejected; a compliant confirm goes
  straight to `confirmed`; a breaching confirm re-enters approval with a NEW request (not a
  reopened one); `terms_already_approved` both fires correctly (identical terms skip
  re-approval) and correctly does NOT fire on a changed-but-still-breaching counter or a
  REJECTED (not APPROVED) prior request; confirming generates billing via the same
  `quotation.confirm()` the Admin path uses; double-confirm rejected; and the `approved`-status
  regression itself, both confirming and re-negotiating from `approved` directly.
- `ruff check .` / `ruff format --check .` clean. Frontend `tsc -b && vite build` clean.
- Manual verification against real seeded PostgreSQL via a 29-check hand-written script driving
  the actual HTTP API end to end, including the full realistic loop: rep builds a compliant
  Services-line order → submits (skips approval) → customer comments (no number changes) →
  customer counters to a breaching 20% → customer confirms → **re-enters approval automatically**
  → verified INTERNALLY that the status really is `pending_approval` and a new `ApprovalRequest`
  exists, with the audit trail showing the customer-counter-offer origin → manager approves →
  customer confirms AGAIN on now-approved terms → `terms_already_approved` correctly lets it
  through straight to `confirmed` with no second approval cycle → billing generated. Also
  verified: an internal user gets 403 from every `/portal/*` route; a customer cannot see a
  draft quotation (404, not 403 — existence itself is not revealed); portal responses contain
  no internal field; a rep gets 403 from the internal confirm override, Admin does not.

**Two real issues found via the live-API script, neither caught by the unit tests written
first (both are now covered by added tests/fixes):**
1. **The `approved` status gap** described above under Important Decisions — a real, would-have-
   shipped design gap, not a code bug. The unit tests exercised exactly the statuses
   `NEGOTIABLE_STATUSES` already listed, so they could not have caught an omission from that
   same list; only driving the real approval-then-reconfirm loop end to end surfaced it.
2. **Display-precision cosmetic**: a counter discount of `20` (parsed by Pydantic from bare JSON,
   not DB-round-tripped) printed as `"20"` instead of `"20.00"` until the row was next read from
   Postgres — the same class of issue fixed for subscription quantity in the previous session's
   billing work, now fixed here via `services/portal.py`'s `_percent()`. Noted in
   PROJECT_CONTEXT.md Known Issues as likely present elsewhere (the internal order-level discount
   endpoint uses the identical pattern) but not swept project-wide this round.

### Known Issues
- The `apply_order_discount` endpoint likely has the same display-precision cosmetic as the one
  fixed here — not swept this round; tracked in PROJECT_CONTEXT.md Known Issues.
- No full browser click-through of the new portal screens yet — `tsc -b && vite build` confirms
  they compile and type-check against the real API responses, but nobody has clicked through
  them in an actual browser. Same gap noted for the billing screens in the previous entry.
- `Messages` and `Profile` in the portal top nav are rendered disabled, matching FRONTEND.md
  Section 2.2's instruction not to invent screens the wireframe never specified content for.
- `DEMO.md` still does not cover fulfillment, billing, or now portal negotiation — three real
  flows undocumented there. Worth a dedicated pass before the next live demo.

### Current State
**Phase 3 (Core Business Workflow) is now fully complete** — every 🔴 Core item in PLAN.md's
own classification is implemented, tested, and verified against the real running system. A rep
can build a hybrid quotation, get it auto-routed for approval, fulfilled across warehouses, and
billed with correct proration; a customer can view their own quotation, negotiate a discount,
and confirm it — with a breaching counter-offer automatically and correctly routing back through
the exact same approval machinery a first-time submission uses, including not looping forever on
terms that are already approved.

### Next Recommended Step
Everything remaining is 🟡 Supporting scope (PROJECT_CONTEXT.md's "Remaining Work"): (1) Upsell
panel wired to real `upsell_rules` data (PRD B5) — 7 rules seeded, builder currently shows
promoted products as a stand-in; (2) Deal health dashboard — blocked on anomaly thresholds still
being undefined; (3) Reporting with filters + export; (4) Admin config screens for discount
tiers/approval chains — data is already configurable via the API, only the UI is missing.

---

## 2026-09-06 — Gap Sweep, Order-Level Discount UI, Upsell Panel, DEMO.md Rewrite

### Goal
User asked to fix the gaps recorded in the previous entries' Known Issues, then continue
building the next backlog item. Three gaps closed: the display-precision cosmetic (noted but
not swept in the portal session), the missing Order-Level Discount UI (deferred since Phase 3
began), and `DEMO.md` not covering fulfillment/billing/portal. Then implemented the top
"Remaining Work" item: the Upsell & Cross-Sell panel wired to real `upsell_rules` data (PRD A6,
B5), closing out everything that was flagged as a stand-in.

### Implemented

**1. Display-precision sweep.** Added `quantize_percent()` to `app/services/quotation.py`
(matching the shape of `services/billing.py`'s `_qty()` and `services/portal.py`'s `_percent()`
from the previous two sessions) and applied it everywhere a `discount_percent` is set directly
from a request body: `replace_lines` and `apply_order_discount`. A project-wide grep for the
same pattern (a `Numeric(...)` column assigned straight from a Pydantic field) found no further
occurrences.

**2. Order-Level Discount UI** (Locked Business Rules #4). The endpoint has existed and been
tested since Phase 3; the builder never had a control for it. Added one: a percentage input and
an "Apply to all lines" button, gated behind a `window.confirm` warning that it overwrites every
line's discount — the same destructive-action pattern already used for Approval's Reject and
the portal's Cancel Subscription.

**3. `app/services/upsell.py`** — pure ranking/filtering, mirroring `risk.py`'s shape:
- `rank_suggestions()` — suppresses any candidate below its own margin floor, then sorts by
  `is_promoted` (primary key, per `app/models/upsell.py`'s own docstring) then
  `co_purchase_score` (tiebreaker).
- `product_margin_percent()` — a product's own `(list_price - cost_price) / list_price`.
- `margin_delta_if_added()` — PRD B5's live "margin delta if added" figure, computed by
  simulating exactly the line `addProduct()` in the builder would create (qty 1, 0% discount) —
  the number shown is the number that would actually appear a moment after clicking "+ Add",
  not a guess computed some other way.

**One documented judgment call, not raised as a question:** `upsell_rules.min_margin_percent`'s
own docstring says the "live margin delta... must clear `min_margin_percent`," which read
literally would compare the floor against the small delta figure above. The seeded floors
(10-20) only make sense as plausible *product* margin percentages, not as swings in a blended
order margin (normally a few points at most), so the floor is compared against
`product_margin_percent()` instead. Low-stakes and reversible — implemented and documented
rather than pausing to ask, per PLAN.md §0.6's own allowance for a defensible default.

**4. `GET /quotations/{id}/upsell` endpoint.** Loads the quotation's current products as
triggers, excludes anything already on the quote (from both the suggestion list and as a
possible suggestion target), collapses duplicate suggestions from more than one trigger down to
the highest-scoring rule, computes each one's margin delta against the quotation's actual
current totals, and returns the ranked, filtered list.

**5. Frontend:** the builder's Upsell & Cross-Sell panel now calls the real endpoint instead of
filtering for promoted products, shows the margin-delta badge (colour-coded positive/negative),
and has a `Dismiss` button. Dismissal is session-local state only (a `Set` in the component, not
persisted) — PRD B5 draws a "Dismiss" button but never specifies whether a dismissal should
survive a reload, and FRONTEND.md leaves the exact affordance `TBD`; persisting it would need a
new table for a session-scoped judgement call, so it stays client-side. Suggestions refresh
after every line change, discount change, and order-level discount application, since the
margin-delta figure depends on the quotation's live totals.

**6. `DEMO.md` rewritten to match reality.** Removed the stale claim that the login screen has
click-to-fill buttons (removed two sessions ago). Added three new flows using the exact numbers
already verified by this session's and the previous two sessions' live-API scripts: Flow 4
(confirm → auto-generated warehouse split → accept), Flow 5 (a hybrid one-time + subscription
order → billing schedule → issue invoice → record payment), Flow 6 (customer portal counter-offer
→ automatic re-entry into approval → manager approves → customer re-confirms). Rewrote the
"What is NOT built" section, which previously claimed fulfillment, billing and the portal had
"no API, no screen" — all three are now fully built and tested. Updated the numbers-worth-
memorising table and test counts.

### Files Changed
- `backend/app/services/quotation.py` (`quantize_percent()`)
- `backend/app/api/v1/endpoints/quotations.py` (precision fix; new `/upsell` endpoint)
- `backend/app/services/upsell.py` (new)
- `backend/app/schemas/api.py` (`UpsellSuggestionResponse`)
- `backend/tests/test_upsell.py` (new — 12 tests)
- `frontend/src/screens/QuotationDetail.tsx` (order-discount control; real upsell panel)
- `frontend/src/lib/api.ts` (`UpsellSuggestion` type)
- `DEMO.md` (three new flows, corrected "not built" section, updated numbers)
- `PROJECT_CONTEXT.md`, `IMPLEMENTATION_LOG.md`

### Important Decisions
- Decision: `min_margin_percent` gates on the suggested product's own margin, not the order-wide
  margin delta.
- Reason: see Implemented §3 above — the seeded floor values only make sense as product-margin
  percentages, and using them as a floor on a typically-small delta would suppress almost every
  suggestion regardless of how healthy the product actually is.

- Decision: "Dismiss" is session-local only, no persistence.
- Reason: PRD B5 and FRONTEND.md both leave the exact behaviour unspecified; a session-scoped
  dismissal needs no schema change, while a persistent one would need a new table for a UX
  detail neither source document commits to.

### Validation
- Tests: **197 backend tests pass** (185 prior + 12 new upsell tests). Coverage: `is_promoted`
  ranks above a higher `co_purchase_score` (not merely a tiebreaker); score breaks ties within
  the same promotion tier; below-floor candidates are suppressed entirely, not de-prioritized;
  exactly-at-the-floor is not suppressed; empty/all-suppressed inputs rank to empty;
  `product_margin_percent` handles a zero list price and a genuine negative margin without
  crashing or clamping; `margin_delta_if_added` is tested for a margin-accretive addition, a
  margin-dilutive one, and an order with zero current revenue (division-by-zero guard).
- `ruff check .` / `ruff format --check .` clean. Frontend `tsc -b && vite build` clean.
- Manual verification against real seeded PostgreSQL: a 9-check live-API script (empty
  quotation returns no suggestions; a laptop-only quote returns exactly the four seeded
  HW-LAPTOP-triggered suggestions with the promoted HW-DOCK ranked first; the laptop itself is
  never self-suggested; adding a suggested product removes it from the list without removing
  others; a user with broader read access can view another rep's quote's suggestions). Re-ran
  the previous two sessions' 40-check billing and 29-check portal scripts unchanged — both still
  pass, confirming the precision fix and quotation-service changes introduced no regression.

### Known Issues
- No full browser click-through of the order-discount control or the real upsell panel yet —
  `tsc -b && vite build` confirms they compile and type-check; same gap noted for billing and
  portal in the previous two entries.
- The "Dismiss" affordance's exact persistence behaviour remains `TBD` per FRONTEND.md; the
  session-local choice here is a reasonable default, not a locked rule.

### Current State
Phase 3 (Core) plus the first Phase 5 (Supporting) item are both complete and verified. Every
gap flagged in the two previous sessions' Known Issues sections is closed except the
browser-click-through item, which is a verification-thoroughness note, not a functional defect.
`DEMO.md` is now an accurate, complete script covering five real end-to-end flows plus security
talking points.

### Next Recommended Step
PROJECT_CONTEXT.md's "Remaining Work", all 🟡 Supporting scope: (1) Deal health dashboard —
blocked on anomaly thresholds still being undefined, needs a decision before it can start;
(2) Reporting with filters + PDF/XLS export; (3) Admin config screens for discount tiers and
approval chains (Screen 18) — the data is already configurable via the API, only the UI is
missing; (4) Product catalogue screens (16-17), manual warehouse override UI, nudges/escalations.

---

## 2026-09-06 — Move Postgres Off Docker, Onto the Local Machine

### Goal
User asked to stop running Postgres as a Docker service and connect the app to PostgreSQL
installed directly on their machine instead, with the explicit instruction that the database
should live there and nowhere else.

### Implemented
Found the local install first rather than guessing: PostgreSQL 18, running as a Windows
service, listening on **port 5433** (not the default 5432 — that port was already taken by
the project's own Dockerized Postgres, still running from the previous session).
`listen_addresses = '*'` was already set; `pg_hba.conf` only allowed `127.0.0.1`/`::1`.

Created a dedicated `dealflow` role (least-privilege, not the `postgres` superuser) with a
freshly generated password, and a `dealflow360` database owned by it — using the `postgres`
superuser credentials the user provided for this one-time setup step only.

**The `pg_hba.conf` restriction turned out not to matter.** Tested directly with `docker run
--rm postgres:16-alpine psql -h host.docker.internal ...` before touching any config: the
connection reached the password-check stage rather than being rejected at the network layer,
and `inet_server_addr()` reported `127.0.0.1` from inside the query — Docker Desktop's
`host.docker.internal` proxy makes the connection appear to Postgres as a plain loopback
connection, which the existing `127.0.0.1/32` rule already permits. No `pg_hba.conf` or
`listen_addresses` edit was needed at all, avoiding a config change to the user's local
Postgres that would have been easy to forget about later.

Updated `.env` (`POSTGRES_HOST=host.docker.internal`, `POSTGRES_PORT=5433`,
`POSTGRES_USER=dealflow`, fresh password, `POSTGRES_DB=dealflow360`) and rewrote
`docker-compose.yml` to remove the `db` service and `pgdata` volume entirely, and to remove
the backend service's hardcoded `POSTGRES_HOST: db` / `POSTGRES_PORT: 5432` environment
overrides that would otherwise have silently ignored whatever `.env` said. Stopped (not
removed) the old Dockerized Postgres container as a safety net rather than deleting its
volume outright.

Ran `alembic upgrade head` and `python -m app.seed` against the new, empty `dealflow360`
database, then brought the full stack up and re-ran every verification artifact this project
has accumulated, specifically because a database swap is exactly the kind of change that
looks fine at the health-check level while quietly being wrong underneath.

Updated `.env.example`, `docker-compose.yml`'s header comment, `README.md` (quick-start,
services table, common commands, troubleshooting — the "no PostgreSQL install needed" claim
is now false and was corrected), and `PROJECT_CONTEXT.md`.

### Files Changed
- `.env` (not committed — gitignored)
- `.env.example`
- `docker-compose.yml` (`db` service and `pgdata` volume removed; backend env override removed)
- `README.md` (Quick Start, Services table, Common commands, Troubleshooting)
- `PROJECT_CONTEXT.md`, `IMPLEMENTATION_LOG.md`

### Important Decisions
- Decision: verify the actual Docker-Desktop-to-host connection behavior empirically (a
  disposable `docker run` probe) before editing any Postgres configuration.
- Reason: assuming `pg_hba.conf` needed a new rule (the usual case on native Linux Docker)
  would have meant editing the user's local Postgres's security configuration unnecessarily.
  The probe took thirty seconds and turned a config change into a non-issue.

- Decision: stop the old Dockerized Postgres container rather than deleting it or its volume.
- Reason: it is unneeded now, but destroying it is irreversible and the user had not been
  asked whether they wanted the demo data preserved a while longer as a fallback. Removing
  it is a one-line follow-up once they confirm they're satisfied with the new setup.

### Validation
- **197 backend tests pass** against the new database, run inside the container exactly as
  before — the app itself required zero code changes, since `POSTGRES_HOST`/`PORT`/`USER`/
  `PASSWORD`/`DB` were already plain environment settings with no assumption baked in about
  where Postgres runs.
- Health check: `{"status":"ok","environment":"development","database":"ok"}`.
- Re-ran all three live-API scripts from the previous two sessions (billing, portal, upsell)
  unchanged against the freshly seeded local database: **78/78 checks pass** (40 + 29 + 9).
- Confirmed via `\dt` that the database was genuinely empty before migrating, and confirmed
  the `dealflow` role can connect and query directly with `psql`, independent of Docker.

### Known Issues
- The old Dockerized Postgres container (`dealflow360-db-1`) is stopped, not removed, and
  its volume still holds the previous session's demo data. Safe to remove
  (`docker rm dealflow360-db-1 && docker volume rm dealflow360_pgdata`) once confirmed the
  new setup is working as expected long-term.
- `README.md`'s repository-layout tree still lists an outdated file/screen inventory from
  several sessions ago (predates fulfillment, billing, portal, upsell) — a pre-existing
  staleness this entry did not fully resolve, only the Postgres-specific claims in it.
- Native Linux Docker users (not this project's dev machine) will need the
  `extra_hosts`/`pg_hba.conf` handling this session's Windows machine did not — noted in
  `docker-compose.yml`'s header comment but not implemented or tested.

### Current State
The full stack (backend + frontend, both still in Docker) runs against PostgreSQL installed
directly on the host machine. No application code changed; only `.env`, `docker-compose.yml`,
and documentation. Every existing test and live-verification script passes unchanged against
the new database.

### Next Recommended Step
Complete the remaining 🟡 Supporting scope (PROJECT_CONTEXT.md's "Remaining Work"), per the
user's explicit request to continue: deal health dashboard (needs anomaly-threshold decisions
first), reporting + export, admin config screens, product catalogue screens.

---

## 2026-09-06 — Complete Supporting Scope: Deal Health, Reporting, Admin Config, Catalogue

### Goal
User asked to complete all remaining 🟡 Supporting scope from PROJECT_CONTEXT.md's backlog in
one pass: the deal health dashboard, reporting with export, admin config screens (discount
tiers, approval chains), and the product catalogue. Two genuine "stop and ask" items first
(PLAN.md §0.6 names deal-health thresholds explicitly; §0.5 requires naming a specific export
library before adopting one) — both confirmed with the user before writing code. See Locked
Business Rules #9 and the new Important Technical Decisions row for the outcomes.

### Implemented

**1. Deal health dashboard** (`app/services/dealhealth.py`, PRD B9). Pure threshold functions
(`is_stalled`, `discount_anomaly`, `delivery_slippage`) mirror `risk.py`'s shape. No scheduled
job exists (`Background Jobs` is still "not yet implemented"), so `refresh_dashboard()` is
called on every dashboard view and writes a fresh `DealHealthSnapshot` row each time — the same
"compute lazily on the read that needs it" pattern `fulfillment.py` uses for its auto-generated
split. Nudge/Escalate actions record an audit event (no notification channel exists to actually
deliver one — noted as a real gap, not silently faked).

**2. Reporting + export** (`app/services/reports.py`, PRD A7). Filters match PRD A7's own list
exactly (Period, Rep, Approval Status, Category). `openpyxl` and `fpdf2` adopted at the Section
0.5 checkpoint — both pure Python, no system library baked into the Docker image (unlike
`weasyprint`, which needs Pango/Cairo). An export applies the exact same ownership scoping as
the JSON view, so a rep's export can never contain data the screen itself would have hidden.

**3. Admin config** (`app/api/v1/endpoints/admin.py`, Screen 18 + PRD A3). CRUD for the
discount ceiling matrix and approval-chain bands, gated by the existing `config.manage`
permission (already seeded to Admin and Sales Manager — no new permission needed). One
reconciliation with FRONTEND.md's wireframe: Screen 18 draws "Tier Discount Ceilings" and
"Category Discount Ceilings" as two separate tables, but the backend's ceiling has always been
a single (tier, category) pair (Locked Business Rules #1/#6) — rendered as the one matrix that
actually is, not two tables that would misrepresent the lookup.

**4. Product catalogue** (`app/api/v1/endpoints/admin.py`, Screens 16-17 + PRD A2). Product and
Category CRUD — create, edit, archive (never hard-delete, per the existing `ArchivableMixin`
convention). Variant and price-list editing from the wireframe are scoped out this round;
general info is the part PRD A2 actually gates the quotation builder's product picker on.

**5. Frontend:** `AdminDiscountTiers.tsx`, `AdminProductsList.tsx` + `AdminProductDetail.tsx`,
`DealHealthDashboard.tsx`, `ReportsScreen.tsx`. Added `api.download()` to the frontend HTTP
client — a binary-blob variant of the existing request pipeline (same 401-retry logic) since
PDF/XLSX exports need a real browser file save, not a JSON response.

### Files Changed
- `backend/app/services/dealhealth.py`, `backend/app/services/reports.py` (new)
- `backend/app/api/v1/endpoints/admin.py`, `dealhealth.py`, `reports.py` (new)
- `backend/app/api/v1/router.py` (wired the three new routers)
- `backend/app/schemas/api.py` (admin/deal-health/reporting DTOs)
- `backend/app/models/audit.py` (`CONFIG_CHANGED` action)
- `backend/requirements.txt` (`openpyxl`, `fpdf2`)
- `backend/tests/test_dealhealth.py`, `test_dealhealth_db.py`, `test_reports.py` (new — 26 tests)
- `frontend/src/screens/AdminDiscountTiers.tsx`, `AdminProductsList.tsx`,
  `AdminProductDetail.tsx`, `DealHealthDashboard.tsx`, `ReportsScreen.tsx` (new)
- `frontend/src/lib/api.ts` (`api.download()`, new DTOs)
- `frontend/src/App.tsx`, `layouts/InternalShell.tsx` (routes/nav enabled)
- `PROJECT_CONTEXT.md`, `IMPLEMENTATION_LOG.md`

### Important Decisions
See Locked Business Rules #9 (deal health thresholds — user-confirmed defaults: 7 days idle,
10 points above a rep's trailing 20-quote average) and the new Important Technical Decisions
row (`openpyxl` + `fpdf2`, user-confirmed at the Section 0.5 checkpoint). One decision made
without asking, low-stakes and documented rather than raised:

- Decision: `upsell_rules.min_margin_percent` gates on the suggested PRODUCT's own margin.
  (Carried over from the previous session — restated here because `admin.py`'s docstring is
  where a future reader would otherwise expect to find the config surface for it and not find
  an explanation.)
- Decision (this session): the single `config.manage` permission covers both discount-tier
  config AND the product catalogue, even though FRONTEND.md's wireframe draws Product Catalog
  as Admin-only and Discount Tiers as Admin + Sales Manager.
- Reason: the backend's RBAC design committed to one `config.manage` permission for all of
  "products, price lists, discount tiers, approval chains" back in Phase 1 (see
  `app/seed.py`'s `PERMISSIONS` list). Splitting it now to match a screen-level wireframe
  distinction would redefine an existing locked decision for a difference the PRD itself
  doesn't insist on — a Sales Manager seeing the product catalogue is not a security problem.

### Validation
- Tests: **223 backend tests pass** (197 prior + 26 new: 15 pure threshold tests, 5 DB
  orchestration tests for `refresh_dashboard`, 6 reporting tests covering scoping, status
  filtering, totals, and both export formats' structural validity).
- `ruff check .` / `ruff format --check .` clean. Frontend `tsc -b && vite build` clean.
- Manual verification against real seeded PostgreSQL via five separate live-API scripts run
  this session (40 + 29 + 9 + 12 + 15 = 105 checks), covering: admin permission gating (rep
  403, manager/admin 200), ceiling matrix read/update with no precision drift, approval-chain
  CRUD, category/product CRUD including duplicate-SKU rejection and archive; a real quotation
  backdated 10 days at the database level (the one thing no API call could simulate) correctly
  appearing as "stalled" on the dashboard, scoped correctly to its owning rep, with a working
  nudge action; report filtering by status and date, and both XLSX (validated as a real
  loadable workbook, not just a byte count) and PDF (validated by the `%PDF` magic number)
  exports downloading with the correct ownership scoping and content-type.

**One real bug found and fixed during this work, the same failure class documented three times
before now:** the discount-tier and approval-chain UPDATE endpoints set `max_discount_percent`/
`min_score`/`max_score`/`tax_rate`/`list_price`/`cost_price` directly from request bodies
without quantizing to the column's 2dp scale, so a bare `16` printed as `"16"` instead of
`"16.00"` in the very same response that showed every other value with two decimals. Caught
immediately by the live-API script's exact-string assertion. Fixed with one `_q2()` helper
applied at every write site in `admin.py` — the fourth occurrence of this exact class, following
`services/{billing,portal,quotation}.py`'s versions. `quotation.py`'s `quantize_percent()` is
now shared by both `quotations.py` and, in spirit, this module's own `_q2()` (not literally
shared, since `admin.py` also quantizes money fields `quantize_percent` was never meant for -
see Known Issues for the follow-up worth doing here).

### Known Issues
- `admin.py`'s `_q2()` and `quotation.py`'s `quantize_percent()` are the same one-line function
  duplicated because their column semantics differ slightly (percentages only vs. percentages
  and money). Worth consolidating into one shared `app/services/decimal_utils.py` if a fifth
  occurrence of this pattern ever shows up — three duplicates is a coincidence, a fourth would
  be a pattern worth naming.
- No background job exists for deal-health recomputation, subscription renewal, or backorder
  consolidation — all three are the same category of gap (something that should happen on a
  schedule happens on next-view instead). Tracked project-wide as one item, not three, since
  the fix (a scheduler) is the same for all of them.
- Nudge/Escalate actions on the Deal Health dashboard record an audit event only — no email or
  in-app notification is actually sent, since no notification channel exists in this build.
- Product variant and price-list editing (FRONTEND.md Screen 17's other two tables) are not
  built. General info (name, category, price, tax, promoted flag) is what the quotation
  builder's product picker actually depends on; variants/price-lists are a real, scoped-out gap.
- No browser click-through yet for any of the five new screens — `tsc -b && vite build`
  confirms they compile and type-check against the real API, consistent with the same gap
  noted for billing/portal/upsell in earlier entries.
- `DEMO.md` does not yet include Deal Health, Reports, or Admin config in its script.

### Current State
**Every Core and Supporting item in PLAN.md Section 18's own classification is now built,
tested, and verified against the real running system.** Only Bonus (🟢) scope — multi-currency,
multi-company, explicitly marked optional by PLAN.md — and the deliberately-deferred items in
PROJECT_CONTEXT.md's "Deferred deliberately" section remain.

### Next Recommended Step
Nothing is blocking. If continuing: (1) a `DEMO.md` pass to add the Phase 5 screens to the
script; (2) the consolidation/background-job items above, if genuinely valuable for a demo
rather than just tidiness; (3) Bonus scope, only if there is time left over per PLAN.md's own
sequencing rule (🔴 before 🟡 before 🟢).

---

## 2026-09-06 — Implement Real Registration, Verify JWT, Fix Deep-Link Session Bug

### Goal
Four user-reported items: (1) there is no registration screen, everything is hardcoded via
seed data — build real signup; (2) validate email format properly; (3) verify the JWT
implementation actually works, not just reads correctly; (4) a real bug — opening
`/approvals/76` (or any deep link) "from something else" drops an already-authenticated admin
back to the login screen.

### Implemented

**1. Signup, for real this time.** Found a genuine documentation/code mismatch while
investigating: `PROJECT_CONTEXT.md` Locked Business Rules #5 has said since Phase 1 that public
signup exists and always creates a Sales Rep — but `app/api/v1/endpoints/auth.py`'s own
docstring said the opposite ("deliberately NO signup endpoint"), and there was in fact no
`/auth/signup` route at all. The rule was locked and written up; the endpoint implementing it
was simply never built. Implemented now:
- `app/services/auth.py`'s `signup()` — always Sales Rep, auto-issues a token pair on success
  (mirrors `authenticate()`'s shape, so sign-up and log-in are one action, matching the PRD's
  own "signs up (first time) or logs in" framing as alternatives, not sequential steps).
- `SignupRequest` has no `role`/`role_id`/`customer_id` field at all — the mass-assignment
  defense (SECURITY_SPEC.md Section 8) is structural, not a matter of the endpoint remembering
  to discard one.
- `POST /auth/signup`, rate-limited tighter than login (5/min vs 10/min — account creation is
  the more expensive and more abuse-attractive operation).
- Frontend: `Register.tsx` (a real screen, not a stub), linked from `Login.tsx`, wired into
  `AuthContext.signUp()`.

**2. Email validation.** Already using Pydantic's `EmailStr` (via `email-validator`) on
`LoginRequest`; `SignupRequest` uses the same. This is real RFC validation, not a `.`/`@`
regex — confirmed live that `user@localhost` (no TLD) and `not-an-email` are both rejected
with 422, not just an obviously-malformed string. Frontend `Register.tsx` also validates
client-side (matching the existing `<input type="email">` pattern already used on Login)
before the round trip, backed by the backend as the actual source of truth.

**3. JWT verified live, not just read.** Wrote a 25-check script exercising every claim
SECURITY_SPEC.md's defence table makes, against the real running system: `alg:none` forgery
rejected, a tampered signature rejected, a token signed with a different secret entirely
rejected, a refresh token rejected when presented as an access token, no-auth-header rejected,
the payload contains no PII (only `sub`/`type`/`jti`/`iat`/`exp`/`iss`/`aud`), refresh rotation
issues a genuinely new token, replaying a revoked refresh token is rejected, and — the one that
actually exercises the reuse-detection logic rather than just the "already used" check —
replaying the SUCCESSOR of a replayed token is also rejected, proving the whole token family
gets revoked, not just the one token that was reused. All 25 passed; nothing needed fixing.

**4. The deep-link session bug — a real bug, root-caused and fixed.** `sessionStorage` (chosen
in the 2026-09-05 fix for the cross-tab collision bug) is per-tab by design: a brand-new tab
opened via a link, bookmark, or pasted URL starts with EMPTY sessionStorage no matter how
signed-in the user is elsewhere in the same browser, so `InternalShell`'s route guard correctly
(from its own point of view) sees no user and bounces to `/login`. This is not a bug in
`InternalShell` — it is the documented, deliberate trade-off of the per-tab design finally
being hit in practice.

Fixed by mirroring the refresh token to `localStorage` as a "last known session" bootstrap
value, with two rules that took two iterations to get right (both caught by writing a literal
trace of the shipped logic against mock Storage objects standing in for multiple tabs, since
this project has no frontend test runner):
- A **routine background token rotation must never update the shared fallback** —
  `setTokens()` gained a `{ background: true }` flag, passed only by `refreshAccessToken()`'s
  own success path. Without this, the first version of the fix reintroduced the ORIGINAL
  cross-tab bug one layer down: tab A's silent ~15-minute token refresh would overwrite tab B's
  still-active identity in the shared fallback, so a brand-new tab C opened right after would
  bootstrap into A's session instead of B's — purely because of refresh timing neither user
  controlled. Caught immediately by the trace script.
- **A tab that bootstrapped once, or ever explicitly signed in or out, must never bootstrap
  again from the shared pool for the rest of that tab's life** — a `dealflow.bootstrapped`
  sessionStorage sentinel. Without this, the SECOND version of the fix had an even worse bug:
  explicitly signing out in tab A would immediately re-bootstrap tab A right back into whatever
  identity happened to be sitting in the shared fallback (tab B's manager session, say) —
  turning "sign out" into "silently sign in as someone else." Also caught by the trace script,
  which is exactly why it was written before declaring the fix done rather than after.

### Files Changed
- `backend/app/services/auth.py` (`signup()`, `SignupError`)
- `backend/app/api/v1/endpoints/auth.py` (`POST /signup`; corrected the stale docstring)
- `backend/app/schemas/api.py` (`SignupRequest`)
- `backend/app/models/audit.py` (`USER_REGISTERED` action)
- `backend/tests/test_auth.py` (new — 7 tests)
- `frontend/src/screens/Register.tsx` (new)
- `frontend/src/screens/Login.tsx` (link to Register; corrected stale "no public sign-up" copy)
- `frontend/src/lib/auth.tsx` (`signUp()`)
- `frontend/src/lib/api.ts` (`setTokens`'s `background` flag and `BOOTSTRAPPED_KEY` sentinel)
- `frontend/src/App.tsx` (`/register` route)
- `PROJECT_CONTEXT.md`, `IMPLEMENTATION_LOG.md`

### Important Decisions
- Decision: signup auto-issues a token pair (auto-login) rather than requiring a separate
  login call afterward.
- Reason: PRD Section 5's own flow lists "signs up (first time) or logs in" as alternatives to
  the same next step, not two actions in sequence; every real registration form does this.

- Decision: password minimum length is 8 characters (SECURITY_SPEC.md says only "enforce
  password policy" without a specific number).
- Reason: a defensible, standard baseline; not raised as a question given how low-stakes and
  reversible a single numeric threshold is.

- Decision: a duplicate email on signup returns a specific 409 with a real message, unlike
  login's deliberately generic 401 for every failure mode.
- Reason: different threat models. Login's genericness stops an attacker from using the
  endpoint to discover which emails have accounts; a signup form telling someone that the
  email they just typed is already registered is not that attack, and every mainstream
  registration flow surfaces it.

- Decision: `PATCH /api/v1/admin/users/{id}/role` (role promotion) is explicitly NOT built this
  round, even though Locked Business Rules #5 ties it to signup.
- Reason: the user's request was specifically registration + login + JWT + the session bug;
  building a role-management screen is a distinct, larger feature not asked for. Recorded as
  an open item in Remaining Work rather than silently expanded into.

### Validation
- Tests: **230 backend tests pass** (223 prior + 7 new signup tests): Sales Rep assignment
  regardless of caller, password hashed not stored plaintext, email normalization
  (case/whitespace), a genuinely valid issued token pair, duplicate-email rejection
  (case-insensitive too), and a structural assertion that `signup()`'s own parameter list has
  no `role`/`role_id`/`customer_id` to smuggle through.
- `ruff check .` / `ruff format --check .` clean. Frontend `tsc -b && vite build` clean.
- Manual verification against real seeded PostgreSQL: the 25-check JWT/signup script above, run
  twice (before and after a `ruff format` pass, to confirm the reformat changed nothing
  behaviorally) — 25/25 both times. Re-ran all four prior sessions' live-API scripts unchanged
  (billing/portal/upsell/deal-health+reports, 93 checks total) to confirm the auth changes —
  which touch the dependency every single endpoint in the app relies on — introduced no
  regression anywhere else.
- The session-storage fix itself was verified with a standalone Node script tracing the exact
  shipped `getRefreshToken`/`setTokens` logic against mock Storage objects simulating multiple
  real browser tabs — 13/13 checks passing on the final version, after the first two versions
  each failed one check that exposed a real design gap (see Implemented §4 above). This is the
  same "verify against the real behavior, not just review the code" standard applied to every
  backend feature in this project, extended to a piece of frontend logic that has no other way
  to be exercised without a browser.

### Known Issues
- `PATCH /api/v1/admin/users/{id}/role` is still not built — an Admin promotes a self-registered
  Sales Rep to another role by editing the database row directly. Tracked in Remaining Work.
- The localStorage bootstrap fallback is a best-effort default for a brand-new tab, not a
  guarantee of which identity it lands on if MULTIPLE different users are simultaneously active
  in different tabs of the same browser (it bootstraps to whichever one most recently performed
  an explicit sign-in) — this only matters for the multi-role-testing-in-one-browser workflow,
  never for a normal single-user session, and a brand-new tab landing on "a" valid signed-in
  identity instead of forcing a fresh login is strictly better than the bug being fixed.
- No frontend test runner exists in this project (`tsc` + `vite build` are the only automated
  frontend checks) — the session-storage fix's real verification is the standalone Node trace
  script in this entry, not a checked-in test. Worth a real Vitest/jsdom setup if frontend logic
  keeps getting subtle enough to need this treatment again.

### Current State
Registration is real: a Sales Rep can create their own account and is signed in immediately.
JWT issuing, verification, rotation, and reuse detection are all confirmed working correctly
against the live system, not just read as correct in the source. The deep-link/new-tab session
bug is fixed without reintroducing the cross-tab collision bug the sessionStorage design
originally existed to prevent — confirmed by literally tracing both failure modes before
declaring it done, not by inspection alone.

### Next Recommended Step
Nothing is blocking. If continuing: `PATCH /api/v1/admin/users/{id}/role` for role promotion
(the other half of Locked Business Rules #5), or any of the previously-recorded Remaining Work
items.
