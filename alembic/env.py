"""Alembic environment — async-aware, driven by application settings.

Imports ``app.models`` so every table is registered on ``Base.metadata``
for autogenerate. Migrations run against a *direct* Postgres connection
(bypassing PgBouncer) because DDL needs a real session.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.db.base import Base

# Importing the models package registers all models on Base.metadata.
import app.models  # noqa: F401,E402  (side-effect import)

config = context.config
config.set_main_option("sqlalchemy.url", settings.migration_database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _include_object(obj: object, name: str | None, type_: str, *_: object) -> bool:
    # Never let autogenerate try to drop the pgvector extension's artefacts.
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.migration_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": settings.migration_database_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={
            "statement_cache_size": 0,
            # Fail loudly instead of hanging a deploy forever when a stale
            # connection (e.g. from a killed container) still holds a lock.
            "server_settings": {"lock_timeout": "15s"},
        },
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
