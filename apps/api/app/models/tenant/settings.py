"""Per-society configuration and theme.

Both are singleton tables (``CHECK (id = 1)``). A society has exactly one
settings row and exactly one theme row; making that a database constraint means
no code path has to defend against a second one.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import TenantBase, TimestampMixin
from app.models.tenant.enums import (
    BillingFrequency,
    ThemeMode,
    billing_frequency_enum,
    theme_mode_enum,
)

HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"
"""Last line of defence against a value injected into a CSS custom property."""


class SocietySettings(TimestampMixin, TenantBase):
    __tablename__ = "society_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)

    society_name: Mapped[str] = mapped_column(String(200), nullable=False)
    registration_number: Mapped[str | None] = mapped_column(String(100))

    address_line1: Mapped[str | None] = mapped_column(String(255))
    address_line2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    pincode: Mapped[str | None] = mapped_column(String(6))

    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(10))

    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Asia/Kolkata"
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, server_default="en-IN")

    financial_year_start_month: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="4"
    )
    """April — the Indian financial year. Drives H1/H2 and FY period keys."""

    default_billing_cycle: Mapped[BillingFrequency] = mapped_column(
        billing_frequency_enum, nullable=False, server_default=BillingFrequency.MONTHLY.value
    )
    bill_due_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="15"
    )
    late_fee_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0"
    )
    late_fee_grace_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint(
            "financial_year_start_month BETWEEN 1 AND 12", name="fy_month_range"
        ),
        CheckConstraint("bill_due_days BETWEEN 0 AND 90", name="due_days_range"),
        CheckConstraint("late_fee_percent >= 0", name="late_fee_non_negative"),
        CheckConstraint(r"pincode IS NULL OR pincode ~ '^[1-9][0-9]{5}$'", name="pincode_format"),
    )


class ThemeSettings(TimestampMixin, TenantBase):
    """The society's appearance.

    Only four colours, a mode and a radius are stored. Every other token
    (hover, active, subtle, foreground) is derived on the client in OKLCH —
    see docs/architecture/theme-system.md section 3.
    """

    __tablename__ = "theme_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)

    theme_mode: Mapped[ThemeMode] = mapped_column(
        theme_mode_enum, nullable=False, server_default=ThemeMode.SYSTEM.value
    )
    primary_color: Mapped[str] = mapped_column(
        String(7), nullable=False, server_default="#4F46E5"
    )
    secondary_color: Mapped[str] = mapped_column(
        String(7), nullable=False, server_default="#0EA5E9"
    )
    accent_color: Mapped[str] = mapped_column(
        String(7), nullable=False, server_default="#8B5CF6"
    )
    sidebar_color: Mapped[str] = mapped_column(
        String(7), nullable=False, server_default="#101828"
    )
    border_radius: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="14"
    )
    logo_url: Mapped[str | None] = mapped_column(String(500))

    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint(f"primary_color ~ '{HEX_COLOR}'", name="primary_hex"),
        CheckConstraint(f"secondary_color ~ '{HEX_COLOR}'", name="secondary_hex"),
        CheckConstraint(f"accent_color ~ '{HEX_COLOR}'", name="accent_hex"),
        CheckConstraint(f"sidebar_color ~ '{HEX_COLOR}'", name="sidebar_hex"),
        CheckConstraint("border_radius BETWEEN 0 AND 32", name="radius_range"),
    )


DEFAULT_THEME: dict[str, object] = {
    "theme_mode": ThemeMode.SYSTEM,
    "primary_color": "#4F46E5",
    "secondary_color": "#0EA5E9",
    "accent_color": "#8B5CF6",
    "sidebar_color": "#101828",
    "border_radius": 14,
    "logo_url": None,
}
