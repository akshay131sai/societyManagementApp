"""Community: notices and amenity bookings.

Two invariants here are enforced by PostgreSQL rather than by the service, for
the same reason the billing triggers are:

* **A slot cannot be double-booked.** ``amenity_bookings`` carries a GiST
  exclusion constraint over ``(amenity_id, tsrange)`` restricted to the
  statuses that actually hold a slot. Two residents pressing Book at the same
  instant is not a rare case in a 300-flat society at 9 a.m. on a Sunday, and
  an application-level "check then insert" loses that race every time.

* **A notice is read once per person.** ``notice_reads`` is keyed on
  ``(notice_id, user_id)``, so a double-tap on a slow connection cannot inflate
  the read count that a committee uses to decide whether anyone saw the AGM
  announcement.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import TenantBase, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.tenant.enums import (
    AudienceScope,
    BookingStatus,
    NoticeCategory,
    Priority,
    audience_scope_enum,
    booking_status_enum,
    notice_category_enum,
    priority_enum,
)

BOOKING_HOLDS_SLOT = "status IN ('PENDING', 'CONFIRMED')"
"""The statuses a live booking can be in.

Both the exclusion constraint and the availability query are written against
this one string, so "which bookings block a slot" has exactly one answer.
"""


# --------------------------------------------------------------------------- #
# Notices
# --------------------------------------------------------------------------- #


class Notice(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A society announcement.

    ``publish_at`` and ``expires_at`` make a notice a scheduled object rather
    than something an admin has to remember to post at 9 a.m. and take down a
    week later. The list endpoint filters on them, so an unpublished draft is
    invisible to residents without a second "is_visible" flag to keep in sync.
    """

    __tablename__ = "notices"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[NoticeCategory] = mapped_column(
        notice_category_enum, nullable=False, server_default=NoticeCategory.GENERAL.value
    )
    priority: Mapped[Priority] = mapped_column(
        priority_enum, nullable=False, server_default=Priority.MEDIUM.value
    )

    audience: Mapped[AudienceScope] = mapped_column(
        audience_scope_enum, nullable=False, server_default=AudienceScope.ALL.value
    )
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buildings.id", ondelete="CASCADE")
    )
    block_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("blocks.id", ondelete="CASCADE")
    )

    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    attachments: Mapped[list[dict] | None] = mapped_column(JSONB)
    """``[{"name": "agm-agenda.pdf", "url": "..."}]``. JSONB rather than a
    child table: attachments are never queried across notices, only rendered
    with the one they belong to."""

    author_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    author_name: Mapped[str] = mapped_column(String(150), nullable=False)

    building: Mapped["object"] = relationship("Building", lazy="selectin")
    block: Mapped["object"] = relationship("Block", lazy="selectin")
    reads: Mapped[list[NoticeRead]] = relationship(
        back_populates="notice", lazy="noload", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "expires_at IS NULL OR publish_at IS NULL OR expires_at > publish_at",
            name="window_order",
        ),
        # An audience of BUILDING with no building is a notice addressed to
        # nobody. Catching it here means the fan-out never has to handle it.
        CheckConstraint(
            "(audience <> 'BUILDING' OR building_id IS NOT NULL) AND "
            "(audience <> 'BLOCK' OR block_id IS NOT NULL)",
            name="audience_target_present",
        ),
        Index("ix_notices_published", "publish_at", postgresql_where="is_published"),
        Index("ix_notices_pinned", "is_pinned", "publish_at", postgresql_where="is_published"),
        Index("ix_notices_category", "category", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Notice {self.title}>"


class NoticeRead(UUIDPrimaryKeyMixin, TenantBase):
    """Who has seen a notice.

    No ``TimestampMixin``: this table only ever grows, one narrow row per
    person per notice, and ``read_at`` is the single fact it exists to record.
    """

    __tablename__ = "notice_reads"

    notice_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("notices.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    notice: Mapped[Notice] = relationship(back_populates="reads", lazy="noload")

    __table_args__ = (
        UniqueConstraint("notice_id", "user_id", name="notice_user"),
        Index("ix_notice_reads_user", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<NoticeRead {self.notice_id}>"


# --------------------------------------------------------------------------- #
# Amenities
# --------------------------------------------------------------------------- #


class Amenity(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A bookable shared facility: clubhouse, gym, party lawn, badminton court.

    ``slot_minutes`` turns the opening hours into a grid the booking screen can
    render and the availability query can iterate. A facility booked by the
    whole day sets it to 1440 and gets exactly one slot, with no special case
    anywhere in the code.
    """

    __tablename__ = "amenities"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(200))
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buildings.id", ondelete="SET NULL")
    )

    capacity: Mapped[int | None] = mapped_column(SmallInteger)
    opens_at: Mapped[time] = mapped_column(Time, nullable=False)
    closes_at: Mapped[time] = mapped_column(Time, nullable=False)
    slot_minutes: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="60"
    )

    booking_charge: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    """Per slot. Zero for a facility a society includes in maintenance."""

    max_advance_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="30"
    )
    max_slots_per_booking: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="2"
    )
    max_active_per_flat: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="3"
    )
    """Stops one flat from holding the party lawn every weekend of the season."""

    requires_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    rules: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    building: Mapped["object"] = relationship("Building", lazy="selectin")

    __table_args__ = (
        CheckConstraint("closes_at > opens_at", name="hours_order"),
        CheckConstraint("slot_minutes BETWEEN 15 AND 1440", name="slot_minutes_range"),
        CheckConstraint("booking_charge >= 0", name="charge_non_negative"),
        CheckConstraint("max_advance_days BETWEEN 1 AND 365", name="advance_days_range"),
        CheckConstraint(
            "max_slots_per_booking BETWEEN 1 AND 48", name="slots_per_booking_range"
        ),
        CheckConstraint("max_active_per_flat BETWEEN 1 AND 50", name="active_per_flat_range"),
        CheckConstraint("capacity IS NULL OR capacity > 0", name="capacity_positive"),
        Index("ux_amenities_name", func.lower(name), unique=True),
        Index("ix_amenities_active", "name", postgresql_where="is_active"),
    )

    def __repr__(self) -> str:
        return f"<Amenity {self.name}>"


class AmenityBooking(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """One flat's hold on one facility for one window.

    The window is stored as two timestamps *and* mirrored into a ``tsrange``
    generated column, because PostgreSQL can only exclude overlaps over a range
    type. The generated column means the range cannot disagree with the
    timestamps the rest of the application reads.
    """

    __tablename__ = "amenity_bookings"

    amenity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("amenities.id", ondelete="CASCADE"), nullable=False
    )
    flat_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="CASCADE"), nullable=False
    )
    booked_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    booked_by_name: Mapped[str] = mapped_column(String(150), nullable=False)

    booking_date: Mapped[date] = mapped_column(Date, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    slots: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")

    guests: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    purpose: Mapped[str | None] = mapped_column(String(300))

    status: Mapped[BookingStatus] = mapped_column(
        booking_status_enum, nullable=False, server_default=BookingStatus.CONFIRMED.value
    )
    charge: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    """Snapshotted from the amenity at booking time. A rate rise next month must
    not change what a resident already agreed to pay — the same rule the
    billing engine applies to a published bill."""

    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(300))

    amenity: Mapped[Amenity] = relationship(lazy="selectin")
    flat: Mapped["object"] = relationship("Flat", lazy="selectin")

    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="window_order"),
        CheckConstraint("slots BETWEEN 1 AND 48", name="slots_range"),
        CheckConstraint("guests BETWEEN 0 AND 500", name="guests_range"),
        CheckConstraint("charge >= 0", name="charge_non_negative"),
        # The double-booking guarantee. `&&` is range overlap; the WHERE clause
        # means a cancelled or rejected booking stops holding its slot.
        ExcludeConstraint(
            ("amenity_id", "="),
            (func.tstzrange(starts_at, ends_at, "[)"), "&&"),
            name="no_overlapping_bookings",
            using="gist",
            where=BOOKING_HOLDS_SLOT,
        ),
        Index("ix_bookings_amenity_date", "amenity_id", "booking_date"),
        Index("ix_bookings_flat", "flat_id", "starts_at"),
        Index(
            "ix_bookings_upcoming",
            "starts_at",
            postgresql_where=BOOKING_HOLDS_SLOT,
        ),
    )

    def __repr__(self) -> str:
        return f"<AmenityBooking {self.amenity_id} {self.booking_date}>"


__all__ = [
    "BOOKING_HOLDS_SLOT",
    "Amenity",
    "AmenityBooking",
    "Notice",
    "NoticeRead",
]
