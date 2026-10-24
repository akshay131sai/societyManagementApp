"""Alembic environment for the CENTRAL database.

Uses a synchronous psycopg engine: Alembic's migration context is synchronous,
and running DDL through the async bridge buys nothing here.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.config import get_settings  # noqa: E402
from app.database.base import CentralBase  # noqa: E402

# Import for the side effect of registering models on CentralBase.metadata.
import app.models.central  # noqa: E402,F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = CentralBase.metadata

if not config.get_main_option("sqlalchemy.url", None):
    # Escaped: a password containing '%' would otherwise break ConfigParser
    # interpolation.
    config.set_main_option(
        "sqlalchemy.url", get_settings().central_dsn_sync.replace("%", "%%")
    )


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
