"""In-app notifications."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import TenantBase, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.tenant.enums import NotificationChannel, notification_channel_enum


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    channel: Mapped[NotificationChannel] = mapped_column(
        notification_channel_enum,
        nullable=False,
        server_default=NotificationChannel.IN_APP.value,
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(500))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Partial index: the bell badge only ever queries unread rows, so this
        # stays small no matter how much history accumulates.
        Index(
            "ix_notifications_unread",
            "user_id",
            "created_at",
            postgresql_where="NOT is_read",
        ),
        Index("ix_notifications_user", "user_id", "created_at"),
    )
