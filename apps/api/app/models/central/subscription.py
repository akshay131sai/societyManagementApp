"""Subscription plans and society subscriptions."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import CentralBase, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.central.enums import (
    BillingCycle,
    SubscriptionStatus,
    billing_cycle_enum,
    subscription_status_enum,
)

if TYPE_CHECKING:
    from app.models.central.society import Society


class SubscriptionPlan(UUIDPrimaryKeyMixin, TimestampMixin, CentralBase):
    """A sellable plan. Deactivated, never deleted — subscriptions cite it."""

    __tablename__ = "subscription_plans"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    billing_cycle: Mapped[BillingCycle] = mapped_column(billing_cycle_enum, nullable=False)

    max_flats: Mapped[int | None] = mapped_column(Integer)
    """NULL means unlimited."""
    max_users: Mapped[int | None] = mapped_column(Integer)

    features: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    trial_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="14")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("trial_days >= 0", name="trial_days_non_negative"),
        CheckConstraint("max_flats IS NULL OR max_flats > 0", name="max_flats_positive"),
        CheckConstraint("max_users IS NULL OR max_users > 0", name="max_users_positive"),
    )

    def __repr__(self) -> str:
        return f"<SubscriptionPlan {self.code} price={self.price}>"


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, CentralBase):
    __tablename__ = "subscriptions"

    society_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("societies.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        subscription_status_enum, nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    """Exactly one per society — see ``ux_subscriptions_current``.

    Renewal appends a new row and flips this, so history is preserved.
    """

    price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    max_flats_snapshot: Mapped[int | None] = mapped_column(Integer)
    max_users_snapshot: Mapped[int | None] = mapped_column(Integer)
    """Limits are snapshotted so raising a plan's cap does not retroactively
    change what an existing subscriber was sold."""

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL")
    )

    society: Mapped[Society] = relationship(back_populates="subscriptions", lazy="noload")
    plan: Mapped[SubscriptionPlan] = relationship(lazy="selectin")

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="date_order"),
        Index(
            "ux_subscriptions_current",
            "society_id",
            unique=True,
            postgresql_where="is_current",
        ),
        Index(
            "ix_subscriptions_expiry",
            "end_date",
            postgresql_where="is_current AND status IN ('TRIAL', 'ACTIVE')",
        ),
    )

    def is_valid_on(self, on: date) -> bool:
        """Entitlement check: right status *and* not past the end date."""
        return (
            self.status in (SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE)
            and self.start_date <= on <= self.end_date
        )

    def __repr__(self) -> str:
        return f"<Subscription society={self.society_id} {self.status} -> {self.end_date}>"
