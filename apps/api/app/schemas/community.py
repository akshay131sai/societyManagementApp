"""Notice and amenity schemas.

The booking payload is deliberately *slot*-shaped rather than
timestamp-shaped: a resident picks "10:00, two slots", and the server derives
the window from the amenity's own grid. Accepting arbitrary start and end
times would let a client book 10:07–11:23 and quietly break every availability
view that assumes a grid.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.tenant import (
    AudienceScope,
    BookingStatus,
    NoticeCategory,
    Priority,
)

Money = Annotated[Decimal, Field(ge=0, le=99_999_999, max_digits=14, decimal_places=2)]


def _strip(value: str) -> str:
    return " ".join(value.strip().split())


# --------------------------------------------------------------------------- #
# Notices
# --------------------------------------------------------------------------- #


class NoticeAttachment(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    url: Annotated[str, Field(min_length=1, max_length=1000)]
    size_bytes: Annotated[int | None, Field(ge=0)] = None


class NoticeCreate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    body: Annotated[str, Field(min_length=1, max_length=20_000)]
    category: NoticeCategory = NoticeCategory.GENERAL
    priority: Priority = Priority.MEDIUM
    audience: AudienceScope = AudienceScope.ALL
    building_id: uuid.UUID | None = None
    block_id: uuid.UUID | None = None
    is_pinned: bool = False
    publish_now: bool = True
    publish_at: datetime | None = None
    expires_at: datetime | None = None
    attachments: Annotated[list[NoticeAttachment], Field(max_length=10)] = []

    @field_validator("title")
    @classmethod
    def _clean_title(cls, v: str) -> str:
        return _strip(v)

    @model_validator(mode="after")
    def _audience_has_a_target(self) -> NoticeCreate:
        # The database enforces this too. Doing it here turns a 500-shaped
        # constraint violation into a field-level message on the right input.
        if self.audience is AudienceScope.BUILDING and self.building_id is None:
            raise ValueError("Choose which building this notice is for.")
        if self.audience is AudienceScope.BLOCK and self.block_id is None:
            raise ValueError("Choose which block this notice is for.")
        if (
            self.expires_at is not None
            and self.publish_at is not None
            and self.expires_at <= self.publish_at
        ):
            raise ValueError("A notice cannot expire before it is published.")
        return self


class NoticeUpdate(BaseModel):
    title: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    body: Annotated[str | None, Field(min_length=1, max_length=20_000)] = None
    category: NoticeCategory | None = None
    priority: Priority | None = None
    is_pinned: bool | None = None
    expires_at: datetime | None = None
    attachments: Annotated[list[NoticeAttachment] | None, Field(max_length=10)] = None


class NoticeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    body: str
    category: NoticeCategory
    priority: Priority
    audience: AudienceScope
    building_id: uuid.UUID | None = None
    building_name: str | None = None
    block_id: uuid.UUID | None = None
    block_name: str | None = None
    is_pinned: bool
    is_published: bool
    publish_at: datetime | None = None
    expires_at: datetime | None = None
    is_expired: bool = False
    attachments: list[NoticeAttachment] = []
    author_id: uuid.UUID | None = None
    author_name: str
    is_read: bool = False
    """For the calling principal. Drives the unread dot in the notice list."""

    read_count: int = 0
    """Only populated for a principal who can manage notices — a resident has
    no business knowing how many neighbours opened the AGM notice."""

    created_at: datetime


class NoticeSummary(BaseModel):
    total: int
    published: int
    scheduled: int
    expired: int
    unread: int


# --------------------------------------------------------------------------- #
# Amenities
# --------------------------------------------------------------------------- #


class AmenityCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    opens_at: time
    closes_at: time
    description: Annotated[str | None, Field(max_length=5000)] = None
    location: Annotated[str | None, Field(max_length=200)] = None
    building_id: uuid.UUID | None = None
    capacity: Annotated[int | None, Field(ge=1, le=32_000)] = None
    slot_minutes: Annotated[int, Field(ge=15, le=1440)] = 60
    booking_charge: Money = Decimal("0")
    max_advance_days: Annotated[int, Field(ge=1, le=365)] = 30
    max_slots_per_booking: Annotated[int, Field(ge=1, le=48)] = 2
    max_active_per_flat: Annotated[int, Field(ge=1, le=50)] = 3
    requires_approval: bool = False
    rules: Annotated[str | None, Field(max_length=10_000)] = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        return _strip(v)

    @model_validator(mode="after")
    def _hours_hold_a_whole_slot(self) -> AmenityCreate:
        if self.closes_at <= self.opens_at:
            raise ValueError("Closing time must be after opening time.")
        span = (
            self.closes_at.hour * 60
            + self.closes_at.minute
            - self.opens_at.hour * 60
            - self.opens_at.minute
        )
        if span < self.slot_minutes:
            raise ValueError(
                f"The opening hours are {span} minutes, which is shorter than one "
                f"{self.slot_minutes}-minute slot."
            )
        return self


class AmenityUpdate(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=120)] = None
    description: Annotated[str | None, Field(max_length=5000)] = None
    location: Annotated[str | None, Field(max_length=200)] = None
    capacity: Annotated[int | None, Field(ge=1, le=32_000)] = None
    opens_at: time | None = None
    closes_at: time | None = None
    slot_minutes: Annotated[int | None, Field(ge=15, le=1440)] = None
    booking_charge: Money | None = None
    max_advance_days: Annotated[int | None, Field(ge=1, le=365)] = None
    max_slots_per_booking: Annotated[int | None, Field(ge=1, le=48)] = None
    max_active_per_flat: Annotated[int | None, Field(ge=1, le=50)] = None
    requires_approval: bool | None = None
    rules: Annotated[str | None, Field(max_length=10_000)] = None
    is_active: bool | None = None


class AmenityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    location: str | None = None
    building_id: uuid.UUID | None = None
    building_name: str | None = None
    capacity: int | None = None
    opens_at: time
    closes_at: time
    slot_minutes: int
    booking_charge: Decimal
    max_advance_days: int
    max_slots_per_booking: int
    max_active_per_flat: int
    requires_approval: bool
    rules: str | None = None
    is_active: bool
    upcoming_bookings: int = 0
    created_at: datetime


class SlotRead(BaseModel):
    """One cell of a day's grid."""

    starts_at: datetime
    ends_at: datetime
    label: str
    available: bool
    booked_by_flat: str | None = None
    """Shown only to a principal who can manage the amenity. A resident sees
    "Booked" and no more — who is having a party is not public information."""

    is_own: bool = False
    booking_id: uuid.UUID | None = None


class AvailabilityRead(BaseModel):
    amenity_id: uuid.UUID
    amenity_name: str
    booking_date: date
    slot_minutes: int
    booking_charge: Decimal
    slots: list[SlotRead]


class BookingCreate(BaseModel):
    """Grid coordinates, not free-form times.

    ``starts_at`` must land on the amenity's slot boundary; the service checks
    it and refuses with the nearest legal time rather than silently rounding.
    """

    amenity_id: uuid.UUID
    starts_at: datetime
    slots: Annotated[int, Field(ge=1, le=48)] = 1
    flat_id: uuid.UUID | None = None
    guests: Annotated[int, Field(ge=0, le=500)] = 0
    purpose: Annotated[str | None, Field(max_length=300)] = None


class BookingDecision(BaseModel):
    approved: bool
    reason: Annotated[str | None, Field(max_length=300)] = None

    @model_validator(mode="after")
    def _rejection_needs_a_reason(self) -> BookingDecision:
        if not self.approved and not (self.reason and self.reason.strip()):
            raise ValueError("Say why the booking was rejected.")
        return self


class BookingCancel(BaseModel):
    reason: Annotated[str | None, Field(max_length=300)] = None


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amenity_id: uuid.UUID
    amenity_name: str | None = None
    flat_id: uuid.UUID
    flat_number: str | None = None
    booked_by: uuid.UUID | None = None
    booked_by_name: str
    booking_date: date
    starts_at: datetime
    ends_at: datetime
    slots: int
    guests: int
    purpose: str | None = None
    status: BookingStatus
    charge: Decimal
    approved_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    can_cancel: bool = False
    created_at: datetime


class AmenitySummary(BaseModel):
    amenities: int
    bookings_today: int
    upcoming: int
    pending_approval: int
    revenue_this_month: Decimal
