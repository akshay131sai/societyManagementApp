"""Central database enum types.

Native PostgreSQL ``ENUM``s rather than ``TEXT`` + ``CHECK``: the database
validates them, they appear in the catalogue for tooling, and an invalid value
cannot be written by a migration or by hand in ``psql``.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class SocietyStatus(StrEnum):
    PROVISIONING = "PROVISIONING"
    PROVISIONING_FAILED = "PROVISIONING_FAILED"
    """Our fault, needs an engineer — deliberately distinct from SUSPENDED."""
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class SubscriptionStatus(StrEnum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUSPENDED = "SUSPENDED"


class BillingCycle(StrEnum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    HALF_YEARLY = "HALF_YEARLY"
    YEARLY = "YEARLY"


class ProvisioningState(StrEnum):
    PENDING = "PENDING"
    DATABASE_CREATED = "DATABASE_CREATED"
    MIGRATED = "MIGRATED"
    SEEDED = "SEEDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Reusable column types. ``create_type=False`` on repeated use is handled by
# Alembic; ``native_enum=True`` is the default and is what we want.
society_status_enum = SAEnum(
    SocietyStatus, name="society_status", values_callable=lambda e: [m.value for m in e]
)
subscription_status_enum = SAEnum(
    SubscriptionStatus,
    name="subscription_status",
    values_callable=lambda e: [m.value for m in e],
)
billing_cycle_enum = SAEnum(
    BillingCycle, name="billing_cycle", values_callable=lambda e: [m.value for m in e]
)
provisioning_state_enum = SAEnum(
    ProvisioningState,
    name="provisioning_state",
    values_callable=lambda e: [m.value for m in e],
)

ACCESSIBLE_SOCIETY_STATUSES = frozenset({SocietyStatus.ACTIVE})
"""Statuses that permit ordinary tenant access."""

VALID_SUBSCRIPTION_STATUSES = frozenset(
    {SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE}
)
"""Statuses that grant entitlement, subject to the end date."""
