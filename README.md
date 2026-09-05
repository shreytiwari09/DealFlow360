# DealFlow360

A self-governing B2B sales operations platform — quote-to-cash with automatic
discount discipline, real-time multi-warehouse inventory awareness, reconciled
one-time + recurring billing on a single order, and a live customer negotiation
portal.

**Stack:** FastAPI (Python 3.12) · React + TypeScript (Vite) · PostgreSQL 16 ·
SQLAlchemy 2 (async) + Alembic · Docker Compose.

> **Status: Phases 1-2 complete, Phase 3 in progress.** The stack runs, 30 tables
> are under migration control, the blended risk engine is implemented and tested,
> and demo seed data exists. There is no authentication and no designed UI yet —
> see `IMPLEMENTATION_LOG.md` for exactly what exists.

### Demo logins

Run the seed, then use `admin@`, `manager@`, `rep@` or `finance@dealflow360.example`,
or `portal@acme.example`, all with password `DealFlow360!demo`. These are dev-only
fixtures — override with `SEED_DEFAULT_PASSWORD`. Login endpoints are not built
yet; the accounts exist ready for them.

---

## Quick start

Requires Docker Desktop. Nothing else needs to be installed locally.

```bash
cp .env.example .env          # then edit .env - see "Secrets" below
docker compose up --build
```

| Service | URL |
|---|---|
| Backend API | http://localhost:8000 |
| API docs (dev only) | http://localhost:8000/docs |
| Frontend | http://localhost:5173 |
| PostgreSQL | `localhost:5432` (bound to 127.0.0.1 only) |

Check it came up:

```bash
curl http://localhost:8000/api/v1/health/ready
# {"status":"ok","environment":"development","database":"ok"}
```

### Secrets

`POSTGRES_PASSWORD` and `JWT_SECRET_KEY` have **no defaults in code** — the app
refuses to start without them, so a placeholder can never silently ship
(SECURITY_SPEC.md §8). Generate a real signing key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env` is gitignored. Only `.env.example`, which contains placeholders, is
committed.

---

## Common commands

All run against the live containers.

```bash
# Seed demo data (idempotent - safe to re-run)
docker compose exec backend python -m app.seed

# Backend
docker compose exec backend pytest                 # tests (seed first - some
                                                   # tests read seeded rows)
docker compose exec backend ruff check .           # lint
docker compose exec backend ruff format .          # format

# Migrations (Alembic - never `create_all`)
docker compose exec backend alembic revision --autogenerate -m "add quotations"
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1
docker compose exec backend alembic current

# Frontend
docker compose exec frontend npm run typecheck
docker compose exec frontend npm run build

# Database shell
docker compose exec db psql -U dealflow -d dealflow360
```

Reset the database completely (destroys the volume):

```bash
docker compose down -v && docker compose up --build
```

---

## Repository layout

```
├── PLAN.md                  Execution roadmap — phases, order, exit conditions
├── PROJECT_CONTEXT.md       Current architecture, decisions, open questions
├── IMPLEMENTATION_LOG.md    Chronological record of what was actually built
├── SECURITY_SPEC.md         Authoritative security implementation contract
├── docs/erd.md              ERD, architecture and state machines
├── docker-compose.yml       Postgres + backend + frontend (no Redis)
├── .env.example             Placeholder environment file
│
├── backend/
│   ├── alembic/             Versioned migrations (async env.py)
│   ├── app/
│   │   ├── main.py          FastAPI app: CORS, error handlers, router
│   │   ├── core/            config · logging · error handling
│   │   ├── db/              declarative Base + naming convention, async session
│   │   ├── models/          30 tables across 11 domain modules
│   │   ├── schemas/         Pydantic request/response DTOs
│   │   ├── services/        risk.py (blended score + routing),
│   │   │                    state_machine.py — both pure, no I/O
│   │   ├── seed.py          Idempotent demo seed
│   │   └── api/
│   │       ├── deps.py      Shared dependencies (auth/permissions in Phase 6)
│   │       └── v1/          Versioned routers and endpoints
│   └── tests/
│
└── frontend/
    └── src/                 React + TypeScript (UI held until design input)
```

---

## Working on this project

Read `PLAN.md` first — it governs build order and process. Two rules matter
most and are easy to violate accidentally:

- **§0.6 Ask, Don't Assume.** Six business rules are now locked and written up
  under "Locked Business Rules" in `PROJECT_CONTEXT.md` — do not redefine them.
  Others (deal-health thresholds, warehouse tie-break) are still open. Do not
  invent them in code: ask, then record the answer there.
- **Phase 8 frontend hold.** No visual design system has been provided yet. The
  current React page is an unstyled connectivity placeholder, not a design
  decision. Do not build screens until the mockup/design resource arrives.

After any meaningful task, append an entry to `IMPLEMENTATION_LOG.md` in its
defined format.
