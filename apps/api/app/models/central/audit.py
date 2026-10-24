"""Platform audit log.

Append-only by convention. Production hardening revokes UPDATE/DELETE from the
application role (see docs/deployment/deployment.md section 10).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import CentralBase


class PlatformAuditLog(CentralBase):
    __tablename__ = "platform_audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    """BIGSERIAL, not UUID — this table is high volume and never joined by id."""

    request_id: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(80), nullable=False)

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL")
    )
    actor_email: Mapped[str | None] = mapped_column(String(255))
    """Denormalised so the trail survives deletion of the actor."""

    society_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("societies.id", ondelete="SET NULL")
    )

    target_type: Mapped[str | None] = mapped_column(String(60))
    target_id: Mapped[str | None] = mapped_column(String(80))

    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """``{"before": {...}, "after": {...}}``. Secrets stripped before write."""

    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="SUCCESS")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_platform_audit_created", created_at.desc()),
        Index("ix_platform_audit_society", "society_id", created_at.desc()),
        Index("ix_platform_audit_actor", "actor_id", created_at.desc()),
        Index("ix_platform_audit_action", "action", created_at.desc()),
    )


class AuditAction:
    """Stable action identifiers. Strings live here, not scattered in services."""

    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    TOKEN_REJECTED = "TOKEN_REJECTED"
    USER_NOT_REGISTERED = "USER_NOT_REGISTERED"
    PERMISSION_DENIED = "PERMISSION_DENIED"

    SOCIETY_CREATED = "SOCIETY_CREATED"
    SOCIETY_UPDATED = "SOCIETY_UPDATED"
    SOCIETY_PROVISIONED = "SOCIETY_PROVISIONED"
    SOCIETY_PROVISIONING_FAILED = "SOCIETY_PROVISIONING_FAILED"
    SOCIETY_LOCKED = "SOCIETY_LOCKED"
    SOCIETY_UNLOCKED = "SOCIETY_UNLOCKED"
    SOCIETY_ARCHIVED = "SOCIETY_ARCHIVED"

    PLAN_CREATED = "PLAN_CREATED"
    PLAN_UPDATED = "PLAN_UPDATED"
    SUBSCRIPTION_ASSIGNED = "SUBSCRIPTION_ASSIGNED"
    SUBSCRIPTION_EXTENDED = "SUBSCRIPTION_EXTENDED"
    SUBSCRIPTION_SUSPENDED = "SUBSCRIPTION_SUSPENDED"
    SUBSCRIPTION_CANCELLED = "SUBSCRIPTION_CANCELLED"

    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    USER_DISABLED = "USER_DISABLED"
    USER_DELETED = "USER_DELETED"
    ROLE_CHANGED = "ROLE_CHANGED"
    ADMIN_ASSIGNED = "ADMIN_ASSIGNED"
    ADMIN_REVOKED = "ADMIN_REVOKED"

    THEME_UPDATED = "THEME_UPDATED"
    SETTINGS_UPDATED = "SETTINGS_UPDATED"

    TEMPLATE_CREATED = "TEMPLATE_CREATED"
    TEMPLATE_VERSION_CREATED = "TEMPLATE_VERSION_CREATED"
    BILLING_RUN_STARTED = "BILLING_RUN_STARTED"
    BILLS_PUBLISHED = "BILLS_PUBLISHED"
    PAYMENT_RECORDED = "PAYMENT_RECORDED"
    SECURITY_EVENT = "SECURITY_EVENT"
