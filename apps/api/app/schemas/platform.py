"""Platform (Super Admin) request/response schemas.

Note that ``SocietyCreate`` is the *only* schema in the codebase that carries
society identity as input — because it is creating one. Every other endpoint
resolves the society from the principal.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.central import (
    BillingCycle,
    ProvisioningState,
    SocietyStatus,
    SubscriptionStatus,
)

Pincode = Annotated[str, Field(pattern=r"^[1-9][0-9]{5}$", description="6-digit Indian PIN")]
IndianMobile = Annotated[
    str, Field(pattern=r"^[6-9][0-9]{9}$", description="10-digit Indian mobile, no +91")
]


# --------------------------------------------------------------------------- #
# Societies
# --------------------------------------------------------------------------- #


class SocietyAdminCreate(BaseModel):
    email: EmailStr
    display_name: Annotated[str, Field(min_length=2, max_length=150)]
    phone: IndianMobile | None = None
    firebase_uid: Annotated[str | None, Field(max_length=128)] = None
    """Optional. When absent the account is created in a ``pending:`` state and
    bound to a Firebase UID on the admin's first sign-in."""


class SocietyCreate(BaseModel):
    name: Annotated[str, Field(min_length=3, max_length=200)]
    slug: Annotated[str | None, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$")] = None
    registration_number: Annotated[str | None, Field(max_length=100)] = None

    address_line1: Annotated[str | None, Field(max_length=255)] = None
    address_line2: Annotated[str | None, Field(max_length=255)] = None
    city: Annotated[str, Field(min_length=2, max_length=100)]
    state: Annotated[str, Field(min_length=2, max_length=100)]
    pincode: Pincode

    contact_email: EmailStr
    contact_phone: IndianMobile
    timezone: Annotated[str, Field(max_length=64)] = "Asia/Kolkata"

    admin: SocietyAdminCreate
    plan_id: uuid.UUID | None = None
    """Defaults to the first active plan by sort order."""

    @field_validator("name", "city", "state")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class SocietyUpdate(BaseModel):
    name: Annotated[str | None, Field(min_length=3, max_length=200)] = None
    registration_number: Annotated[str | None, Field(max_length=100)] = None
    address_line1: Annotated[str | None, Field(max_length=255)] = None
    address_line2: Annotated[str | None, Field(max_length=255)] = None
    city: Annotated[str | None, Field(min_length=2, max_length=100)] = None
    state: Annotated[str | None, Field(min_length=2, max_length=100)] = None
    pincode: Pincode | None = None
    contact_email: EmailStr | None = None
    contact_phone: IndianMobile | None = None
    timezone: Annotated[str | None, Field(max_length=64)] = None


class SocietyLockRequest(BaseModel):
    reason: Annotated[str, Field(min_length=3, max_length=500)]


class RegistryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    database_name: str
    sequence_number: int
    provisioning_state: ProvisioningState
    provisioning_step: str | None = None
    provisioning_error: str | None = None
    alembic_revision: str | None = None
    migrated_at: datetime | None = None


class SubscriptionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_name: str | None = None
    status: SubscriptionStatus
    start_date: date
    end_date: date
    days_remaining: int | None = None


class SocietyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    registration_number: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str
    state: str
    pincode: str
    contact_email: str
    contact_phone: str
    timezone: str
    status: SocietyStatus
    total_flats: int
    locked_at: datetime | None = None
    locked_reason: str | None = None
    created_at: datetime


class SocietyDetail(SocietyRead):
    registry: RegistryRead | None = None
    subscription: SubscriptionSummary | None = None
    admin_count: int = 0
    user_count: int = 0


class SocietyProvisionResult(BaseModel):
    society: SocietyRead
    database_name: str
    alembic_revision: str
    admin_email: str
    admin_firebase_uid: str
    subscription: SubscriptionSummary
    resumed: bool = False


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #


class PlanCreate(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=100)]
    code: Annotated[str, Field(pattern=r"^[A-Z0-9_]{2,50}$")]
    description: str | None = None
    price: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
    billing_cycle: BillingCycle
    max_flats: Annotated[int | None, Field(gt=0)] = None
    max_users: Annotated[int | None, Field(gt=0)] = None
    features: dict[str, Any] = Field(default_factory=dict)
    trial_days: Annotated[int, Field(ge=0, le=365)] = 14
    sort_order: int = 0


class PlanUpdate(BaseModel):
    name: Annotated[str | None, Field(min_length=2, max_length=100)] = None
    description: str | None = None
    price: Annotated[Decimal | None, Field(ge=0, max_digits=12, decimal_places=2)] = None
    max_flats: Annotated[int | None, Field(gt=0)] = None
    max_users: Annotated[int | None, Field(gt=0)] = None
    features: dict[str, Any] | None = None
    trial_days: Annotated[int | None, Field(ge=0, le=365)] = None
    is_active: bool | None = None
    sort_order: int | None = None


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    description: str | None = None
    price: Decimal
    billing_cycle: BillingCycle
    max_flats: int | None = None
    max_users: int | None = None
    features: dict[str, Any]
    trial_days: int
    is_active: bool
    sort_order: int


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #


class SubscriptionAssign(BaseModel):
    society_id: uuid.UUID
    plan_id: uuid.UUID
    start_date: date | None = None
    end_date: date | None = None
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    notes: Annotated[str | None, Field(max_length=1000)] = None


class SubscriptionExtend(BaseModel):
    days: Annotated[int | None, Field(gt=0, le=3650)] = None
    new_end_date: date | None = None
    notes: Annotated[str | None, Field(max_length=1000)] = None


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    society_id: uuid.UUID
    plan_id: uuid.UUID
    plan_name: str | None = None
    status: SubscriptionStatus
    start_date: date
    end_date: date
    is_current: bool
    price_snapshot: Decimal
    max_flats_snapshot: int | None = None
    max_users_snapshot: int | None = None
    notes: str | None = None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Dashboard & audit
# --------------------------------------------------------------------------- #


class PlatformDashboard(BaseModel):
    total_societies: int
    active_societies: int
    locked_societies: int
    provisioning_societies: int
    failed_societies: int
    active_subscriptions: int
    expiring_soon: int
    total_users: int
    total_plans: int


class PlatformUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    phone: str | None = None
    is_super_admin: bool
    society_id: uuid.UUID | None = None
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: str | None = None
    action: str
    actor_email: str | None = None
    society_id: uuid.UUID | None = None
    target_type: str | None = None
    target_id: str | None = None
    changes: dict[str, Any] | None = None
    status: str
    created_at: datetime
