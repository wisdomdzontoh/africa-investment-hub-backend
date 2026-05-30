"""Test fixtures.

Spins up a disposable schema on a real Postgres+pgvector database, overrides
the request DB session, swaps Redis for fakeredis, stubs external clients
(OpenAI / R2 / queue), and provides an authenticated test client whose current
user can be set per test (no real Clerk JWTs needed).

The test database URL defaults to the ``postgres`` compose service; override
with ``TEST_DATABASE_URL`` (CI sets this).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Ensure a valid 32-byte encryption key exists before any app module reads
# settings. The container's env_file can inject an *empty* value, so overwrite
# when blank (env vars take precedence over .env in pydantic-settings).
# "0123...ef" → urlsafe-base64; decodes to exactly 32 bytes.
if not os.environ.get("FIELD_ENCRYPTION_KEY"):
    os.environ["FIELD_ENCRYPTION_KEY"] = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://aih:aih_password@postgres:5432/aih_test",
)

import app.models  # noqa: E402,F401  (register all models for create_all)
from app.api import deps  # noqa: E402
from app.core import redis as redis_module  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402  ('app' alone is the package)
from app.models.enums import UserRole, UserStatus  # noqa: E402
from app.models.user import User  # noqa: E402


async def _ensure_database() -> None:
    """Create the test database (and pgvector extension) if missing."""
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    admin_engine = create_async_engine(
        admin_url, isolation_level="AUTOCOMMIT", connect_args={"statement_cache_size": 0}
    )
    async with admin_engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()


# A single module-level engine using NullPool so each operation opens a fresh
# connection on the current event loop — this sidesteps pytest-asyncio
# cross-loop binding without rebuilding the schema per test.
_engine = create_async_engine(
    TEST_DATABASE_URL, poolclass=NullPool, connect_args={"statement_cache_size": 0}
)
_schema_ready = False


async def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    await _ensure_database()
    async with _engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    _schema_ready = True


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Per-test session. Schema is created once; tables truncated each test."""
    await _ensure_schema()
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with _engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    async with async_sessionmaker(bind=_engine, expire_on_commit=False)() as session:
        yield session


# ─────────────────────── External-service stubs ───────────────────────
@pytest.fixture(autouse=True)
def _stub_externals(monkeypatch) -> None:
    import fakeredis.aioredis

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis", fake, raising=False)
    monkeypatch.setattr(redis_module, "get_redis", lambda: fake)

    # No-op the ARQ enqueue so tests never touch a real broker.
    async def _noop_enqueue(*_a, **_k) -> None:
        return None

    monkeypatch.setattr("app.workers.queue.enqueue", _noop_enqueue)
    monkeypatch.setattr("app.services.investor_service.enqueue", _noop_enqueue)
    monkeypatch.setattr("app.services.project_service.enqueue", _noop_enqueue)
    monkeypatch.setattr("app.services.consultant_service.enqueue", _noop_enqueue)
    monkeypatch.setattr("app.services.admin_service.enqueue", _noop_enqueue)
    monkeypatch.setattr("app.services.cms_service.enqueue", _noop_enqueue, raising=False)

    # Stub R2 storage (no network).
    monkeypatch.setattr(
        "app.services.storage.presign_put", lambda key, ct: f"https://r2.test/put/{key}"
    )
    monkeypatch.setattr(
        "app.services.storage.presign_get", lambda key, **k: f"https://r2.test/get/{key}"
    )
    monkeypatch.setattr("app.services.storage.delete_object", lambda key: None)


# ─────────────────────────── Auth / client ───────────────────────────
class _UserBox:
    """Holds the user the overridden auth dependencies should return."""

    current: User | None = None


@pytest_asyncio.fixture
async def client(db) -> AsyncGenerator[AsyncClient, None]:
    sessionmaker = async_sessionmaker(bind=_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Re-fetch the active user via the *request* session (as production does),
    # so routes that mutate the current user persist correctly.
    async def _override_current_user(session: AsyncSession = Depends(get_db)) -> User:
        if _UserBox.current is None:
            from app.core.exceptions import UnauthorizedError

            raise UnauthorizedError("Missing authentication credentials.")
        user = await session.get(User, _UserBox.current.id)
        if user is None:
            from app.core.exceptions import UnauthorizedError

            raise UnauthorizedError("Missing authentication credentials.")
        if user.deleted_at is not None or user.status == UserStatus.suspended:
            from app.core.exceptions import UnauthorizedError

            raise UnauthorizedError("This account has been deactivated.")
        return user

    async def _override_optional_user(session: AsyncSession = Depends(get_db)) -> User | None:
        if _UserBox.current is None:
            return None
        return await session.get(User, _UserBox.current.id)

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    fastapi_app.dependency_overrides[deps.get_current_user] = _override_current_user
    fastapi_app.dependency_overrides[deps.get_optional_user] = _override_optional_user

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    fastapi_app.dependency_overrides.clear()
    _UserBox.current = None


@pytest_asyncio.fixture
async def make_user(db):
    """Factory: create and persist a user, returning it."""

    async def _make(
        *, role: UserRole = UserRole.investor, status: UserStatus = UserStatus.approved
    ) -> User:
        user = User(clerk_id=f"clerk_{uuid.uuid4().hex}", email="u@test.com", role=role, status=status)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    return _make


@pytest.fixture
def auth_as():
    """Set the authenticated user for subsequent client requests."""

    def _set(user: User | None) -> None:
        _UserBox.current = user

    return _set
