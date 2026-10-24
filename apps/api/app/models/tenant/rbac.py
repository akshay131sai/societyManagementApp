"""Tenant RBAC tables.

Seeded at provisioning from ``app.core.permissions.ROLE_PERMISSIONS``. Runtime
reads these *tables*, not the Python constant, which is what makes a per-society
custom role possible later without changing the shipped default.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import TenantBase, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.tenant.user import TenantUser


class RoleRow(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    """System roles cannot be deleted or have their permission set edited via
    the API. A society may *add* custom roles, not weaken the built-ins."""

    role_permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role", lazy="selectin", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Role {self.code}>"


class PermissionRow(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    resource: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_permissions_resource", "resource"),)

    def __repr__(self) -> str:
        return f"<Permission {self.code}>"


class RolePermission(TenantBase):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )

    role: Mapped[RoleRow] = relationship(back_populates="role_permissions", lazy="noload")
    permission: Mapped[PermissionRow] = relationship(lazy="selectin")


class UserRole(TenantBase):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[TenantUser] = relationship(
        back_populates="user_roles",
        lazy="noload",
        foreign_keys=[user_id],
    )
    role: Mapped[RoleRow] = relationship(lazy="selectin")

    __table_args__ = (Index("ix_user_roles_user", "user_id"),)
