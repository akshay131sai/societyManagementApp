"""Society — the tenant root record."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import CentralBase, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.central.enums import SocietyStatus, society_status_enum

if TYPE_CHECKING:
    from app.models.central.registry import DatabaseRegistry
    from app.models.central.subscription import Subscription
    from app.models.central.user import PlatformUser


class Society(UUIDPrimaryKeyMixin, TimestampMixin, CentralBase):
    __tablename__ = "societies"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    """URL-safe identifier. Immutable after creation."""

    registration_number: Mapped[str | None] = mapped_column(String(100))

    address_line1: Mapped[str | None] = mapped_column(String(255))
    address_line2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    pincode: Mapped[str] = mapped_column(String(6), nullable=False)

    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(10), nullable=False)

    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Asia/Kolkata"
    )

    status: Mapped[SocietyStatus] = mapped_column(
        society_status_enum,
        nullable=False,
        server_default=SocietyStatus.PROVISIONING.value,
        index=True,
    )

    total_flats: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    """Denormalised counter.

    Kept here so the Super Admin society list renders one column without fanning
    out a query across every tenant database.
    """

    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_reason: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        # societies <-> platform_users is a genuine cycle (a society records who
        # created it; a user records which society they belong to). use_alter
        # defers this constraint to an ALTER TABLE after both tables exist.
        ForeignKey(
            "platform_users.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_societies_created_by_platform_users",
        ),
    )

    registry: Mapped[DatabaseRegistry | None] = relationship(
        back_populates="society", uselist=False, lazy="selectin"
    )
    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="society", lazy="noload"
    )

    __table_args__ = (
        CheckConstraint(r"pincode ~ '^[1-9][0-9]{5}$'", name="pincode_format"),
        CheckConstraint(r"contact_phone ~ '^[6-9][0-9]{9}$'", name="phone_format"),
        CheckConstraint(r"slug ~ '^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$'", name="slug_format"),
        Index(
            "ix_societies_status_active",
            "status",
            postgresql_where="status <> 'ARCHIVED'",
        ),
    )

    @property
    def is_accessible(self) -> bool:
        return self.status is SocietyStatus.ACTIVE

    def __repr__(self) -> str:
        return f"<Society {self.slug} status={self.status}>"


class SocietyAdminAssignment(UUIDPrimaryKeyMixin, TimestampMixin, CentralBase):
    """Audit trail of who administers which society.

    The *live* mapping is ``platform_users.society_id``; this table records the
    history, including revocations.
    """

    __tablename__ = "society_admin_assignments"

    society_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("societies.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("platform_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL")
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL")
    )
    revoked_reason: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    __table_args__ = (
        Index(
            "ux_society_admin_active",
            "society_id",
            "platform_user_id",
            unique=True,
            postgresql_where="is_active",
        ),
    )
