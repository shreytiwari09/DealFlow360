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
