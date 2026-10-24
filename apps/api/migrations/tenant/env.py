"""Alembic environment for TENANT databases.

The target database is supplied by the caller, either as
``-x database_name=nestflow_society_0001`` or via ``config.attributes`` when
invoked programmatically by :class:`TenantDatabaseManager`.

The name is validated against ``DB_NAME_PATTERN`` before a DSN is built, so a
migration cannot be pointed at an arbitrary database.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.config import DB_NAME_PATTERN, get_settings  # noqa: E402
from app.database.base import TenantBase  # noqa: E402

# Import for the side effect of registering models on TenantBase.metadata.
import app.models.tenant  # noqa: E402,F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = TenantBase.metadata


def _resolve_database_name() -> str | None:
    if (name := config.attributes.get("database_name")) is not None:
        return str(name)
    return context.get_x_argument(as_dictionary=True).get("database_name")


def _resolve_url() -> str:
    if url := config.get_main_option("sqlalchemy.url", None):
        return url

    database_name = _resolve_database_name()
    if not database_name:
        raise RuntimeError(
            "Tenant migrations need a target database. Pass "
            "-x database_name=nestflow_society_NNNN, or invoke through "
            "TenantDatabaseManager.run_migrations()."
        )
    if not DB_NAME_PATTERN.match(database_name):
        raise RuntimeError(
            f"Refusing to migrate {database_name!r}; tenant database names must "
            f"match {DB_NAME_PATTERN.pattern}"
        )
    return get_settings().tenant_dsn_sync(database_name).replace("%", "%%")


config.set_main_option("sqlalchemy.url", _resolve_url())


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
