"""Notification schemas.

A notification is never *created* by a client — it is a side effect of
something that happened. There is no ``NotificationCreate`` here on purpose:
the only writes a caller can make are marking one, or all, as read.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.tenant import NotificationChannel


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel: NotificationChannel
    category: str
    title: str
    body: str | None = None
    link: str | None = None
    payload: dict[str, Any] | None = None
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime


class NotificationFeed(BaseModel):
    """The bell menu in one request: the recent items and the badge number.

    Two calls would let the list and the badge disagree while a colleague is
    resolving tickets in the next room.
    """

    items: list[NotificationRead]
    unread: int
    total: int


class MarkReadRequest(BaseModel):
    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=200)]


class MarkReadResult(BaseModel):
    marked: int
    unread: int


class RealtimeStatus(BaseModel):
    """What the ``/ws`` endpoint is doing right now, for the health screen."""

    connections: int
    users: int
    society_connections: int
