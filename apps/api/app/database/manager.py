"""TenantDatabaseManager — the single gateway to tenant databases.

Every tenant connection in the application comes from here, keyed by a
``society_id`` that was resolved from the authenticated principal. Nothing else
in the codebase constructs a tenant engine or DSN.

Design notes
------------
* **Bounded LRU of engines.** One :class:`AsyncEngine` per society, each with a
  small pool. Eviction disposes the engine so connections are returned rather
  than leaked. Worst-case connection count is
  ``TENANT_ENGINE_CACHE_SIZE * (TENANT_POOL_SIZE + TENANT_POOL_MAX_OVERFLOW)``
  per worker — see docs/deployment/deployment.md section 3.

* **A connection is never created per request.** The per-request cost is a pool
  checkout.

* **Database names are generated, never accepted.** ``CREATE DATABASE`` cannot
  be parameterised, so every name reaching DDL is validated against
  ``DB_NAME_PATTERN`` *and* quoted with ``psycopg.sql.Identifier``.

* **DDL runs on its own autocommit connection.** ``CREATE DATABASE`` cannot run
  inside a transaction block.
"""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import structlog
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import DB_NAME_PATTERN, Settings, get_settings
from app.core.errors import NotFoundError, TenantDatabaseUnavailableError

log = structlog.get_logger(__name__)

# PostgreSQL SQLSTATEs raised by our own triggers and constraints. These are
# rules the application is stating, not failures of the database.
RULE_VIOLATION_SQLSTATES = frozenset(
    {
        "23505",  # unique_violation
        "23503",  # foreign_key_violation
        "23514",  # check_violation
        "23001",  # restrict_violation  (our immutability triggers)
        "23502",  # not_null_violation
        "P0001",  # raise_exception
    }
)


def _is_rule_violation(exc: Exception) -> bool:
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    return sqlstate in RULE_VIOLATION_SQLSTATES


class TenantDatabaseManager:
    """Owns tenant engines, tenant DDL and tenant migrations."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._engines: OrderedDict[UUID, AsyncEngine] = OrderedDict()
        self._sessionmakers: dict[UUID, async_sessionmaker[AsyncSession]] = {}
        self._db_names: dict[UUID, str] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Name safety
    # ------------------------------------------------------------------ #

    @staticmethod
    def validate_database_name(database_name: str) -> str:
        """Raise unless the name is a well-formed generated tenant DB name.

        This is the last gate before a name reaches DDL. It is deliberately a
        allowlist pattern, not an escape/sanitise step.
        """
        if not isinstance(database_name, str) or not DB_NAME_PATTERN.match(database_name):
            raise ValueError(
                f"Unsafe tenant database name {database_name!r}; "
                f"must match {DB_NAME_PATTERN.pattern}"
            )
        return database_name

    @staticmethod
    def build_database_name(sequence_number: int) -> str:
        """``7`` -> ``nestflow_society_0007``."""
        if sequence_number < 1:
            raise ValueError("sequence_number must be positive")
        return f"nestflow_society_{sequence_number:04d}"

    # ------------------------------------------------------------------ #
    # Engine cache
    # ------------------------------------------------------------------ #

    async def register(self, society_id: UUID, database_name: str) -> None:
        """Bind a society to its database name without opening a connection."""
        self.validate_database_name(database_name)
        async with self._lock:
            existing = self._db_names.get(society_id)
            if existing is not None and existing != database_name:
                # The society was moved to a different database; drop the stale
                # engine so no request can keep using the old one.
                await self._dispose_locked(society_id)
            self._db_names[society_id] = database_name

    async def get_engine(self, society_id: UUID) -> AsyncEngine:
        """Return the cached engine for a society, creating it on miss."""
        async with self._lock:
            engine = self._engines.get(society_id)
            if engine is not None:
                self._engines.move_to_end(society_id)
                return engine

            database_name = self._db_names.get(society_id)
            if database_name is None:
                raise NotFoundError(
                    "Tenant database registration",
                    details={"society_id": str(society_id)},
                )

            engine = self._create_engine(database_name)
            self._engines[society_id] = engine
            self._sessionmakers[society_id] = async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
            log.info(
                "tenant.engine.created",
                society_id=str(society_id),
                database=database_name,
                cached=len(self._engines),
            )
            await self._evict_if_needed()
            return engine

    def _create_engine(self, database_name: str) -> AsyncEngine:
        s = self._settings
        return create_async_engine(
            s.tenant_dsn_async(database_name),
            pool_size=s.TENANT_POOL_SIZE,
            max_overflow=s.TENANT_POOL_MAX_OVERFLOW,
            pool_recycle=s.POOL_RECYCLE_SECONDS,
            pool_timeout=s.POOL_TIMEOUT_SECONDS,
            pool_pre_ping=True,
            echo=False,
            future=True,
        )

    async def _evict_if_needed(self) -> None:
        """Dispose least-recently-used engines beyond the cache bound.

        Caller must hold ``self._lock``.
        """
        while len(self._engines) > self._settings.TENANT_ENGINE_CACHE_SIZE:
            society_id, engine = self._engines.popitem(last=False)
            self._sessionmakers.pop(society_id, None)
            log.info("tenant.engine.evicted", society_id=str(society_id))
            # Dispose outside the critical path but do not orphan the pool.
            await engine.dispose()

    @asynccontextmanager
    async def session(self, society_id: UUID) -> AsyncIterator[AsyncSession]:
        """Session bound to one society's database.

        Commits on success, rolls back on exception.
        """
        await self.get_engine(society_id)
        factory = self._sessionmakers[society_id]
        try:
            async with factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
        except IntegrityError:
            # A constraint or trigger rejection is a business rule — an
            # immutable bill, a duplicate flat number — not an outage. Telling
            # the user "try again shortly" would be actively misleading, so it
            # propagates to the handlers in app.main.
            raise
        except DBAPIError as exc:
            if _is_rule_violation(exc):
                raise
            log.error("tenant.session.failed", society_id=str(society_id), error=str(exc))
            raise TenantDatabaseUnavailableError() from exc
        except SQLAlchemyError as exc:
            log.error(
                "tenant.session.failed",
                society_id=str(society_id),
                error=str(exc),
            )
            raise TenantDatabaseUnavailableError() from exc

    async def dispose(self, society_id: UUID) -> None:
        async with self._lock:
            await self._dispose_locked(society_id)

    async def _dispose_locked(self, society_id: UUID) -> None:
        engine = self._engines.pop(society_id, None)
        self._sessionmakers.pop(society_id, None)
        if engine is not None:
            await engine.dispose()
            log.info("tenant.engine.disposed", society_id=str(society_id))

    async def dispose_all(self) -> None:
        async with self._lock:
            for society_id, engine in list(self._engines.items()):
                await engine.dispose()
                log.debug("tenant.engine.disposed", society_id=str(society_id))
            self._engines.clear()
            self._sessionmakers.clear()

    @property
    def cached_count(self) -> int:
        return len(self._engines)

    # ------------------------------------------------------------------ #
    # DDL
    # ------------------------------------------------------------------ #

    async def database_exists(self, database_name: str) -> bool:
        self.validate_database_name(database_name)
        return await asyncio.to_thread(self._database_exists_sync, database_name)

    async def create_database(self, database_name: str) -> bool:
        """Create the tenant database. Returns ``False`` if it already existed.

        Idempotent, so a resumed provisioning run does not fail here.
        """
        self.validate_database_name(database_name)
        created = await asyncio.to_thread(self._create_database_sync, database_name)
        log.info("tenant.database.create", database=database_name, created=created)
        return created

    async def drop_database(self, database_name: str) -> None:
        """Drop a tenant database. Archive / erasure only — never a rollback path."""
        self.validate_database_name(database_name)
        await asyncio.to_thread(self._drop_database_sync, database_name)
        log.warning("tenant.database.dropped", database=database_name)

    # --- sync helpers, run in a thread ---------------------------------- #

    def _maintenance_connection(self):  # type: ignore[no-untyped-def]
        """Autocommit psycopg connection to the maintenance database.

        ``CREATE DATABASE`` / ``DROP DATABASE`` cannot run inside a transaction.
        """
        import psycopg

        s = self._settings
        return psycopg.connect(
            host=s.TENANT_DB_HOST,
            port=s.TENANT_DB_PORT,
            user=s.TENANT_DB_USER,
            password=s.TENANT_DB_PASSWORD,
            dbname=s.TENANT_DB_MAINTENANCE_DB,
            autocommit=True,
        )

    def _database_exists_sync(self, database_name: str) -> bool:
        with self._maintenance_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database_name,),
            )
            return cur.fetchone() is not None

    def _create_database_sync(self, database_name: str) -> bool:
        self.validate_database_name(database_name)
        with self._maintenance_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
            if cur.fetchone() is not None:
                return False
            # Identifier() quotes safely; the name has already been allowlisted.
            cur.execute(
                sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(
                    sql.Identifier(database_name)
                )
            )
            return True

    def _drop_database_sync(self, database_name: str) -> None:
        self.validate_database_name(database_name)
        with self._maintenance_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )

    # ------------------------------------------------------------------ #
    # Migrations
    # ------------------------------------------------------------------ #

    async def run_migrations(self, database_name: str, revision: str = "head") -> str:
        """Run tenant Alembic migrations. Returns the applied head revision."""
        self.validate_database_name(database_name)
        head = await asyncio.to_thread(self._run_migrations_sync, database_name, revision)
        log.info("tenant.migrations.applied", database=database_name, revision=head)
        return head

    def _run_migrations_sync(self, database_name: str, revision: str) -> str:
        from pathlib import Path

        from alembic import command
        from alembic.config import Config

        api_root = Path(__file__).resolve().parents[2]
        cfg = Config(str(api_root / "alembic.tenant.ini"))
        cfg.set_main_option("script_location", str(api_root / "migrations" / "tenant"))
        cfg.set_main_option(
            "sqlalchemy.url",
            self._settings.tenant_dsn_sync(database_name).replace("%", "%%"),
        )
        cfg.attributes["database_name"] = database_name
        command.upgrade(cfg, revision)
        return self._current_revision_sync(database_name)

    def _current_revision_sync(self, database_name: str) -> str:
        import psycopg

        with psycopg.connect(
            host=self._settings.TENANT_DB_HOST,
            port=self._settings.TENANT_DB_PORT,
            user=self._settings.TENANT_DB_USER,
            password=self._settings.TENANT_DB_PASSWORD,
            dbname=database_name,
        ) as conn, conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
            row = cur.fetchone()
            return str(row[0]) if row else ""

    # ------------------------------------------------------------------ #
    # Diagnostics
    # ------------------------------------------------------------------ #

    async def current_database(self, society_id: UUID) -> str:
        """Ask the connection which database it is actually attached to.

        Used by the tenant-isolation tests to prove the engine cache hands back
        the right database under interleaved access.
        """
        async with self.session(society_id) as session:
            result = await session.execute(text("SELECT current_database()"))
            return str(result.scalar_one())


_manager: TenantDatabaseManager | None = None


def get_tenant_manager() -> TenantDatabaseManager:
    """Process-wide manager singleton."""
    global _manager
    if _manager is None:
        _manager = TenantDatabaseManager()
    return _manager


async def dispose_tenant_manager() -> None:
    global _manager
    if _manager is not None:
        await _manager.dispose_all()
        _manager = None
