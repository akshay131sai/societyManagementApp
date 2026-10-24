"""Declarative bases and shared column mixins.

Central and tenant models use **separate** ``MetaData`` objects. This is what
lets Alembic autogenerate two independent migration histories without either
one trying to create the other's tables — and it makes "did this table end up
in the wrong database?" a static, greppable question.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
"""Deterministic constraint names.

Without this, PostgreSQL invents names and Alembic autogenerate produces
migrations that cannot drop the constraints it created on another machine.
"""


class CentralBase(DeclarativeBase):
    """Base for tables in ``nestflow_platform``."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TenantBase(DeclarativeBase):
    """Base for tables in every ``nestflow_society_NNNN`` database."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# --------------------------------------------------------------------------- #
# Mixins
# --------------------------------------------------------------------------- #


class UUIDPrimaryKeyMixin:
    """UUID v4 primary key generated in the database."""

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )


class TimestampMixin:
    """``created_at`` / ``updated_at``, always UTC, maintained by the database.

    ``server_default``/``onupdate`` rather than Python defaults, so rows written
    by a migration or by ``psql`` get correct timestamps too.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
