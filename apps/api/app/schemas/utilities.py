"""Utility reading, asset and dashboard schemas.

``consumption`` is never accepted on input — it is a generated column. Sending
it would imply the client can disagree with the meter, which it cannot.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.tenant import PetType, SlotType, VehicleType

Reading = Annotated[Decimal, Field(ge=0, le=99_999_999, max_digits=14, decimal_places=3)]
Money = Annotated[Decimal, Field(ge=0, le=99_999_999, max_digits=14, decimal_places=2)]

# A period the billing engine can parse: 2026-08, 2026-Q2, 2026-H1, FY2026-27.
PERIOD_KEY = r"^(\d{4}-(0[1-9]|1[0-2])|\d{4}-Q[1-4]|\d{4}-H[12]|FY\d{4}-\d{2})$"


# --------------------------------------------------------------------------- #
# Readings
# --------------------------------------------------------------------------- #


class _ReadingBase(BaseModel):
    flat_id: uuid.UUID
    reading_date: date
    period_key: Annotated[str | None, Field(pattern=PERIOD_KEY)] = None
    previous_reading: Reading | None = None
    current_reading: Reading
    meter_number: Annotated[str | None, Field(max_length=40)] = None
    remarks: Annotated[str | None, Field(max_length=2000)] = None

    @model_validator(mode="after")
    def _not_in_the_future(self) -> _ReadingBase:
        # A meter cannot have been read tomorrow. Catching it here gives a clear
        # message; the database CHECK stays as the guarantee.
        if self.reading_date > date.today():
            raise ValueError("A reading cannot be dated in the future.")
        if (
            self.previous_reading is not None
            and self.current_reading < self.previous_reading
        ):
            raise ValueError(
                "The current reading is lower than the previous one. If the meter "
                "was replaced, record the change in remarks and start a new series."
            )
        return self


class WaterReadingCreate(_ReadingBase):
    pass


class ElectricityReadingCreate(_ReadingBase):
    amount: Money | None = None


class ReadingUpdate(BaseModel):
    """Corrections only. ``flat_id`` and ``reading_date`` are the identity of a
    reading and cannot be edited — delete and re-enter instead."""

    previous_reading: Reading | None = None
    current_reading: Reading | None = None
    period_key: Annotated[str | None, Field(pattern=PERIOD_KEY)] = None
    meter_number: Annotated[str | None, Field(max_length=40)] = None
    remarks: Annotated[str | None, Field(max_length=2000)] = None
    amount: Money | None = None


class ReadingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    flat_id: uuid.UUID
    flat_number: str | None = None
    reading_date: date
    period_key: str | None = None
    previous_reading: Decimal | None = None
    current_reading: Decimal
    consumption: Decimal
    meter_number: str | None = None
    remarks: str | None = None
    amount: Decimal | None = None
    created_at: datetime


class BulkReadingRow(BaseModel):
    flat_id: uuid.UUID
    current_reading: Reading
    previous_reading: Reading | None = None
    meter_number: Annotated[str | None, Field(max_length=40)] = None
    amount: Money | None = None


class BulkReadingCreate(BaseModel):
    """One reading date, many flats — how a meter reader actually works."""

    reading_date: date
    period_key: Annotated[str | None, Field(pattern=PERIOD_KEY)] = None
    rows: Annotated[list[BulkReadingRow], Field(min_length=1, max_length=1000)]
    skip_existing: bool = True
    """Re-running a partially entered round should top it up, not fail."""

    @field_validator("rows")
    @classmethod
    def _unique_flats(cls, rows: list[BulkReadingRow]) -> list[BulkReadingRow]:
        seen = {r.flat_id for r in rows}
        if len(seen) != len(rows):
            raise ValueError("A flat appears more than once in this batch.")
        return rows

    @model_validator(mode="after")
    def _not_in_the_future(self) -> BulkReadingCreate:
        if self.reading_date > date.today():
            raise ValueError("A reading cannot be dated in the future.")
        return self


class BulkReadingResult(BaseModel):
    created: int
    skipped: int
    skipped_flat_ids: list[uuid.UUID] = []


class PendingFlat(BaseModel):
    """A flat awaiting entry, with its opening value prefilled."""

    flat_id: uuid.UUID
    flat_number: str
    building_name: str | None = None
    previous_reading: Decimal | None = None
    last_reading_date: date | None = None


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #


class ConsumptionPoint(BaseModel):
    reading_date: date
    label: str
    consumption: Decimal
    current_reading: Decimal | None = None
    amount: Decimal | None = None


class ConsumptionStats(BaseModel):
    readings: int
    average: Decimal
    highest: Decimal
    lowest: Decimal
    total: Decimal


class ConsumptionTrend(BaseModel):
    """What a resident sees on their utility card: the series, the headline
    numbers, and whether they are using more than last time."""

    unit: Literal["kL", "kWh"]
    points: list[ConsumptionPoint]
    stats: ConsumptionStats
    latest: Decimal | None = None
    previous: Decimal | None = None
    change_pct: Decimal | None = None


class SocietyConsumptionPoint(BaseModel):
    reading_date: date
    label: str
    total: Decimal


# --------------------------------------------------------------------------- #
# Parking
# --------------------------------------------------------------------------- #


class ParkingSlotCreate(BaseModel):
    slot_number: Annotated[str, Field(min_length=1, max_length=20)]
    building_id: uuid.UUID | None = None
    level: Annotated[str | None, Field(max_length=20)] = None
    slot_type: SlotType = SlotType.FOUR_WHEELER
    monthly_charge: Money = Decimal("0")
    flat_id: uuid.UUID | None = None
    notes: Annotated[str | None, Field(max_length=1000)] = None

    @field_validator("slot_number")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return v.strip().upper()


class ParkingSlotUpdate(BaseModel):
    level: Annotated[str | None, Field(max_length=20)] = None
    slot_type: SlotType | None = None
    monthly_charge: Money | None = None
    notes: Annotated[str | None, Field(max_length=1000)] = None
    is_active: bool | None = None


class ParkingAllotment(BaseModel):
    flat_id: uuid.UUID | None = None
    """``null`` releases the slot back to the pool."""


class ParkingSlotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slot_number: str
    building_id: uuid.UUID | None = None
    level: str | None = None
    slot_type: SlotType
    monthly_charge: Decimal
    flat_id: uuid.UUID | None = None
    flat_number: str | None = None
    notes: str | None = None
    is_active: bool
    created_at: datetime


class ParkingSummary(BaseModel):
    total: int
    allotted: int
    available: int


# --------------------------------------------------------------------------- #
# Vehicles
# --------------------------------------------------------------------------- #

# Indian formats, old and BH-series, plus a permissive fallback for imports.
REGISTRATION = r"^[A-Z0-9][A-Z0-9\- ]{3,19}$"


class VehicleCreate(BaseModel):
    flat_id: uuid.UUID
    registration_number: Annotated[str, Field(pattern=REGISTRATION)]
    vehicle_type: VehicleType
    make: Annotated[str | None, Field(max_length=40)] = None
    model: Annotated[str | None, Field(max_length=40)] = None
    color: Annotated[str | None, Field(max_length=30)] = None
    parking_slot_id: uuid.UUID | None = None

    @field_validator("registration_number", mode="before")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return " ".join(str(v).strip().upper().split())


class VehicleUpdate(BaseModel):
    vehicle_type: VehicleType | None = None
    make: Annotated[str | None, Field(max_length=40)] = None
    model: Annotated[str | None, Field(max_length=40)] = None
    color: Annotated[str | None, Field(max_length=30)] = None
    parking_slot_id: uuid.UUID | None = None
    is_active: bool | None = None


class VehicleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    flat_id: uuid.UUID
    flat_number: str | None = None
    registration_number: str
    vehicle_type: VehicleType
    make: str | None = None
    model: str | None = None
    color: str | None = None
    parking_slot_id: uuid.UUID | None = None
    parking_slot_number: str | None = None
    is_active: bool
    created_at: datetime


# --------------------------------------------------------------------------- #
# Pets
# --------------------------------------------------------------------------- #


class PetCreate(BaseModel):
    flat_id: uuid.UUID
    name: Annotated[str, Field(min_length=1, max_length=60)]
    pet_type: PetType
    breed: Annotated[str | None, Field(max_length=60)] = None
    registration_number: Annotated[str | None, Field(max_length=40)] = None
    vaccination_expiry: date | None = None
    monthly_fee: Money = Decimal("0")

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class PetUpdate(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=60)] = None
    pet_type: PetType | None = None
    breed: Annotated[str | None, Field(max_length=60)] = None
    registration_number: Annotated[str | None, Field(max_length=40)] = None
    vaccination_expiry: date | None = None
    monthly_fee: Money | None = None
    is_active: bool | None = None


class PetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    flat_id: uuid.UUID
    flat_number: str | None = None
    name: str
    pet_type: PetType
    breed: str | None = None
    registration_number: str | None = None
    vaccination_expiry: date | None = None
    vaccination_due: bool = False
    monthly_fee: Decimal
    is_active: bool
    created_at: datetime


# --------------------------------------------------------------------------- #
# Resident dashboard
# --------------------------------------------------------------------------- #


class DashboardFlat(BaseModel):
    id: uuid.UUID
    flat_number: str
    building_name: str | None = None
    block_name: str | None = None
    floor_name: str | None = None
    area_sqft: Decimal


class DashboardBill(BaseModel):
    id: uuid.UUID
    bill_number: str
    period_label: str
    total_amount: Decimal
    amount_paid: Decimal
    balance: Decimal
    due_date: date
    status: str
    is_overdue: bool
    days_until_due: int


class DashboardPayment(BaseModel):
    id: uuid.UUID
    amount: Decimal
    paid_on: date
    method: str
    reference: str | None = None
    bill_number: str | None = None


class DashboardCharge(BaseModel):
    """One slice of the "where your money goes" chart."""

    label: str
    amount: Decimal


class ResidentDashboard(BaseModel):
    flats: list[DashboardFlat]
    outstanding: Decimal
    overdue_count: int
    next_due: DashboardBill | None = None
    recent_bills: list[DashboardBill]
    recent_payments: list[DashboardPayment]
    charge_breakdown: list[DashboardCharge]
    water: ConsumptionTrend | None = None
    electricity: ConsumptionTrend | None = None
    vehicles: int = 0
    parking_slots: int = 0
    pets: int = 0
    paid_this_year: Decimal = Decimal("0")
