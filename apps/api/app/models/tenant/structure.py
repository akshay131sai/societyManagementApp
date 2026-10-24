"""Physical structure: buildings → blocks → floors → flats.

Every table here lives in the society's own database, so none of them carries a
``society_id``. See docs/database/tenant-schema.md section 5.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import TenantBase, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.tenant.enums import (
    FamilyAccessLevel,
    FamilyRelationship,
    OccupancyStatus,
    ResidentType,
    family_access_level_enum,
    family_relationship_enum,
    occupancy_status_enum,
    resident_type_enum,
)

if TYPE_CHECKING:
    from app.models.tenant.user import TenantUser


class Building(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    __tablename__ = "buildings"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    total_floors: Mapped[int | None] = mapped_column(SmallInteger)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    blocks: Mapped[list[Block]] = relationship(
        back_populates="building", lazy="noload", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("total_floors IS NULL OR total_floors > 0", name="floors_positive"),
        Index("ix_buildings_sort", "sort_order", "name"),
    )

    def __repr__(self) -> str:
        return f"<Building {self.code}>"


class Block(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A wing or block within a building.

    A society with no wings still gets one block per building — the seeded
    "Main" block — so the flat hierarchy is uniform and reporting never has to
    special-case a missing level.
    """

    __tablename__ = "blocks"

    building_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    building: Mapped[Building] = relationship(back_populates="blocks", lazy="selectin")
    floors: Mapped[list[Floor]] = relationship(
        back_populates="block", lazy="noload", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("building_id", "code", name="building_code"),
        Index("ix_blocks_building", "building_id", "sort_order"),
    )

    def __repr__(self) -> str:
        return f"<Block {self.code}>"


class Floor(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    __tablename__ = "floors"

    block_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("blocks.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    """0 is ground, negative is basement — both are ordinary in Indian societies."""

    name: Mapped[str | None] = mapped_column(String(60))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    block: Mapped[Block] = relationship(back_populates="floors", lazy="selectin")
    flats: Mapped[list[Flat]] = relationship(
        back_populates="floor", lazy="noload", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("block_id", "number", name="block_number"),
        CheckConstraint("number BETWEEN -10 AND 200", name="number_range"),
        Index("ix_floors_block", "block_id", "number"),
    )

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.number == 0:
            return "Ground Floor"
        if self.number < 0:
            return f"Basement {abs(self.number)}"
        return f"Floor {self.number}"

    def __repr__(self) -> str:
        return f"<Floor {self.number}>"


class Flat(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A single flat.

    ``building_id`` and ``block_id`` are denormalised alongside ``floor_id``:
    "all flats in building X" is the hottest query in a billing run, and
    carrying them here removes two joins from every flat lookup. A trigger
    derives them from ``floor_id`` on insert and update, so they cannot drift.
    """

    __tablename__ = "flats"

    floor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("floors.id", ondelete="CASCADE"), nullable=False
    )
    block_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("blocks.id", ondelete="CASCADE"), nullable=False
    )
    building_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False
    )

    flat_number: Mapped[str] = mapped_column(String(30), nullable=False)
    flat_type: Mapped[str | None] = mapped_column(String(20))
    """"1BHK", "2BHK", "3BHK", "Penthouse" — free text, because societies vary."""

    area_sqft: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    carpet_area_sqft: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    occupancy_status: Mapped[OccupancyStatus] = mapped_column(
        occupancy_status_enum, nullable=False, server_default=OccupancyStatus.VACANT.value
    )

    base_maintenance_override: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    """Per-flat override of the template's base maintenance. NULL uses the template."""

    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    floor: Mapped[Floor] = relationship(back_populates="flats", lazy="selectin")
    residents: Mapped[list[Resident]] = relationship(
        back_populates="flat",
        lazy="noload",
        cascade="all, delete-orphan",
        foreign_keys="Resident.flat_id",
    )

    __table_args__ = (
        # Unique per BUILDING, not society-wide: Tower A and Tower B both
        # having a flat "101" is ordinary, and forcing a prefix would make the
        # software argue with the signage.
        UniqueConstraint("building_id", "flat_number", name="number"),
        CheckConstraint("area_sqft > 0", name="area_positive"),
        CheckConstraint(
            "carpet_area_sqft IS NULL OR (carpet_area_sqft > 0 AND carpet_area_sqft <= area_sqft)",
            name="carpet_area_sane",
        ),
        CheckConstraint(
            "base_maintenance_override IS NULL OR base_maintenance_override >= 0",
            name="override_non_negative",
        ),
        Index("ix_flats_building", "building_id", postgresql_where="is_active"),
        Index("ix_flats_block", "block_id", postgresql_where="is_active"),
        Index("ix_flats_floor", "floor_id"),
        Index("ix_flats_occupancy", "occupancy_status", postgresql_where="is_active"),
    )

    def __repr__(self) -> str:
        return f"<Flat {self.flat_number}>"


class Resident(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A person living in a flat.

    ``user_id`` is nullable on purpose: a non-app-using owner, or an owner who
    has moved out but still owns the flat, exists as a resident with no login.
    A ``FLAT_OWNER`` principal's ``flat_ids`` comes from the rows where
    ``user_id`` matches and ``is_active`` is true.
    """

    __tablename__ = "residents"

    flat_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(10))

    resident_type: Mapped[ResidentType] = mapped_column(resident_type_enum, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    """The point of contact for the flat. At most one active primary per flat."""

    move_in_date: Mapped[date | None] = mapped_column(Date)
    move_out_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    flat: Mapped[Flat] = relationship(
        back_populates="residents", lazy="selectin", foreign_keys=[flat_id]
    )
    family_members: Mapped[list[FamilyMember]] = relationship(
        back_populates="resident", lazy="noload", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(r"phone IS NULL OR phone ~ '^[6-9][0-9]{9}$'", name="phone_format"),
        CheckConstraint(
            "move_out_date IS NULL OR move_in_date IS NULL OR move_out_date >= move_in_date",
            name="date_order",
        ),
        Index("ix_residents_flat", "flat_id", postgresql_where="is_active"),
        Index("ix_residents_user", "user_id", postgresql_where="user_id IS NOT NULL"),
        Index("ix_residents_email", func.lower(email)),
        # At most one active primary contact per flat — a database constraint,
        # not a service-layer convention, because billing and visitor routing
        # both assume it holds.
        Index(
            "ux_residents_primary",
            "flat_id",
            unique=True,
            postgresql_where="is_primary AND is_active",
        ),
    )

    def __repr__(self) -> str:
        return f"<Resident {self.full_name}>"


class FamilyMember(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A member of a resident's household. Not billed separately.

    ``user_id`` is nullable because the roster and the app account are separate
    concerns: a toddler is recorded here and will never sign in, while a spouse
    is granted a login and reaches the flat through
    ``PrincipalResolver._load_flat_ids``, which follows this row to the
    resident's ``flat_id``.

    ``access_level`` is the source of truth for how much they may see; the
    matching tenant role is derived from it via ``ACCESS_LEVEL_ROLES``.
    """

    __tablename__ = "family_members"

    resident_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("residents.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    relationship_to_resident: Mapped[FamilyRelationship] = mapped_column(
        family_relationship_enum, nullable=False
    )
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(10))
    email: Mapped[str | None] = mapped_column(String(255))

    access_level: Mapped[FamilyAccessLevel] = mapped_column(
        family_access_level_enum, nullable=False, server_default=FamilyAccessLevel.NONE.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    resident: Mapped[Resident] = relationship(back_populates="family_members", lazy="noload")

    __table_args__ = (
        CheckConstraint(r"phone IS NULL OR phone ~ '^[6-9][0-9]{9}$'", name="phone_format"),
        # Granting app access without an address to grant it to is not a state
        # the service layer should have to defend against.
        CheckConstraint(
            "access_level = 'NONE' OR email IS NOT NULL", name="access_needs_email"
        ),
        Index("ix_family_members_resident", "resident_id"),
        Index("ix_family_members_user", "user_id", postgresql_where="user_id IS NOT NULL"),
        Index(
            "ux_family_members_email",
            func.lower(email),
            unique=True,
            postgresql_where="email IS NOT NULL AND is_active",
        ),
    )

    def __repr__(self) -> str:
        return f"<FamilyMember {self.full_name}>"
