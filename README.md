# DealFlow360

A self-governing B2B sales operations platform — quote-to-cash with automatic
discount discipline, real-time multi-warehouse inventory awareness, reconciled
one-time + recurring billing on a single order, and a live customer negotiation
portal.

**Stack:** FastAPI (Python 3.12) · React + TypeScript (Vite) · PostgreSQL 16+ ·
SQLAlchemy 2 (async) + Alembic · Docker Compose for the backend/frontend.
**Postgres runs natively on your machine, not in a container** — see
"Database setup" below for why and how.

> **Status: all PRD Core scope is complete and demoable**, plus the first
> Supporting-scope items. Login (all 5 roles), the quotation builder with a
> live blended discount risk score and a real upsell panel, automatic approval
> routing, multi-warehouse fulfillment with backorders, hybrid one-time +
> subscription billing with proration, and a genuinely separate customer
> negotiation portal all work end-to-end against the real API.
> `IMPLEMENTATION_LOG.md` has the full chronological build history;
> `PROJECT_CONTEXT.md` has the current backlog.

---

## Run it on a brand-new machine — copy/paste this whole block

Requires **[Docker Desktop](https://www.docker.com/products/docker-desktop/)**,
**Git**, and a **local PostgreSQL install** (16 or newer) — see "Database
setup" immediately below if you don't have one yet. Backend and frontend run
in containers; only Postgres runs directly on the host.

### Database setup (one time)

The app needs a dedicated role and database. Using `psql` (adjust the port if
your local Postgres doesn't use the default 5432 — check with
`pg_isready` or your `postgresql.conf`):

```bash
psql -U postgres -h localhost -p 5432 -c "CREATE ROLE dealflow LOGIN PASSWORD 'pick-a-real-password';"
psql -U postgres -h localhost -p 5432 -c "CREATE DATABASE dealflow360 OWNER dealflow;"
```

That's it — no other Postgres configuration is required. On Docker Desktop
(Windows/Mac), the backend container reaches this via `host.docker.internal`,
which resolves to the host automatically; you do not need to touch
`pg_hba.conf` or `listen_addresses` for this to work. (Native Linux Docker
needs one extra `extra_hosts` line in `docker-compose.yml` — see the comment
at the top of that file.)

```bash
git clone https://github.com/shreytiwari09/DealFlow360.git
cd DealFlow360

cp .env.example .env
# Open .env and fill in the real values: the POSTGRES_PASSWORD you just set
# above, POSTGRES_PORT if it isn't 5432, and a real JWT_SECRET_KEY (see
# "Secrets" below for how to generate one).

docker compose up -d --build
```

First run pulls base images and builds two containers — give it 1-3 minutes.
Then wait for the backend to report healthy and seed the demo data:

```bash
# Windows PowerShell / macOS / Linux all use the same command:
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed
```

Open **http://localhost:5173** and sign in with a plain email/password login.
Password for every demo account: `DealFlow360!demo`

| Role | Email |
|---|---|
| Sales Rep | `rep@dealflow360.example` |
| Sales Manager | `manager@dealflow360.example` |
| Finance / Ops | `finance@dealflow360.example` |
| Admin | `admin@dealflow360.example` |
| Customer (portal) | `portal@acme.example` |

Confirm the backend is genuinely up (this hits the database, not just the process):

```bash
curl http://localhost:8000/api/v1/health/ready
# {"status":"ok","environment":"development","database":"ok"}
```

**That's the whole setup.** If something doesn't come up, see [Troubleshooting](#troubleshooting) below before doing anything else.

---

## Giving the demo

There is no standing demo script in this repo — `PROJECT_CONTEXT.md`'s
"Remaining Work" section is the current, accurate list of what is and isn't
built, and `IMPLEMENTATION_LOG.md` is the chronological record of what was
verified and when. Walk the app itself: sign up or log in as a Sales Rep,
build a quotation, watch it route for approval, accept the fulfillment split,
and negotiate it from the customer portal — every flow described in this
README works end-to-end against the real API, not a mock.

### A frozen, known-good checkpoint

The commit tagged **`demo-v1`** is a fully verified early snapshot (Phase 3
part 1 — the two approval-routing flows). `main` has since completed the rest
of PRD Core scope (fulfillment, billing, portal) plus upsell — see
`IMPLEMENTATION_LOG.md` for the verified state of each. `demo-v1` never moves.
If you're mid-feature and a demo comes up unannounced, switch to the
known-good state instead of demoing work in progress:

```bash
git fetch --tags
git checkout demo-v1
docker compose down -v && docker compose up -d --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed
```

Afterward, go back to active development:

```bash
git checkout main
docker compose down -v && docker compose up -d --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed
```

Nothing is lost either direction — this only switches which commit's code is
running; all your `main` commits stay exactly where they are.

**Extra safety net:** if you want the demo copy to never be touched at all —
not even by an accidental `git checkout` on the wrong terminal — clone the repo
a second time into its own folder and pin it to the tag permanently:

```bash
git clone https://github.com/shreytiwari09/DealFlow360.git DealFlow360-demo
cd DealFlow360-demo
git checkout demo-v1
# Give this copy a distinct Compose project name so it can run
# side-by-side with your main dev copy without port/volume conflicts:
docker compose -p dealflow360-demo up -d --build
```

---

## Services and ports

| Service | URL | Notes |
|---|---|---|
| Frontend | http://localhost:5173 | React + Vite dev server |
| Backend API | http://localhost:8000 | FastAPI |
| API docs | http://localhost:8000/docs | Interactive OpenAPI UI (dev only, disabled in production) |
| PostgreSQL | `localhost:<your POSTGRES_PORT>` | Runs on the host, not in a container — see "Database setup" above |

---

## Secrets

`POSTGRES_PASSWORD` and `JWT_SECRET_KEY` have **no defaults in code** — the app
refuses to start without them, so a placeholder can never silently ship to
production (SECURITY_SPEC.md §8). For local/demo use, any non-empty value in
`.env` works. To generate a real cryptographic signing key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
# no local Python? do it inside the container instead:
docker compose exec backend python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env` is gitignored — only `.env.example`, which holds placeholders, is
committed. Never commit a real `.env`.

---

## Common commands

Run against the live containers — no local Python/Node toolchain needed for any of these.

```bash
# --- Demo data -------------------------------------------------------------
docker compose exec backend python -m app.seed          # idempotent, safe to re-run anytime

# Full reset (wipes all data, rebuilds from empty) - run against your LOCAL
# Postgres, not through docker compose exec, since Postgres isn't containerized:
psql -U dealflow -h localhost -p <your POSTGRES_PORT> -d dealflow360 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed

# --- Backend -----------------------------------------------------------------
docker compose exec backend pytest                 # 197 tests (run the seed first - some read seeded rows)
docker compose exec backend ruff check .           # lint
docker compose exec backend ruff format .          # format

# Migrations (Alembic - schema is never created with create_all)
docker compose exec backend alembic revision --autogenerate -m "describe the change"
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1
docker compose exec backend alembic current

# --- Frontend ------------------------------------------------------------
docker compose exec frontend npm run typecheck
docker compose exec frontend npm run build

# --- Database shell --------------------------------------------------------
# Directly against your local Postgres - not through docker compose exec:
psql -U dealflow -h localhost -p <your POSTGRES_PORT> -d dealflow360

# --- Logs / status -----------------------------------------------------------
docker compose ps
docker compose logs backend --tail 50
docker compose logs frontend --tail 50

# --- Stop everything ---------------------------------------------------------
docker compose down          # stop backend/frontend containers; Postgres (on the
                              # host) is untouched either way, since it isn't
                              # part of this compose project
```

---

## Troubleshooting

**`docker compose` fails with "cannot connect to the Docker daemon" / a pipe error (Windows).**
Docker Desktop isn't running. Start it (Start Menu → Docker Desktop, or on
Windows: `Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"`
in PowerShell) and wait ~30-60 seconds for the whale icon to stop animating,
then retry.

**A port is already in use (`5173` or `8000`).**
Something else on the machine is using it. Either stop that process, or edit
the port mapping on the left-hand side in `docker-compose.yml` (e.g.
`"5174:5173"`) and use the new port in your browser.

**Postgres port conflict, or the backend can't reach Postgres at all.**
`POSTGRES_PORT` in `.env` must match whatever your local Postgres actually
listens on — check with `pg_isready` or your `postgresql.conf`. If you
previously ran this project's own Dockerized Postgres, that container may
still be bound to `5432`; stop it (`docker stop <container>`) or just pick a
different `POSTGRES_PORT` for your local install. `POSTGRES_HOST` must stay
`host.docker.internal` (not `localhost`, which inside the backend container
means the container itself, and not your local Postgres).

**Frontend loads but shows a blank page, gets stuck on "Loading…", or numbers
never appear.**
Almost always a stale browser session from a previous run, not a backend
problem. First confirm the backend itself is fine:
```bash
curl http://localhost:8000/api/v1/health/ready
```
If that returns `{"status":"ok",...}`, the backend is healthy and the issue is
in the browser — open DevTools (F12) → Console for red errors, then clear
storage and reload:
```js
sessionStorage.clear(); localStorage.clear();
```

**Dashboard/lists show all zeros or an empty table right after a reset.**
That's correct, not broken — a fresh reset genuinely has no quotations yet.
Click **+ New Quotation** to create one, or run `docker compose exec backend
python -m app.seed` for realistic demo data.

**`alembic upgrade head` or the seed command fails right after `docker compose up`.**
Confirm your local Postgres is actually running and the credentials/port in
`.env` are correct: `curl http://localhost:8000/api/v1/health/ready` should
show `"database":"ok"` — if it shows `"database":"unavailable"` instead, fix
`.env` and recreate the backend container with `docker compose up -d backend`
(a plain `restart` reuses the old environment and will not pick up `.env`
changes).

**I changed backend code and nothing seems to update.**
The backend container runs with `--reload` and picks up changes automatically
via the bind mount — no rebuild needed for Python changes. If it truly seems
stuck: `docker compose restart backend`. A rebuild (`--build`) is only needed
after changing `requirements.txt`.

---

## Repository layout

```
├── PLAN.md                  Execution roadmap — phases, order, exit conditions
├── PROJECT_CONTEXT.md       Current architecture, locked decisions, open questions
├── IMPLEMENTATION_LOG.md    Chronological record of what was actually built
├── SECURITY_SPEC.md         Authoritative security implementation contract
├── FRONTEND.md              Screen-by-screen UI spec (the Phase 8 design input)
├── docs/erd.md              ERD, system architecture diagram, state machines
├── docker-compose.yml       Backend + frontend only — Postgres runs on the host
├── .env.example             Placeholder environment file
│
├── backend/
│   ├── alembic/                    Versioned migrations (async env.py)
│   └── app/
│       ├── main.py                 FastAPI app: CORS, rate limiting, error handlers, router
│       ├── seed.py                 Idempotent demo/dev seed data
│       ├── core/                   config · security (Argon2id) · tokens (JWT) · rate_limit
│       ├── db/                     declarative Base + naming convention, async session
│       ├── models/                 30 tables across domain modules (rbac, quotation,
│       │                           approval, catalog, policy, billing, inventory, ...)
│       ├── schemas/                Pydantic request/response DTOs
│       ├── services/                business logic, kept independent of HTTP:
│       │     risk.py                 blended risk score + approval routing (pure, no DB)
│       │     quotation.py            recalculates totals/margin/risk on every line change
│       │     approval.py             creates approval requests/steps, tracks whose turn it is
│       │     auth.py                 login, refresh rotation with reuse detection, logout
│       │     audit.py                the one function that writes every audit_logs row
│       │     state_machine.py        valid status transitions for every entity (pure)
│       └── api/
│           ├── deps.py             RBAC: identity → permission → resource-ownership checks
│           └── v1/endpoints/       auth, quotations, approvals, catalog, dashboard, health
│   └── tests/                      124 tests: risk engine, state machines, DB constraints,
│                                    seed data, health endpoints
│
└── frontend/
    └── src/
        ├── App.tsx                 Route map
        ├── layouts/InternalShell.tsx   Sidebar + header shell for internal roles
        ├── screens/                Login, Dashboard, QuotationsList, QuotationDetail
        │                           (the builder), ApprovalsList, ApprovalDetail
        ├── components/ui.tsx       Shared components: badges, KPI cards, data table, stepper
        ├── lib/                    api.ts (HTTP client + token refresh), auth.tsx (session
        │                           context), format.ts
        └── styles/                 tokens.css (design tokens) + app.css
```

---

## Working on this project

Read `PLAN.md` first — it governs build order and process, and
`PROJECT_CONTEXT.md` has the ordered backlog for what's next (warehouse
splitting, hybrid billing, the customer portal negotiation screen). Two rules
matter most and are easy to violate by accident:

- **§0.6 Ask, Don't Assume.** Business rules that were ambiguous in the PRD
  are now locked and written up under "Locked Business Rules" in
  `PROJECT_CONTEXT.md` — do not redefine them without recording why. A few
  (deal-health thresholds, warehouse tie-break) are still genuinely open;
  don't invent them silently in code.
- **RBAC lives in one place.** All permission and resource-ownership checks
  go through `backend/app/api/deps.py` — never duplicate an authorization
  check in an endpoint. Frontend role-based hiding (`can()` in `lib/auth.tsx`)
  is a UX courtesy only; it is never the real security boundary.

After any meaningful change, append an entry to `IMPLEMENTATION_LOG.md` in its
defined format — that file is what lets the next session (human or AI) pick
up work without re-deriving what already happened.
