# African Investment Hub — Backend

FastAPI backend for the African Investment Hub platform (see
[`../docs/PRD_African_Investment_Hub.md`](../docs/PRD_African_Investment_Hub.md)).

**Stack:** FastAPI · Python 3.12 · SQLAlchemy 2.0 (async) · PostgreSQL 16 +
pgvector · Redis 7 · ARQ · Clerk (JWT) · OpenAI · Cloudflare R2 · Resend ·
Sentry · Langfuse.

---

## Quick start (Docker)

```bash
cd backend
cp .env.example .env          # fill in real keys for live integrations
docker compose up --build
```

- API: http://localhost:8000
- Health: http://localhost:8000/health
- OpenAPI docs: http://localhost:8000/docs (dev/staging only)
- Metrics: http://localhost:8000/metrics

Run database migrations (once the stack is up):

```bash
docker compose exec api alembic upgrade head
```

## Local development (no Docker)

Requires Python 3.12, a reachable PostgreSQL 16 + pgvector, and Redis 7.

```bash
cd backend
python -m venv .venv
. .venv/Scripts/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

cp .env.example .env            # point POSTGRES_HOST/REDIS_HOST at localhost
alembic upgrade head
uvicorn app.main:app --reload
```

## Tasks

| Command | Purpose |
|---|---|
| `uvicorn app.main:app --reload` | Run the API server |
| `arq app.workers.worker.WorkerSettings` | Run the ARQ background worker |
| `alembic upgrade head` | Apply migrations |
| `alembic revision --autogenerate -m "msg"` | Generate a migration |
| `ruff check . && ruff format --check .` | Lint / format check |
| `mypy app` | Static type check |
| `pytest` | Run tests with coverage (≥85% gate) |
| `pre-commit install` | Install git hooks |

## Project layout

```
app/
  core/      config, security, logging, encryption, rate limiting, i18n, errors
  db/        declarative base, mixins, async session
  models/    SQLAlchemy models (all entities — PRD §10)
  schemas/   Pydantic request/response models
  api/v1/    routers (health, investors, projects, consultants, countries, ai, admin/…)
  services/  business logic (thin endpoints, fat services), external clients, ai/
  workers/   ARQ worker + background tasks
alembic/     migrations
tests/       unit + integration
```

## Configuration

All configuration is environment-driven via `app/core/config.py`
(`pydantic-settings`). See [`.env.example`](.env.example) for the full,
documented list. Real third-party credentials (Clerk, OpenAI, R2, Resend,
Sentry, Langfuse) are supplied per environment; the test suite stubs them.

## Phasing

Phase 1 endpoints are fully implemented. Phase 2/3 endpoints are routed and
documented but return `501 Not Implemented` until `FEATURE_PHASE2` /
`FEATURE_PHASE3` are enabled. See the PRD §5 for scope.
