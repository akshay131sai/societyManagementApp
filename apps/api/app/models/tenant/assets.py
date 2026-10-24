"""Parking slots, vehicles and pets.

All three feed the billing engine — `parking_charge_total`, `vehicle_count`,
`pet_fee_total` are formula fields — so their charges live here rather than
being re-entered per bill.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import TenantBase, TimestampMixin, UUIDPrimaryKeyMixin


def _pg_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class SlotType(StrEnum):
    TWO_WHEELER = "TWO_WHEELER"
    FOUR_WHEELER = "FOUR_WHEELER"
    VISITOR = "VISITOR"
    HANDICAPPED = "HANDICAPPED"


class VehicleType(StrEnum):
    TWO_WHEELER = "TWO_WHEELER"
    FOUR_WHEELER = "FOUR_WHEELER"
    BICYCLE = "BICYCLE"
    OTHER = "OTHER"


class PetType(StrEnum):
    DOG = "DOG"
    CAT = "CAT"
    BIRD = "BIRD"
    OTHER = "OTHER"


slot_type_enum = _pg_enum(SlotType, "slot_type")
vehicle_type_enum = _pg_enum(VehicleType, "vehicle_type")
pet_type_enum = _pg_enum(PetType, "pet_type")


class ParkingSlot(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A physical parking space. A shared society resource, so allotment is an
    admin action even though the vehicle in it belongs to a resident."""

    __tablename__ = "parking_slots"

    slot_number: Mapped[str] = mapped_column(String(20), nullable=False)
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buildings.id", ondelete="SET NULL")
    )
    level: Mapped[str | None] = mapped_column(String(20))
    slot_type: Mapped[SlotType] = mapped_column(
        slot_type_enum, nullable=False, server_default=SlotType.FOUR_WHEELER.value
    )
    monthly_charge: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )

    flat_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="SET NULL")
    )
    """NULL means unallotted. Visitor slots stay NULL permanently."""

    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    flat: Mapped["object"] = relationship("Flat", lazy="selectin")

    __table_args__ = (
        CheckConstraint("monthly_charge >= 0", name="charge_non_negative"),
        Index("ux_parking_slot_number", func.upper(slot_number), unique=True),
        Index("ix_parking_flat", "flat_id", postgresql_where="flat_id IS NOT NULL"),
        Index("ix_parking_available", "slot_type", postgresql_where="flat_id IS NULL AND is_active"),
    )

    def __repr__(self) -> str:
        return f"<ParkingSlot {self.slot_number}>"


class Vehicle(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    __tablename__ = "vehicles"

    flat_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="CASCADE"), nullable=False
    )
    registration_number: Mapped[str] = mapped_column(String(20), nullable=False)
    vehicle_type: Mapped[VehicleType] = mapped_column(vehicle_type_enum, nullable=False)

    make: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(30))

    parking_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parking_slots.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    flat: Mapped["object"] = relationship("Flat", lazy="selectin")
    parking_slot: Mapped[ParkingSlot | None] = relationship(lazy="selectin")

    __table_args__ = (
        # Registration numbers are society-wide unique among active vehicles:
        # the gate needs to resolve a plate to exactly one flat.
        Index(
            "ux_vehicle_registration",
            func.upper(registration_number),
            unique=True,
            postgresql_where="is_active",
        ),
        Index("ix_vehicles_flat", "flat_id", postgresql_where="is_active"),
    )

    def __repr__(self) -> str:
        return f"<Vehicle {self.registration_number}>"


class Pet(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    __tablename__ = "pets"

    flat_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    pet_type: Mapped[PetType] = mapped_column(pet_type_enum, nullable=False)
    breed: Mapped[str | None] = mapped_column(String(60))
    registration_number: Mapped[str | None] = mapped_column(String(40))
    vaccination_expiry: Mapped[date | None] = mapped_column(Date)
    monthly_fee: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    flat: Mapped["object"] = relationship("Flat", lazy="selectin")

    __table_args__ = (
        CheckConstraint("monthly_fee >= 0", name="fee_non_negative"),
        Index("ix_pets_flat", "flat_id", postgresql_where="is_active"),
    )

    def __repr__(self) -> str:
        return f"<Pet {self.name}>"
