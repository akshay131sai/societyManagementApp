"""Authentication schemas.

``/auth/me`` returns everything the client shell needs — principal, society,
subscription, theme and navigation — in one call, so the app renders without a
request waterfall.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.auth.passwords import password_problem
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


class LoginRequest(BaseModel):
    """Which fields are required depends on ``AUTH_PROVIDER``:

    * ``password`` — ``email`` and ``password``.
    * ``firebase`` — ``id_token``, a Firebase ID token.
    * ``dev`` — ``id_token`` of the form ``dev:<email>``.
    """

    id_token: str | None = Field(default=None, min_length=1, max_length=8192)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=128)


def _strong_enough(value: str) -> str:
    problem = password_problem(value)
    if problem:
        raise ValueError(problem)
    return value


NewPassword = Annotated[str, AfterValidator(_strong_enough)]
"""A password being set: checked against the policy before any work starts."""


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: NewPassword


class PasswordSet(BaseModel):
    """An administrator setting or resetting someone else's password."""

    password: NewPassword


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    """Seconds until ``access_token`` expires."""
    refresh_expires_in: int


class LogoutResponse(BaseModel):
    signed_out: bool


NavItem.model_rebuild()
