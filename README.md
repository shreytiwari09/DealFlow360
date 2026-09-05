# DealFlow360

A self-governing B2B sales operations platform — quote-to-cash with automatic
discount discipline, real-time multi-warehouse inventory awareness, reconciled
one-time + recurring billing on a single order, and a live customer negotiation
portal.

**Stack:** FastAPI (Python 3.12) · React + TypeScript (Vite) · PostgreSQL 16 ·
SQLAlchemy 2 (async) + Alembic · Docker Compose. Everything runs in containers —
**the only things you need installed are Git and Docker Desktop.**

> **Status: working, demoable application.** Login (all 5 roles), the quotation
> builder with a live blended discount risk score, automatic approval routing
> (including a two-step Manager → Finance chain), approve/reject/return with a
> mandatory reason, and a full audit trail all work end-to-end right now.
> See [`DEMO.md`](DEMO.md) for the exact script — every number in it was
> verified against the running system. `IMPLEMENTATION_LOG.md` has the full
> chronological build history; `PROJECT_CONTEXT.md` has the current backlog.

---

## Run it on a brand-new machine — copy/paste this whole block

Requires only **[Docker Desktop](https://www.docker.com/products/docker-desktop/)**
and **Git**. Nothing else — no Python, no Node, no PostgreSQL install. Works
identically on Windows, macOS, and Linux.

```bash
git clone https://github.com/shreytiwari09/DealFlow360.git
cd DealFlow360

cp .env.example .env
# Open .env and set POSTGRES_PASSWORD and JWT_SECRET_KEY to anything non-empty
# for local/demo use (see "Secrets" below for how to generate a real one).

docker compose up -d --build
```

First run pulls base images and builds two containers — give it 1-3 minutes.
Then wait for the backend to report healthy and seed the demo data:

```bash
# Windows PowerShell / macOS / Linux all use the same command:
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed
```

Open **http://localhost:5173** and sign in — the login screen has click-to-fill
buttons for every demo account. Password for all of them: `DealFlow360!demo`

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

Follow **[`DEMO.md`](DEMO.md)** — it is the verified script: exactly what to
click, the exact numbers you should see at each step, the security talking
points, and an explicit list of what is *not* built yet (so you're never
surprised by a question). Every claim in it was checked against the running
system, not written from memory.

### A frozen, known-good checkpoint

The commit tagged **`demo-v1`** is a fully verified snapshot — 124 automated
tests plus 56 end-to-end API checks pass on it, and both demo flows were
driven through the real UI with no runtime errors. Development continues on
`main`; `demo-v1` never moves. If you're mid-feature and a demo comes up
unannounced, switch to the known-good state instead of demoing work in
progress:

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
| PostgreSQL | `localhost:5432` | Bound to `127.0.0.1` only, not exposed externally |

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

# Full reset (wipes all data, rebuilds from empty):
docker compose exec db psql -U dealflow -d dealflow360 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed

# --- Backend -----------------------------------------------------------------
docker compose exec backend pytest                 # 124 tests (run the seed first - some read seeded rows)
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
docker compose exec db psql -U dealflow -d dealflow360

# --- Logs / status -----------------------------------------------------------
docker compose ps
docker compose logs backend --tail 50
docker compose logs frontend --tail 50

# --- Stop everything ---------------------------------------------------------
docker compose down          # stop, keep data
docker compose down -v       # stop, DELETE all data (fresh start next time)
```

---

## Troubleshooting

**`docker compose` fails with "cannot connect to the Docker daemon" / a pipe error (Windows).**
Docker Desktop isn't running. Start it (Start Menu → Docker Desktop, or on
Windows: `Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"`
in PowerShell) and wait ~30-60 seconds for the whale icon to stop animating,
then retry.

**A port is already in use (`5173`, `8000`, or `5432`).**
Something else on the machine is using it. Either stop that process, or edit
the port mapping on the left-hand side in `docker-compose.yml` (e.g.
`"5174:5173"`) and use the new port in your browser.

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
Click **+ New Quotation** to create one, or see `DEMO.md` for a full script
that populates realistic demo data as it goes.

**`alembic upgrade head` or the seed command fails right after `docker compose up`.**
The backend started before Postgres finished initializing on a very slow
first boot. Wait ~10 seconds and retry — `docker compose ps` should show `db`
as `healthy` before either command is expected to work.

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
├── DEMO.md                  Verified demo script — what to click, expected numbers
├── docs/erd.md              ERD, system architecture diagram, state machines
├── docker-compose.yml       Postgres + backend + frontend (no Redis)
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
