"""Tenant-local user identity.

Mirrors a ``platform_users`` row. ``firebase_uid`` is denormalised here so
building a Principal costs one tenant query rather than a join back through the
central database.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import TenantBase, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.tenant.rbac import UserRole


class TenantUser(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    __tablename__ = "users"

    firebase_uid: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(10))
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user_roles: Mapped[list[UserRole]] = relationship(
        back_populates="user",
        lazy="selectin",
        cascade="all, delete-orphan",
        # user_roles has two FKs to users (user_id, assigned_by), so the join
        # column must be named explicitly.
        foreign_keys="UserRole.user_id",
    )

    __table_args__ = (
        CheckConstraint(r"phone IS NULL OR phone ~ '^[6-9][0-9]{9}$'", name="phone_format"),
        Index("ux_users_email_lower", func.lower(email), unique=True),
        Index("ix_users_active", "is_active", postgresql_where="is_active"),
    )

    def __repr__(self) -> str:
        return f"<TenantUser {self.email}>"
