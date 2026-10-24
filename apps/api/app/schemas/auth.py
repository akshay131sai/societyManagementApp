"""Authentication schemas.

``/auth/me`` returns everything the client shell needs — principal, society,
subscription, theme and navigation — in one call, so the app renders without a
request waterfall.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.central import SocietyStatus, SubscriptionStatus
from app.schemas.theme import ThemeRead


class PrincipalRead(BaseModel):
    id: uuid.UUID
    firebase_uid: str
    email: str
    display_name: str
    is_super_admin: bool
    society_id: uuid.UUID | None = None
    tenant_user_id: uuid.UUID | None = None
    roles: list[str]
    permissions: list[str]
    flat_ids: list[uuid.UUID] = []


class SocietyContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    status: SocietyStatus
    city: str
    state: str
    timezone: str
    total_flats: int


class SubscriptionContext(BaseModel):
    status: SubscriptionStatus
    plan_name: str | None = None
    start_date: date
    end_date: date
    days_remaining: int
    is_trial: bool


class NavItem(BaseModel):
    key: str
    label: str
    icon: str
    path: str
    permission: str | None = None
    badge: str | None = None
    children: list[NavItem] = []


class MeResponse(BaseModel):
    """One call bootstraps the entire client shell."""

    principal: PrincipalRead
    society: SocietyContext | None = None
    subscription: SubscriptionContext | None = None
    theme: ThemeRead | None = None
    navigation: list[NavItem] = []
    auth_provider: str
    """``"dev"`` makes the frontend render a persistent development badge."""
    server_time: datetime


class SessionResponse(BaseModel):
    recorded: bool
    last_login_at: datetime | None = None


NavItem.model_rebuild()
