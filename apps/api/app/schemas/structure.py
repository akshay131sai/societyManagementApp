"""Structure and resident schemas.

None of these carries a ``society_id``. The tenant is the session.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.tenant import (
    FamilyAccessLevel,
    FamilyRelationship,
    OccupancyStatus,
    ResidentType,
)
from app.schemas.platform import IndianMobile

Code = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9\-]{0,19}$")]
Area = Annotated[Decimal, Field(gt=0, le=100_000, max_digits=10, decimal_places=2)]


# --------------------------------------------------------------------------- #
# Buildings
# --------------------------------------------------------------------------- #


class BuildingCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    code: Code
    description: Annotated[str | None, Field(max_length=1000)] = None
    total_floors: Annotated[int | None, Field(gt=0, le=200)] = None
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class BuildingUpdate(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=120)] = None
    description: Annotated[str | None, Field(max_length=1000)] = None
    total_floors: Annotated[int | None, Field(gt=0, le=200)] = None
    sort_order: int | None = None
    is_active: bool | None = None


class BuildingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    description: str | None = None
    total_floors: int | None = None
    sort_order: int
    is_active: bool
    created_at: datetime

    block_count: int = 0
    floor_count: int = 0
    flat_count: int = 0


# --------------------------------------------------------------------------- #
# Blocks
# --------------------------------------------------------------------------- #


class BlockCreate(BaseModel):
    building_id: uuid.UUID
    name: Annotated[str, Field(min_length=1, max_length=120)]
    code: Code
    description: Annotated[str | None, Field(max_length=1000)] = None
    sort_order: int = 0

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class BlockUpdate(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=120)] = None
    description: Annotated[str | None, Field(max_length=1000)] = None
    sort_order: int | None = None
    is_active: bool | None = None


class BlockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    building_id: uuid.UUID
    building_name: str | None = None
    name: str
    code: str
    description: str | None = None
    sort_order: int
    is_active: bool
    created_at: datetime

    floor_count: int = 0
    flat_count: int = 0


# --------------------------------------------------------------------------- #
# Floors
# --------------------------------------------------------------------------- #


class FloorCreate(BaseModel):
    block_id: uuid.UUID
    number: Annotated[int, Field(ge=-10, le=200)]
    """0 is ground, negative is basement."""
    name: Annotated[str | None, Field(max_length=60)] = None


class FloorRangeCreate(BaseModel):
    """Create a contiguous run of floors in one call.

    A 20-storey tower is 20 identical POSTs otherwise.
    """

    block_id: uuid.UUID
    from_number: Annotated[int, Field(ge=-10, le=200)]
    to_number: Annotated[int, Field(ge=-10, le=200)]

    @model_validator(mode="after")
    def _validate_range(self) -> FloorRangeCreate:
        if self.to_number < self.from_number:
            raise ValueError("to_number must not be less than from_number")
        if self.to_number - self.from_number + 1 > 210:
            raise ValueError("A single request may create at most 210 floors")
        return self


class FloorUpdate(BaseModel):
    number: Annotated[int | None, Field(ge=-10, le=200)] = None
    name: Annotated[str | None, Field(max_length=60)] = None


class FloorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    block_id: uuid.UUID
    block_name: str | None = None
    building_id: uuid.UUID | None = None
    building_name: str | None = None
    number: int
    name: str | None = None
    display_name: str
    flat_count: int = 0
    created_at: datetime


# --------------------------------------------------------------------------- #
# Flats
# --------------------------------------------------------------------------- #


class FlatCreate(BaseModel):
    floor_id: uuid.UUID
    flat_number: Annotated[str, Field(min_length=1, max_length=30)]
    flat_type: Annotated[str | None, Field(max_length=20)] = None
    area_sqft: Area
    carpet_area_sqft: Area | None = None
    occupancy_status: OccupancyStatus = OccupancyStatus.VACANT
    base_maintenance_override: Annotated[
        Decimal | None, Field(ge=0, max_digits=14, decimal_places=2)
    ] = None
    notes: Annotated[str | None, Field(max_length=2000)] = None

    @field_validator("flat_number")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _carpet_within_area(self) -> FlatCreate:
        if self.carpet_area_sqft is not None and self.carpet_area_sqft > self.area_sqft:
            raise ValueError("carpet_area_sqft cannot exceed area_sqft")
        return self


class FlatUpdate(BaseModel):
    floor_id: uuid.UUID | None = None
    flat_number: Annotated[str | None, Field(min_length=1, max_length=30)] = None
    flat_type: Annotated[str | None, Field(max_length=20)] = None
    area_sqft: Area | None = None
    carpet_area_sqft: Area | None = None
    occupancy_status: OccupancyStatus | None = None
    base_maintenance_override: Annotated[
        Decimal | None, Field(ge=0, max_digits=14, decimal_places=2)
    ] = None
    notes: Annotated[str | None, Field(max_length=2000)] = None
    is_active: bool | None = None


class FlatBulkCreate(BaseModel):
    """Generate a floor's (or a whole block's) flats from a numbering pattern.

    Creating 200 flats one dialog at a time is the single worst part of
    onboarding a society, so this is a first-class operation rather than a
    convenience script.
    """

    block_id: uuid.UUID
    from_floor: Annotated[int, Field(ge=-10, le=200)]
    to_floor: Annotated[int, Field(ge=-10, le=200)]
    flats_per_floor: Annotated[int, Field(ge=1, le=50)]

    pattern: Annotated[str, Field(min_length=1, max_length=40)] = "{block}-{floor}{index:02d}"
    """Placeholders: ``{building}`` ``{block}`` ``{floor}`` ``{index}``.

    ``A-101``  -> ``{block}-{floor}{index:02d}``
    ``A/1/01`` -> ``{block}/{floor}/{index:02d}``
    """

    start_index: Annotated[int, Field(ge=0, le=99)] = 1
    flat_type: Annotated[str | None, Field(max_length=20)] = None
    area_sqft: Area
    carpet_area_sqft: Area | None = None
    occupancy_status: OccupancyStatus = OccupancyStatus.VACANT
    create_missing_floors: bool = True
    dry_run: bool = False
    """Preview the generated numbers without writing anything."""

    @model_validator(mode="after")
    def _validate(self) -> FlatBulkCreate:
        if self.to_floor < self.from_floor:
            raise ValueError("to_floor must not be less than from_floor")
        total = (self.to_floor - self.from_floor + 1) * self.flats_per_floor
        if total > 2000:
            raise ValueError(
                f"This would create {total} flats; a single request is limited to 2000"
            )
        if "{index" not in self.pattern:
            raise ValueError("pattern must contain {index} so flat numbers stay unique")
        allowed = {"building", "block", "floor", "index"}
        import re

        used = {m.split(":")[0] for m in re.findall(r"\{([^}]*)\}", self.pattern)}
        if unknown := used - allowed:
            raise ValueError(
                f"Unknown placeholder(s): {', '.join(sorted(unknown))}. "
                f"Allowed: {', '.join(sorted(allowed))}"
            )
        return self


class FlatBulkResult(BaseModel):
    created: int
    skipped: int
    floors_created: int
    dry_run: bool
    preview: list[str] = []
    conflicts: list[str] = []


class ResidentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    phone: str | None = None
    email: str | None = None
    resident_type: ResidentType
    is_primary: bool


class FlatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    flat_number: str
    flat_type: str | None = None
    area_sqft: Decimal
    carpet_area_sqft: Decimal | None = None
    occupancy_status: OccupancyStatus
    base_maintenance_override: Decimal | None = None
    notes: str | None = None
    is_active: bool
    created_at: datetime

    floor_id: uuid.UUID
    block_id: uuid.UUID
    building_id: uuid.UUID
    floor_number: int | None = None
    floor_name: str | None = None
    block_name: str | None = None
    building_name: str | None = None

    resident_count: int = 0


class FlatDetail(FlatRead):
    residents: list[ResidentSummary] = []


# --------------------------------------------------------------------------- #
# Residents
# --------------------------------------------------------------------------- #


class ResidentCreate(BaseModel):
    flat_id: uuid.UUID
    full_name: Annotated[str, Field(min_length=2, max_length=150)]
    email: EmailStr | None = None
    phone: IndianMobile | None = None
    resident_type: ResidentType
    is_primary: bool = False
    move_in_date: date | None = None
    move_out_date: date | None = None

    user_id: uuid.UUID | None = None
    """Link to an existing society login, so the person sees their own flat."""

    @field_validator("full_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _dates(self) -> ResidentCreate:
        if (
            self.move_out_date is not None
            and self.move_in_date is not None
            and self.move_out_date < self.move_in_date
        ):
            raise ValueError("move_out_date cannot precede move_in_date")
        return self


class ResidentUpdate(BaseModel):
    full_name: Annotated[str | None, Field(min_length=2, max_length=150)] = None
    email: EmailStr | None = None
    phone: IndianMobile | None = None
    resident_type: ResidentType | None = None
    is_primary: bool | None = None
    move_in_date: date | None = None
    move_out_date: date | None = None
    user_id: uuid.UUID | None = None
    is_active: bool | None = None


class FamilyMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resident_id: uuid.UUID
    full_name: str
    relationship_to_resident: FamilyRelationship
    date_of_birth: date | None = None
    phone: str | None = None
    email: str | None = None
    access_level: FamilyAccessLevel = FamilyAccessLevel.NONE
    is_active: bool = True
    has_login: bool = False


class FamilyMemberCreate(BaseModel):
    resident_id: uuid.UUID
    full_name: Annotated[str, Field(min_length=2, max_length=150)]
    relationship_to_resident: FamilyRelationship
    date_of_birth: date | None = None
    phone: IndianMobile | None = None
    email: EmailStr | None = None
    """Optional at creation — a toddler on the roster needs no address.
    Required before app access can be granted."""


class FamilyMemberUpdate(BaseModel):
    full_name: Annotated[str | None, Field(min_length=2, max_length=150)] = None
    relationship_to_resident: FamilyRelationship | None = None
    date_of_birth: date | None = None
    phone: IndianMobile | None = None
    email: EmailStr | None = None
    is_active: bool | None = None


class FamilyAccessGrant(BaseModel):
    """Grant a login, or move an existing one to a different tier.

    ``NONE`` is rejected by the service: removing access is a DELETE on the
    access sub-resource, not a tier of it.
    """

    access_level: FamilyAccessLevel
    email: EmailStr | None = None
    """Falls back to the address already on the family member."""


class ResidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    flat_id: uuid.UUID
    flat_number: str | None = None
    user_id: uuid.UUID | None = None
    full_name: str
    email: str | None = None
    phone: str | None = None
    resident_type: ResidentType
    is_primary: bool
    move_in_date: date | None = None
    move_out_date: date | None = None
    is_active: bool
    created_at: datetime


class ResidentDetail(ResidentRead):
    family_members: list[FamilyMemberRead] = []


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #


class StructureSummary(BaseModel):
    buildings: int
    blocks: int
    floors: int
    flats: int
    residents: int
    total_area_sqft: float
    occupancy: dict[str, int]
    resident_types: dict[str, int]
    flat_types: list[str]


class StructureTreeNode(BaseModel):
    """Compact hierarchy for pickers and the structure page."""

    id: uuid.UUID
    label: str
    kind: Literal["building", "block", "floor"]
    flat_count: int = 0
    children: list[StructureTreeNode] = []


StructureTreeNode.model_rebuild()
