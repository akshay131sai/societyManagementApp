"""DatabaseRegistry — the only place a tenant database is resolved from.

Credentials are deliberately **not** stored here; they come from the
environment. A dump of the central database therefore contains no usable
tenant credentials.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Sequence,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import CentralBase, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.central.enums import ProvisioningState, provisioning_state_enum

if TYPE_CHECKING:
    from app.models.central.society import Society

society_db_seq = Sequence("society_db_seq", start=1, metadata=CentralBase.metadata)
"""Allocates the numeric suffix in ``nestflow_society_NNNN``."""


class DatabaseRegistry(UUIDPrimaryKeyMixin, TimestampMixin, CentralBase):
    __tablename__ = "database_registry"

    society_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("societies.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    database_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)

    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5432")
    """Stored so a society can be relocated to another instance later."""

    provisioning_state: Mapped[ProvisioningState] = mapped_column(
        provisioning_state_enum,
        nullable=False,
        server_default=ProvisioningState.PENDING.value,
    )
    provisioning_error: Mapped[str | None] = mapped_column(Text)
    provisioning_step: Mapped[str | None] = mapped_column(String(80))

    alembic_revision: Mapped[str | None] = mapped_column(String(64))
    """Tenant migration head actually applied.

    Makes "which societies are on which revision" answerable from one central
    query, which is otherwise unanswerable in a database-per-tenant design.
    """
    migrated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    society: Mapped[Society] = relationship(back_populates="registry", lazy="noload")

    __table_args__ = (
        CheckConstraint(
            r"database_name ~ '^nestflow_society_[0-9]{4,10}$'",
            name="database_name_format",
        ),
    )

    @property
    def is_ready(self) -> bool:
        return self.provisioning_state is ProvisioningState.COMPLETED

    def __repr__(self) -> str:
        return f"<DatabaseRegistry {self.database_name} {self.provisioning_state}>"
