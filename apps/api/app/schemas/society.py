"""Society-scoped schemas (tenant side).

None of these carry a ``society_id`` — the tenant is the session.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.auth import NewPassword
from app.schemas.platform import IndianMobile, Pincode


class SocietySettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    society_name: str
    registration_number: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    timezone: str
    currency: str
    locale: str
    financial_year_start_month: int
    default_billing_cycle: str
    bill_due_days: int
    late_fee_percent: Decimal
    late_fee_grace_days: int
    updated_at: datetime | None = None


class SocietySettingsUpdate(BaseModel):
    society_name: Annotated[str | None, Field(min_length=3, max_length=200)] = None
    registration_number: Annotated[str | None, Field(max_length=100)] = None
    address_line1: Annotated[str | None, Field(max_length=255)] = None
    address_line2: Annotated[str | None, Field(max_length=255)] = None
    city: Annotated[str | None, Field(max_length=100)] = None
    state: Annotated[str | None, Field(max_length=100)] = None
    pincode: Pincode | None = None
    contact_email: EmailStr | None = None
    contact_phone: IndianMobile | None = None
    timezone: Annotated[str | None, Field(max_length=64)] = None
    financial_year_start_month: Annotated[int | None, Field(ge=1, le=12)] = None
    default_billing_cycle: Annotated[
        str | None, Field(pattern=r"^(MONTHLY|QUARTERLY|HALF_YEARLY|YEARLY|ONE_TIME)$")
    ] = None
    bill_due_days: Annotated[int | None, Field(ge=0, le=90)] = None
    late_fee_percent: Annotated[Decimal | None, Field(ge=0, le=100)] = None
    late_fee_grace_days: Annotated[int | None, Field(ge=0, le=90)] = None


class SocietyDashboard(BaseModel):
    society_name: str
    total_users: int
    active_users: int
    total_flats: int
    total_buildings: int
    total_residents: int = 0
    occupancy: dict[str, int] = {}
    unread_notifications: int
    roles_summary: dict[str, int]
    subscription_status: str
    subscription_days_remaining: int
    provisioned_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Tenant users
# --------------------------------------------------------------------------- #


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    is_system: bool


class RoleWithPermissions(RoleRead):
    permissions: list[str] = []


class TenantUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None = None
    avatar_url: str | None = None
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime
    roles: list[str] = []


class TenantUserCreate(BaseModel):
    email: EmailStr
    full_name: Annotated[str, Field(min_length=2, max_length=150)]
    phone: IndianMobile | None = None
    role_codes: Annotated[list[str], Field(min_length=1)]
    firebase_uid: Annotated[str | None, Field(max_length=128)] = None
    password: NewPassword | None = None
    """Initial sign-in password (``AUTH_PROVIDER=password``). Without one the
    account exists but cannot sign in until a password is set."""


class TenantUserUpdate(BaseModel):
    full_name: Annotated[str | None, Field(min_length=2, max_length=150)] = None
    phone: IndianMobile | None = None
    avatar_url: Annotated[str | None, Field(max_length=500)] = None
    is_active: bool | None = None


class UserRolesUpdate(BaseModel):
    role_codes: Annotated[list[str], Field(min_length=1)]
