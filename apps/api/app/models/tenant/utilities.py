"""Water and electricity readings.

``consumption`` is a **generated column**, so it can never disagree with the
readings it derives from — not via a repository that forgets, not via a
correction applied to only one of the two numbers.

The monotonic ``CHECK`` catches a transposed meter entry at write time rather
than as a negative charge on a resident's bill.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import TenantBase, TimestampMixin, UUIDPrimaryKeyMixin


class _ReadingMixin:
    reading_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_key: Mapped[str | None] = mapped_column(String(20))
    """Which billing period this reading belongs to. Set by the reader UI so a
    late-entered reading still lands in the right bill."""

    previous_reading: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    current_reading: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)

    meter_number: Mapped[str | None] = mapped_column(String(40))
    remarks: Mapped[str | None] = mapped_column(Text)


class WaterReading(_ReadingMixin, UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    __tablename__ = "water_readings"

    flat_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="CASCADE"), nullable=False
    )
    consumption: Mapped[Decimal] = mapped_column(
        Numeric(14, 3),
        Computed("current_reading - COALESCE(previous_reading, 0)", persisted=True),
    )
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    flat: Mapped["object"] = relationship("Flat", lazy="selectin")

    __table_args__ = (
        # Named per table: a unique constraint is backed by an index, and index
        # names live in the schema namespace, not the table's.
        UniqueConstraint("flat_id", "reading_date", name="water_flat_date"),
        CheckConstraint("current_reading >= 0", name="reading_non_negative"),
        CheckConstraint(
            "previous_reading IS NULL OR current_reading >= previous_reading",
            name="monotonic",
        ),
        Index("ix_water_flat_date", "flat_id", "reading_date"),
        Index("ix_water_period", "period_key"),
    )

    def __repr__(self) -> str:
        return f"<WaterReading {self.reading_date} {self.consumption}>"


class ElectricityReading(_ReadingMixin, UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    __tablename__ = "electricity_readings"

    flat_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="CASCADE"), nullable=False
    )
    consumption: Mapped[Decimal] = mapped_column(
        Numeric(14, 3),
        Computed("current_reading - COALESCE(previous_reading, 0)", persisted=True),
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    """Set when the society is billed by the utility and passes the amount
    through rather than applying its own tariff."""

    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    flat: Mapped["object"] = relationship("Flat", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("flat_id", "reading_date", name="electricity_flat_date"),
        CheckConstraint("current_reading >= 0", name="reading_non_negative"),
        CheckConstraint(
            "previous_reading IS NULL OR current_reading >= previous_reading",
            name="monotonic",
        ),
        CheckConstraint("amount IS NULL OR amount >= 0", name="amount_non_negative"),
        Index("ix_elec_flat_date", "flat_id", "reading_date"),
        Index("ix_elec_period", "period_key"),
    )

    def __repr__(self) -> str:
        return f"<ElectricityReading {self.reading_date} {self.consumption}>"
