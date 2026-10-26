"""Refresh tokens — the server-side half of a NestFlow session.

Access tokens are stateless and short-lived. Refresh tokens are long-lived, so
each one is recorded here by its ``jti`` and can be revoked. Every refresh
rotates: the presented token is retired and a new one issued in the same
``family_id``. Presenting a retired token again means it was copied, and the
whole family is revoked — the thief and the victim are both signed out, which
is the only safe outcome when you cannot tell them apart.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import CentralBase


class RefreshToken(CentralBase):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    """The token's ``jti``. Generated in Python because it is signed into the token."""

    platform_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("platform_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    family_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    """Shared by every token descended from one sign-in."""

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    """Set on rotation. A revoked token with no successor was signed out, not rotated."""

    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_refresh_tokens_user", "platform_user_id"),
        Index("ix_refresh_tokens_family", "family_id"),
    )
