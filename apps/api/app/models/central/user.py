"""PlatformUser — the ``firebase_uid`` -> society mapping.

This table is the hinge of tenant isolation: it is the only place the
authenticated identity is turned into a society, and therefore into a database.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import CentralBase, TimestampMixin, UUIDPrimaryKeyMixin


class PlatformUser(UUIDPrimaryKeyMixin, TimestampMixin, CentralBase):
    __tablename__ = "platform_users"

    firebase_uid: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(10))
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)

    is_super_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    society_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("societies.id", ondelete="CASCADE"),
    )
    """NULL if and only if ``is_super_admin``. Enforced by ``ck_scope`` below."""

    tenant_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    """Id of the matching row in the tenant ``users`` table."""

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # A super admin scoped to a society is the shape most tenant-escape bugs
        # need. Make it unrepresentable rather than merely untested.
        CheckConstraint(
            "(is_super_admin AND society_id IS NULL) "
            "OR (NOT is_super_admin AND society_id IS NOT NULL)",
            name="scope",
        ),
        CheckConstraint(
            r"phone IS NULL OR phone ~ '^[6-9][0-9]{9}$'", name="phone_format"
        ),
        Index("ix_platform_users_email_lower", func.lower(email)),
        Index(
            "ix_platform_users_society",
            "society_id",
            postgresql_where="society_id IS NOT NULL",
        ),
        # The same person may be a resident in two societies -> two Firebase
        # accounts, two rows. Email is unique per society, not globally.
        Index(
            "ux_platform_users_society_email",
            "society_id",
            func.lower(email),
            unique=True,
            postgresql_where="society_id IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        scope = "platform" if self.is_super_admin else f"society={self.society_id}"
        return f"<PlatformUser {self.email} {scope}>"
