"""Structure and resident services.

Two things here are worth reading before changing anything:

* **Owner scoping.** A ``FLAT_OWNER`` may hold ``flat.read`` and still only see
  their own flats. The narrowing is decided by
  ``Principal.is_scoped_to_own(...)`` — never by checking for the FLAT_OWNER
  role, because a principal who also holds ``flat.manage`` must not be narrowed.

* **The flat counter.** ``societies.total_flats`` lives in the *central*
  database so the Super Admin society list does not have to fan out across every
  tenant. It is refreshed from the tenant's real count after any change, in a
  separate session, and a failure to refresh never fails the request.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import (
    AlreadyExistsError,
    ConflictError,
    NotFoundError,
    ResourceForbiddenError,
    ValidationError,
)
from app.core.permissions import ACCESS_LEVEL_ROLES, Permission
from app.models.central import Society
from app.models.tenant import (
    Block,
    Building,
    FamilyAccessLevel,
    FamilyMember,
    Flat,
    Floor,
    OccupancyStatus,
    Resident,
    ResidentType,
)
from app.repositories.structure import (
    BlockRepository,
    BuildingRepository,
    FamilyMemberRepository,
    FlatRepository,
    FloorRepository,
    ResidentRepository,
)
from app.schemas.structure import (
    BlockCreate,
    BlockUpdate,
    BuildingCreate,
    BuildingUpdate,
    FamilyMemberCreate,
    FamilyMemberUpdate,
    FlatBulkCreate,
    FlatCreate,
    FlatUpdate,
    FloorCreate,
    FloorRangeCreate,
    FloorUpdate,
    ResidentCreate,
    ResidentUpdate,
)
from app.services.audit import AuditService, diff

log = structlog.get_logger(__name__)


class AuditAction:
    BUILDING_CREATED = "BUILDING_CREATED"
    BUILDING_UPDATED = "BUILDING_UPDATED"
    BUILDING_DELETED = "BUILDING_DELETED"
    BLOCK_CREATED = "BLOCK_CREATED"
    BLOCK_UPDATED = "BLOCK_UPDATED"
    BLOCK_DELETED = "BLOCK_DELETED"
    FLOOR_CREATED = "FLOOR_CREATED"
    FLOOR_UPDATED = "FLOOR_UPDATED"
    FLOOR_DELETED = "FLOOR_DELETED"
    FLAT_CREATED = "FLAT_CREATED"
    FLATS_BULK_CREATED = "FLATS_BULK_CREATED"
    FLAT_UPDATED = "FLAT_UPDATED"
    FLAT_DELETED = "FLAT_DELETED"
    RESIDENT_CREATED = "RESIDENT_CREATED"
    RESIDENT_UPDATED = "RESIDENT_UPDATED"
    RESIDENT_DELETED = "RESIDENT_DELETED"
    FAMILY_MEMBER_CREATED = "FAMILY_MEMBER_CREATED"
    FAMILY_MEMBER_UPDATED = "FAMILY_MEMBER_UPDATED"
    FAMILY_MEMBER_DELETED = "FAMILY_MEMBER_DELETED"


# --------------------------------------------------------------------------- #
# Central flat counter
# --------------------------------------------------------------------------- #


async def sync_flat_count(society_id: uuid.UUID, total: int) -> None:
    """Refresh ``societies.total_flats`` in the central database.

    Best-effort: a denormalised display counter must never fail the write that
    changed the flats. It is recomputed from the tenant's real count on every
    change, so a missed update self-heals on the next one.
    """
    try:
        from app.database.central import central_session

        async with central_session() as session:
            await session.execute(
                update(Society).where(Society.id == society_id).values(total_flats=total)
            )
    except Exception as exc:  # pragma: no cover - display counter only
        log.warning("society.flat_count_sync_failed", society_id=str(society_id), error=str(exc))


# --------------------------------------------------------------------------- #
# Buildings
# --------------------------------------------------------------------------- #


class BuildingService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = BuildingRepository(tenant)

    async def list(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        buildings = await self.repo.list(include_inactive=include_inactive)
        counts = await self.repo.counts()
        return [_building_dict(b, counts.get(b.id, {})) for b in buildings]

    async def get(self, building_id: uuid.UUID) -> dict[str, Any]:
        building = await self.repo.get(building_id)
        if building is None:
            raise NotFoundError("Building")
        counts = await self.repo.counts()
        return _building_dict(building, counts.get(building.id, {}))

    async def create(
        self, payload: BuildingCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        if await self.repo.get_by_code(payload.code):
            raise AlreadyExistsError(f"A building with code '{payload.code}' already exists.")

        building = Building(**payload.model_dump())
        await self.repo.create(building)

        # A society with no wings still gets one block, so the hierarchy is
        # uniform and no downstream query has to special-case a missing level.
        block = Block(
            building_id=building.id, name="Main", code="M", sort_order=0, is_active=True
        )
        BlockRepository(self.tenant).session.add(block)
        await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.BUILDING_CREATED,
            principal=principal,
            target_type="building",
            target_id=building.id,
            changes={"after": {"name": building.name, "code": building.code}},
            request_id=request_id,
        )
        return await self.get(building.id)

    async def update(
        self,
        building_id: uuid.UUID,
        payload: BuildingUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        building = await self.repo.get(building_id)
        if building is None:
            raise NotFoundError("Building")

        before = _snapshot(building)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(building, field, value)
        await self.tenant.flush()
        await self.tenant.refresh(building)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.BUILDING_UPDATED,
            principal=principal,
            target_type="building",
            target_id=building.id,
            changes=diff(before, _snapshot(building)),
            request_id=request_id,
        )
        return await self.get(building.id)

    async def delete(
        self, building_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        building = await self.repo.get(building_id)
        if building is None:
            raise NotFoundError("Building")

        counts = (await self.repo.counts()).get(building_id, {})
        if counts.get("flats", 0):
            raise ConflictError(
                f"This building still has {counts['flats']} flat(s). "
                "Remove or reassign them before deleting it."
            )

        await self.tenant.delete(building)
        await self.tenant.flush()
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.BUILDING_DELETED,
            principal=principal,
            target_type="building",
            target_id=building_id,
            changes={"before": {"name": building.name, "code": building.code}},
            request_id=request_id,
        )


# --------------------------------------------------------------------------- #
# Blocks
# --------------------------------------------------------------------------- #


class BlockService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = BlockRepository(tenant)

    async def list(
        self, *, building_id: uuid.UUID | None = None, include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        blocks = await self.repo.list(building_id=building_id, include_inactive=include_inactive)
        counts = await self.repo.counts()
        return [_block_dict(b, counts.get(b.id, {})) for b in blocks]

    async def get(self, block_id: uuid.UUID) -> dict[str, Any]:
        block = await self.repo.get(block_id)
        if block is None:
            raise NotFoundError("Block")
        counts = await self.repo.counts()
        return _block_dict(block, counts.get(block.id, {}))

    async def create(
        self, payload: BlockCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        if await BuildingRepository(self.tenant).get(payload.building_id) is None:
            raise NotFoundError("Building")
        if await self.repo.get_by_code(payload.building_id, payload.code):
            raise AlreadyExistsError(
                f"This building already has a block with code '{payload.code}'."
            )

        block = Block(**payload.model_dump())
        await self.repo.create(block)
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.BLOCK_CREATED,
            principal=principal,
            target_type="block",
            target_id=block.id,
            changes={"after": {"name": block.name, "code": block.code}},
            request_id=request_id,
        )
        return await self.get(block.id)

    async def update(
        self,
        block_id: uuid.UUID,
        payload: BlockUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        block = await self.repo.get(block_id)
        if block is None:
            raise NotFoundError("Block")

        before = _snapshot(block)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(block, field, value)
        await self.tenant.flush()
        await self.tenant.refresh(block)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.BLOCK_UPDATED,
            principal=principal,
            target_type="block",
            target_id=block.id,
            changes=diff(before, _snapshot(block)),
            request_id=request_id,
        )
        return await self.get(block.id)

    async def delete(
        self, block_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        block = await self.repo.get(block_id)
        if block is None:
            raise NotFoundError("Block")

        counts = (await self.repo.counts()).get(block_id, {})
        if counts.get("flats", 0):
            raise ConflictError(
                f"This block still has {counts['flats']} flat(s). "
                "Remove or reassign them before deleting it."
            )

        await self.tenant.delete(block)
        await self.tenant.flush()
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.BLOCK_DELETED,
            principal=principal,
            target_type="block",
            target_id=block_id,
            request_id=request_id,
        )


# --------------------------------------------------------------------------- #
# Floors
# --------------------------------------------------------------------------- #


class FloorService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = FloorRepository(tenant)

    async def list(
        self, *, block_id: uuid.UUID | None = None, building_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        floors = await self.repo.list(block_id=block_id, building_id=building_id)
        counts = await self.repo.flat_counts()
        return [_floor_dict(f, counts.get(f.id, 0)) for f in floors]

    async def get(self, floor_id: uuid.UUID) -> dict[str, Any]:
        floor = await self.repo.get_with_parents(floor_id)
        if floor is None:
            raise NotFoundError("Floor")
        counts = await self.repo.flat_counts()
        return _floor_dict(floor, counts.get(floor.id, 0))

    async def create(
        self, payload: FloorCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        if await BlockRepository(self.tenant).get(payload.block_id) is None:
            raise NotFoundError("Block")
        if await self.repo.get_by_number(payload.block_id, payload.number):
            raise AlreadyExistsError(f"This block already has floor {payload.number}.")

        floor = Floor(**payload.model_dump(), sort_order=payload.number)
        await self.repo.create(floor)
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FLOOR_CREATED,
            principal=principal,
            target_type="floor",
            target_id=floor.id,
            changes={"after": {"number": floor.number}},
            request_id=request_id,
        )
        return await self.get(floor.id)

    async def create_range(
        self, payload: FloorRangeCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        """Create a contiguous run of floors, skipping any that already exist."""
        if await BlockRepository(self.tenant).get(payload.block_id) is None:
            raise NotFoundError("Block")

        existing = {
            f.number for f in await self.repo.list(block_id=payload.block_id)
        }
        wanted = range(payload.from_number, payload.to_number + 1)
        to_create = [n for n in wanted if n not in existing]

        for number in to_create:
            self.tenant.add(Floor(block_id=payload.block_id, number=number, sort_order=number))
        await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FLOOR_CREATED,
            principal=principal,
            target_type="block",
            target_id=payload.block_id,
            changes={
                "after": {
                    "range": f"{payload.from_number}..{payload.to_number}",
                    "created": len(to_create),
                }
            },
            request_id=request_id,
        )
        return {
            "created": len(to_create),
            "skipped": len(list(wanted)) - len(to_create),
            "floors": await self.list(block_id=payload.block_id),
        }

    async def update(
        self,
        floor_id: uuid.UUID,
        payload: FloorUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        floor = await self.repo.get(floor_id)
        if floor is None:
            raise NotFoundError("Floor")

        values = payload.model_dump(exclude_unset=True)
        if (number := values.get("number")) is not None and number != floor.number:
            clash = await self.repo.get_by_number(floor.block_id, number)
            if clash is not None:
                raise AlreadyExistsError(f"This block already has floor {number}.")
            values["sort_order"] = number

        before = _snapshot(floor)
        for field, value in values.items():
            setattr(floor, field, value)
        await self.tenant.flush()
        await self.tenant.refresh(floor)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FLOOR_UPDATED,
            principal=principal,
            target_type="floor",
            target_id=floor.id,
            changes=diff(before, _snapshot(floor)),
            request_id=request_id,
        )
        return await self.get(floor.id)

    async def delete(
        self, floor_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        floor = await self.repo.get(floor_id)
        if floor is None:
            raise NotFoundError("Floor")

        flat_count = (await self.repo.flat_counts()).get(floor_id, 0)
        if flat_count:
            raise ConflictError(
                f"This floor still has {flat_count} flat(s). "
                "Remove or reassign them before deleting it."
            )

        await self.tenant.delete(floor)
        await self.tenant.flush()
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FLOOR_DELETED,
            principal=principal,
            target_type="floor",
            target_id=floor_id,
            request_id=request_id,
        )


# --------------------------------------------------------------------------- #
# Flats
# --------------------------------------------------------------------------- #


class FlatService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = FlatRepository(tenant)

    def _owner_scope(self, principal: Principal) -> list[uuid.UUID] | None:
        """Flat ids this principal is narrowed to, or None for society-wide."""
        if principal.is_scoped_to_own(Permission.FLAT_READ):
            return sorted(principal.flat_ids)
        return None

    async def list(
        self,
        principal: Principal,
        *,
        page: int,
        limit: int,
        q: str | None = None,
        building_id: uuid.UUID | None = None,
        block_id: uuid.UUID | None = None,
        floor_id: uuid.UUID | None = None,
        occupancy_status: OccupancyStatus | None = None,
        flat_type: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.repo.list(
            page=page,
            limit=limit,
            q=q,
            building_id=building_id,
            block_id=block_id,
            floor_id=floor_id,
            occupancy_status=occupancy_status,
            flat_type=flat_type,
            only_ids=self._owner_scope(principal),
        )
        counts = await self.repo.resident_counts([f.id for f in rows])
        return [_flat_dict(f, counts.get(f.id, 0)) for f in rows], total

    async def get(self, flat_id: uuid.UUID, principal: Principal) -> dict[str, Any]:
        flat = await self.repo.get_detailed(flat_id)
        if flat is None:
            raise NotFoundError("Flat")

        scope = self._owner_scope(principal)
        if scope is not None and flat.id not in scope:
            # 404 rather than 403: a scoped principal should not be able to
            # confirm the existence of a flat they cannot see.
            raise NotFoundError("Flat")

        residents = await ResidentRepository(self.tenant).list_for_flat(flat_id)
        payload = _flat_dict(flat, len(residents))
        payload["residents"] = [
            {
                "id": r.id,
                "full_name": r.full_name,
                "phone": r.phone,
                "email": r.email,
                "resident_type": r.resident_type,
                "is_primary": r.is_primary,
            }
            for r in residents
        ]
        return payload

    async def create(
        self,
        payload: FlatCreate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        floor = await FloorRepository(self.tenant).get_with_parents(payload.floor_id)
        if floor is None:
            raise NotFoundError("Floor")
        if await self.repo.get_by_number(floor.block.building_id, payload.flat_number):
            raise AlreadyExistsError(
                f"Flat '{payload.flat_number}' already exists in this building."
            )

        flat = Flat(
            **payload.model_dump(),
            # Set explicitly so the in-memory object is correct without a
            # refresh; the database trigger is the guarantee, not the source.
            block_id=floor.block_id,
            building_id=floor.block.building_id,
        )
        await self.repo.create(flat)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FLAT_CREATED,
            principal=principal,
            target_type="flat",
            target_id=flat.id,
            changes={"after": {"flat_number": flat.flat_number, "area_sqft": str(flat.area_sqft)}},
            request_id=request_id,
        )
        return await self.get(flat.id, principal)

    async def bulk_create(
        self, payload: FlatBulkCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        """Generate a block's flats from a numbering pattern."""
        block = await BlockRepository(self.tenant).get(payload.block_id)
        if block is None:
            raise NotFoundError("Block")
        building = await BuildingRepository(self.tenant).get(block.building_id)
        if building is None:  # pragma: no cover - FK guarantees this
            raise NotFoundError("Building")

        floor_repo = FloorRepository(self.tenant)
        existing_floors = {f.number: f for f in await floor_repo.list(block_id=payload.block_id)}

        floors_created = 0
        wanted_floors = list(range(payload.from_floor, payload.to_floor + 1))
        missing = [n for n in wanted_floors if n not in existing_floors]

        if missing and not payload.create_missing_floors:
            raise ValidationError(
                f"Floors {', '.join(map(str, missing))} do not exist in this block. "
                "Enable create_missing_floors, or create them first."
            )

        if missing and not payload.dry_run:
            for number in missing:
                floor = Floor(block_id=payload.block_id, number=number, sort_order=number)
                self.tenant.add(floor)
                existing_floors[number] = floor
            await self.tenant.flush()
            floors_created = len(missing)

        # Generate the numbers first so conflicts are reported before any write.
        generated: list[tuple[int, str]] = []
        for floor_number in wanted_floors:
            for i in range(payload.flats_per_floor):
                number = _render_pattern(
                    payload.pattern,
                    building=building.code,
                    block=block.code,
                    floor=floor_number,
                    index=payload.start_index + i,
                )
                generated.append((floor_number, number))

        numbers = [n for _, n in generated]
        if len(set(n.upper() for n in numbers)) != len(numbers):
            raise ValidationError(
                "This pattern produces duplicate flat numbers. "
                "Include {floor} in the pattern, or widen the index."
            )

        clashing = await self.repo.existing_numbers(block.building_id, numbers)
        to_create = [(f, n) for f, n in generated if n.upper() not in clashing]

        if payload.dry_run:
            return {
                "created": 0,
                "skipped": len(clashing),
                "floors_created": 0,
                "dry_run": True,
                "preview": numbers[:50],
                "conflicts": sorted(clashing)[:50],
            }

        flats = [
            Flat(
                floor_id=existing_floors[floor_number].id,
                block_id=block.id,
                building_id=block.building_id,
                flat_number=number,
                flat_type=payload.flat_type,
                area_sqft=payload.area_sqft,
                carpet_area_sqft=payload.carpet_area_sqft,
                occupancy_status=payload.occupancy_status,
            )
            for floor_number, number in to_create
        ]
        await self.repo.create_many(flats)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FLATS_BULK_CREATED,
            principal=principal,
            target_type="block",
            target_id=block.id,
            changes={
                "after": {
                    "created": len(flats),
                    "skipped": len(clashing),
                    "floors": f"{payload.from_floor}..{payload.to_floor}",
                    "pattern": payload.pattern,
                }
            },
            request_id=request_id,
        )
        log.info(
            "flats.bulk_created",
            society_id=str(principal.society_id),
            created=len(flats),
            skipped=len(clashing),
        )
        return {
            "created": len(flats),
            "skipped": len(clashing),
            "floors_created": floors_created,
            "dry_run": False,
            "preview": [n for _, n in to_create][:50],
            "conflicts": sorted(clashing)[:50],
        }

    async def update(
        self,
        flat_id: uuid.UUID,
        payload: FlatUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        flat = await self.repo.get(flat_id)
        if flat is None:
            raise NotFoundError("Flat")

        values = payload.model_dump(exclude_unset=True)

        target_building = flat.building_id
        if (floor_id := values.get("floor_id")) and floor_id != flat.floor_id:
            moved_to = await FloorRepository(self.tenant).get_with_parents(floor_id)
            if moved_to is None:
                raise NotFoundError("Floor")
            target_building = moved_to.block.building_id
            values["block_id"] = moved_to.block_id
            values["building_id"] = target_building

        number = values.get("flat_number", flat.flat_number)
        if number.upper() != flat.flat_number.upper() or target_building != flat.building_id:
            clash = await self.repo.get_by_number(target_building, number)
            if clash is not None and clash.id != flat.id:
                raise AlreadyExistsError(
                    f"Flat '{number}' already exists in the target building."
                )

        before = _snapshot(flat)
        for field, value in values.items():
            setattr(flat, field, value)
        await self.tenant.flush()
        await self.tenant.refresh(flat)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FLAT_UPDATED,
            principal=principal,
            target_type="flat",
            target_id=flat.id,
            changes=diff(before, _snapshot(flat)),
            request_id=request_id,
        )
        return await self.get(flat.id, principal)

    async def delete(
        self, flat_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        flat = await self.repo.get(flat_id)
        if flat is None:
            raise NotFoundError("Flat")

        residents = await ResidentRepository(self.tenant).list_for_flat(flat_id)
        if residents:
            raise ConflictError(
                f"This flat still has {len(residents)} active resident(s). "
                "Move them out before deleting it."
            )

        await self.tenant.delete(flat)
        await self.tenant.flush()
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FLAT_DELETED,
            principal=principal,
            target_type="flat",
            target_id=flat_id,
            changes={"before": {"flat_number": flat.flat_number}},
            request_id=request_id,
        )


# --------------------------------------------------------------------------- #
# Residents
# --------------------------------------------------------------------------- #


class ResidentService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = ResidentRepository(tenant)

    def _owner_scope(self, principal: Principal) -> list[uuid.UUID] | None:
        if principal.is_scoped_to_own(Permission.RESIDENT_READ):
            return sorted(principal.flat_ids)
        return None

    async def list(
        self,
        principal: Principal,
        *,
        page: int,
        limit: int,
        q: str | None = None,
        flat_id: uuid.UUID | None = None,
        building_id: uuid.UUID | None = None,
        resident_type: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.repo.list(
            page=page,
            limit=limit,
            q=q,
            flat_id=flat_id,
            building_id=building_id,
            resident_type=resident_type,
            only_flat_ids=self._owner_scope(principal),
        )
        return [_resident_dict(r) for r in rows], total

    async def get(self, resident_id: uuid.UUID, principal: Principal) -> dict[str, Any]:
        resident = await self.repo.get_detailed(resident_id)
        if resident is None:
            raise NotFoundError("Resident")

        scope = self._owner_scope(principal)
        if scope is not None and resident.flat_id not in scope:
            raise NotFoundError("Resident")

        payload = _resident_dict(resident)
        payload["family_members"] = [
            {
                "id": m.id,
                "resident_id": m.resident_id,
                "full_name": m.full_name,
                "relationship_to_resident": m.relationship_to_resident,
                "date_of_birth": m.date_of_birth,
                "phone": m.phone,
            }
            for m in resident.family_members
        ]
        return payload

    async def create(
        self, payload: ResidentCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        flat = await FlatRepository(self.tenant).get(payload.flat_id)
        if flat is None:
            raise NotFoundError("Flat")

        values = payload.model_dump()
        if values.get("email"):
            values["email"] = str(values["email"]).lower()

        # ux_residents_primary makes a second active primary a database error;
        # demote the incumbent first so the admin's intent wins cleanly.
        if values.get("is_primary"):
            await self._demote_primary(payload.flat_id)

        resident = Resident(**values)
        await self.repo.create(resident)
        await self._sync_occupancy(flat)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.RESIDENT_CREATED,
            principal=principal,
            target_type="resident",
            target_id=resident.id,
            changes={
                "after": {
                    "full_name": resident.full_name,
                    "flat": flat.flat_number,
                    "type": resident.resident_type.value,
                }
            },
            request_id=request_id,
        )
        return await self.get(resident.id, principal)

    async def update(
        self,
        resident_id: uuid.UUID,
        payload: ResidentUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        resident = await self.repo.get(resident_id)
        if resident is None:
            raise NotFoundError("Resident")

        values = payload.model_dump(exclude_unset=True)
        if values.get("email"):
            values["email"] = str(values["email"]).lower()
        if values.get("is_primary") and not resident.is_primary:
            await self._demote_primary(resident.flat_id, exclude=resident.id)

        before = _snapshot(resident)
        for field, value in values.items():
            setattr(resident, field, value)
        await self.tenant.flush()
        await self.tenant.refresh(resident)

        flat = await FlatRepository(self.tenant).get(resident.flat_id)
        if flat is not None:
            await self._sync_occupancy(flat)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.RESIDENT_UPDATED,
            principal=principal,
            target_type="resident",
            target_id=resident.id,
            changes=diff(before, _snapshot(resident)),
            request_id=request_id,
        )
        return await self.get(resident.id, principal)

    async def delete(
        self, resident_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        resident = await self.repo.get(resident_id)
        if resident is None:
            raise NotFoundError("Resident")

        flat_id = resident.flat_id
        await self.tenant.delete(resident)
        await self.tenant.flush()

        flat = await FlatRepository(self.tenant).get(flat_id)
        if flat is not None:
            await self._sync_occupancy(flat)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.RESIDENT_DELETED,
            principal=principal,
            target_type="resident",
            target_id=resident_id,
            changes={"before": {"full_name": resident.full_name}},
            request_id=request_id,
        )

    async def _demote_primary(
        self, flat_id: uuid.UUID, exclude: uuid.UUID | None = None
    ) -> None:
        current = await self.repo.current_primary(flat_id)
        if current is not None and current.id != exclude:
            current.is_primary = False
            await self.tenant.flush()

    async def _sync_occupancy(self, flat: Flat) -> None:
        """Derive the flat's occupancy from who actually lives there.

        Keeps a billing input honest: a flat marked VACANT with an owner living
        in it would be billed on the wrong branch of a formula.
        """
        residents = await self.repo.list_for_flat(flat.id)
        if not residents:
            status = OccupancyStatus.VACANT
        elif any(r.resident_type is ResidentType.TENANT for r in residents):
            status = OccupancyStatus.RENTED
        else:
            status = OccupancyStatus.OWNER_OCCUPIED

        if flat.occupancy_status is not status:
            flat.occupancy_status = status
            await self.tenant.flush()


class FamilyMemberService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = FamilyMemberRepository(tenant)

    async def _assert_visible(self, resident_id: uuid.UUID, principal: Principal) -> Resident:
        resident = await ResidentRepository(self.tenant).get(resident_id)
        if resident is None:
            raise NotFoundError("Resident")
        if principal.is_scoped_to_own(Permission.RESIDENT_READ) and not principal.owns_flat(
            resident.flat_id
        ):
            raise ResourceForbiddenError()
        return resident

    async def _assert_can_manage(
        self, resident_id: uuid.UUID, principal: Principal
    ) -> Resident:
        """Only the flat admin may change a household.

        Owner scoping alone is not enough here. It narrows a resident to their
        own flat, which would still let *any* resident on that flat edit the
        roster and hand out logins. "Flat admin" has to mean one person, so the
        authority is the flat's primary resident — the row the
        ``ux_residents_primary`` unique index already guarantees is unique —
        plus any co-admin they have appointed.

        A Society Admin holds ``resident.manage``, which broadens
        ``family.manage`` society-wide and skips this check entirely.
        """
        resident = await self._assert_visible(resident_id, principal)

        if not principal.is_scoped_to_own(Permission.FAMILY_MANAGE):
            return resident  # Society Admin: society-wide.

        if principal.tenant_user_id is None:
            raise ResourceForbiddenError()

        if await self.repo.is_flat_admin(resident.flat_id, principal.tenant_user_id):
            return resident

        raise ResourceForbiddenError(
            "Only the flat's primary resident can manage its family members."
        )

    async def list(self, resident_id: uuid.UUID, principal: Principal) -> list[dict[str, Any]]:
        await self._assert_visible(resident_id, principal)
        return [_family_dict(m) for m in await self.repo.list_for_resident(resident_id)]

    async def create(
        self, payload: FamilyMemberCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        await self._assert_can_manage(payload.resident_id, principal)
        values = payload.model_dump()
        if values.get("email"):
            await self._assert_email_free(str(values["email"]).lower())
            values["email"] = str(values["email"]).lower()
        member = FamilyMember(**values)
        await self.repo.create(member)
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FAMILY_MEMBER_CREATED,
            principal=principal,
            target_type="family_member",
            target_id=member.id,
            changes={"after": {"full_name": member.full_name}},
            request_id=request_id,
        )
        return _family_dict(member)

    async def update(
        self,
        member_id: uuid.UUID,
        payload: FamilyMemberUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        member = await self.repo.get(member_id)
        if member is None:
            raise NotFoundError("Family member")
        await self._assert_can_manage(member.resident_id, principal)

        before = _snapshot(member)
        values = payload.model_dump(exclude_unset=True)
        if values.get("email"):
            values["email"] = str(values["email"]).lower()
            await self._assert_email_free(values["email"], exclude=member.id)
        for field, value in values.items():
            setattr(member, field, value)
        await self.tenant.flush()
        await self.tenant.refresh(member)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FAMILY_MEMBER_UPDATED,
            principal=principal,
            target_type="family_member",
            target_id=member.id,
            changes=diff(before, _snapshot(member)),
            request_id=request_id,
        )
        return _family_dict(member)

    async def delete(
        self, member_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        member = await self.repo.get(member_id)
        if member is None:
            raise NotFoundError("Family member")
        await self._assert_can_manage(member.resident_id, principal)

        # A member who could sign in must lose that first, or the tenant user
        # would outlive the row that scopes it to a flat.
        revoked_user_id = member.user_id
        if revoked_user_id is not None:
            await self.repo.deactivate_user(revoked_user_id)

        await self.tenant.delete(member)
        await self.tenant.flush()
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FAMILY_MEMBER_DELETED,
            principal=principal,
            target_type="family_member",
            target_id=member_id,
            changes={"before": {"user_id": str(revoked_user_id) if revoked_user_id else None}},
            request_id=request_id,
        )

    # -- app access --------------------------------------------------------- #

    async def _assert_email_free(
        self, email: str, *, exclude: uuid.UUID | None = None
    ) -> None:
        """One address, one person — across residents, users and family alike.

        Checked here rather than relied upon from the partial unique index
        alone, because the clash is usually with a *resident* or an existing
        tenant user, which that index does not cover.
        """
        if await self.repo.email_taken(email, exclude=exclude):
            raise AlreadyExistsError(f"{email} is already in use in this society.")

    async def grant_access(
        self,
        member_id: uuid.UUID,
        access_level: FamilyAccessLevel,
        principal: Principal,
        *,
        email: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Give a family member a login, or change the tier of an existing one.

        Creates only the *tenant* half. The central ``platform_users`` row that
        makes the account resolvable at sign-in lives in another database and
        therefore another session, so the router creates it — the same split
        ``create_user`` in ``app/api/v1/society.py`` uses.

        No password is set or stored anywhere: ``firebase_uid`` is written as a
        ``pending:`` placeholder that ``PrincipalResolver._link_by_email`` binds
        on first sign-in.
        """
        if access_level is FamilyAccessLevel.NONE:
            raise ValidationError("Use revoke to remove a family member's access.")

        member = await self.repo.get(member_id)
        if member is None:
            raise NotFoundError("Family member")
        await self._assert_can_manage(member.resident_id, principal)

        address = (email or member.email or "").strip().lower()
        if not address:
            raise ValidationError("An email address is required to grant app access.")

        before = _snapshot(member)
        role = ACCESS_LEVEL_ROLES[access_level.value]

        if member.user_id is None:
            # Re-inviting somebody whose access was revoked adopts their old
            # dormant account, because it still holds the address under the
            # society-wide unique index on users.email.
            reclaimed = await self.repo.reclaimable_login(address)
            if reclaimed is not None:
                member.user_id = reclaimed
                await self.repo.update_login_email(reclaimed, address)
            else:
                await self._assert_email_free(address, exclude=member.id)
                member.user_id = await self.repo.create_login(
                    email=address, full_name=member.full_name, phone=member.phone
                )
        elif address != (member.email or "").lower():
            await self._assert_email_free(address, exclude=member.id)
            await self.repo.update_login_email(member.user_id, address)

        # access_level is the source of truth; the role is derived from it, so
        # a tier change is a replace rather than an add.
        await self.repo.set_login_role(member.user_id, role, principal.tenant_user_id)
        await self.repo.reactivate_user(member.user_id)

        member.email = address
        member.access_level = access_level
        await self.tenant.flush()
        await self.tenant.refresh(member)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FAMILY_MEMBER_UPDATED,
            principal=principal,
            target_type="family_member",
            target_id=member.id,
            changes=diff(before, _snapshot(member)),
            request_id=request_id,
        )
        return _family_dict(member)

    async def revoke_access(
        self, member_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        """Take away the login but keep the person on the roster.

        Deactivating rather than deleting keeps the audit trail — and every
        complaint they filed — attributable.
        """
        member = await self.repo.get(member_id)
        if member is None:
            raise NotFoundError("Family member")
        await self._assert_can_manage(member.resident_id, principal)

        if member.user_id is None:
            raise ConflictError("This family member does not have app access.")

        before = _snapshot(member)
        await self.repo.deactivate_user(member.user_id)
        member.user_id = None
        member.access_level = FamilyAccessLevel.NONE
        await self.tenant.flush()
        await self.tenant.refresh(member)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.FAMILY_MEMBER_UPDATED,
            principal=principal,
            target_type="family_member",
            target_id=member.id,
            changes=diff(before, _snapshot(member)),
            request_id=request_id,
        )
        return _family_dict(member)


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #


class StructureOverviewService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant

    async def summary(self) -> dict[str, Any]:
        buildings = await BuildingRepository(self.tenant).list()
        blocks = await BlockRepository(self.tenant).list()
        floors = await FloorRepository(self.tenant).list()
        flat_repo = FlatRepository(self.tenant)
        resident_repo = ResidentRepository(self.tenant)

        return {
            "buildings": len(buildings),
            "blocks": len(blocks),
            "floors": len(floors),
            "flats": await flat_repo.count(),
            "residents": await resident_repo.count(),
            "total_area_sqft": await flat_repo.total_area(),
            "occupancy": await flat_repo.counts_by_occupancy(),
            "resident_types": await resident_repo.counts_by_type(),
            "flat_types": await flat_repo.distinct_types(),
        }

    async def tree(self) -> list[dict[str, Any]]:
        """Building → block → floor hierarchy for pickers.

        Four queries regardless of size, rather than one per node.
        """
        buildings = await BuildingRepository(self.tenant).list()
        blocks = await BlockRepository(self.tenant).list()
        floors = await FloorRepository(self.tenant).list()
        floor_flat_counts = await FloorRepository(self.tenant).flat_counts()

        floors_by_block: dict[uuid.UUID, list[Any]] = {}
        for floor in floors:
            floors_by_block.setdefault(floor.block_id, []).append(floor)

        blocks_by_building: dict[uuid.UUID, list[Any]] = {}
        for block in blocks:
            blocks_by_building.setdefault(block.building_id, []).append(block)

        tree = []
        for building in buildings:
            block_nodes = []
            for block in blocks_by_building.get(building.id, []):
                floor_nodes = [
                    {
                        "id": f.id,
                        "label": f.display_name,
                        "kind": "floor",
                        "flat_count": floor_flat_counts.get(f.id, 0),
                        "children": [],
                    }
                    for f in floors_by_block.get(block.id, [])
                ]
                block_nodes.append(
                    {
                        "id": block.id,
                        "label": block.name,
                        "kind": "block",
                        "flat_count": sum(n["flat_count"] for n in floor_nodes),
                        "children": floor_nodes,
                    }
                )
            tree.append(
                {
                    "id": building.id,
                    "label": building.name,
                    "kind": "building",
                    "flat_count": sum(n["flat_count"] for n in block_nodes),
                    "children": block_nodes,
                }
            )
        return tree


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_PLACEHOLDER = re.compile(r"\{(building|block|floor|index)(?::([^}]*))?\}")


def _render_pattern(pattern: str, **values: Any) -> str:
    """Render a flat-number pattern without exposing ``str.format``.

    ``str.format`` on user input reaches attributes and indices
    (``{block.__class__}``), so only the four known placeholders are
    substituted, with an optional numeric format spec.
    """

    def replace(match: re.Match[str]) -> str:
        key, spec = match.group(1), match.group(2)
        value = values[key]
        if spec:
            if not re.fullmatch(r"0?\d*d?", spec):
                raise ValidationError(f"Unsupported format '{spec}' in pattern")
            return format(int(value), spec)
        return str(value)

    return _PLACEHOLDER.sub(replace, pattern).strip()


def _building_dict(b: Building, counts: dict[str, int]) -> dict[str, Any]:
    return {
        "id": b.id,
        "name": b.name,
        "code": b.code,
        "description": b.description,
        "total_floors": b.total_floors,
        "sort_order": b.sort_order,
        "is_active": b.is_active,
        "created_at": b.created_at,
        "block_count": counts.get("blocks", 0),
        "floor_count": counts.get("floors", 0),
        "flat_count": counts.get("flats", 0),
    }


def _block_dict(b: Block, counts: dict[str, int]) -> dict[str, Any]:
    return {
        "id": b.id,
        "building_id": b.building_id,
        "building_name": b.building.name if b.building else None,
        "name": b.name,
        "code": b.code,
        "description": b.description,
        "sort_order": b.sort_order,
        "is_active": b.is_active,
        "created_at": b.created_at,
        "floor_count": counts.get("floors", 0),
        "flat_count": counts.get("flats", 0),
    }


def _floor_dict(f: Floor, flat_count: int) -> dict[str, Any]:
    block = f.block if "block" in f.__dict__ else None
    building = block.building if block and "building" in block.__dict__ else None
    return {
        "id": f.id,
        "block_id": f.block_id,
        "block_name": block.name if block else None,
        "building_id": building.id if building else None,
        "building_name": building.name if building else None,
        "number": f.number,
        "name": f.name,
        "display_name": f.display_name,
        "flat_count": flat_count,
        "created_at": f.created_at,
    }


def _flat_dict(f: Flat, resident_count: int) -> dict[str, Any]:
    floor = f.floor if "floor" in f.__dict__ else None
    block = floor.block if floor and "block" in floor.__dict__ else None
    building = block.building if block and "building" in block.__dict__ else None
    return {
        "id": f.id,
        "flat_number": f.flat_number,
        "flat_type": f.flat_type,
        "area_sqft": f.area_sqft,
        "carpet_area_sqft": f.carpet_area_sqft,
        "occupancy_status": f.occupancy_status,
        "base_maintenance_override": f.base_maintenance_override,
        "notes": f.notes,
        "is_active": f.is_active,
        "created_at": f.created_at,
        "floor_id": f.floor_id,
        "block_id": f.block_id,
        "building_id": f.building_id,
        "floor_number": floor.number if floor else None,
        "floor_name": floor.display_name if floor else None,
        "block_name": block.name if block else None,
        "building_name": building.name if building else None,
        "resident_count": resident_count,
    }


def _resident_dict(r: Resident) -> dict[str, Any]:
    flat = r.flat if "flat" in r.__dict__ else None
    return {
        "id": r.id,
        "flat_id": r.flat_id,
        "flat_number": flat.flat_number if flat else None,
        "user_id": r.user_id,
        "full_name": r.full_name,
        "email": r.email,
        "phone": r.phone,
        "resident_type": r.resident_type,
        "is_primary": r.is_primary,
        "move_in_date": r.move_in_date,
        "move_out_date": r.move_out_date,
        "is_active": r.is_active,
        "created_at": r.created_at,
    }


def _family_dict(m: FamilyMember) -> dict[str, Any]:
    return {
        "id": m.id,
        "resident_id": m.resident_id,
        "full_name": m.full_name,
        "relationship_to_resident": m.relationship_to_resident,
        "date_of_birth": m.date_of_birth,
        "phone": m.phone,
        "email": m.email,
        "access_level": m.access_level,
        "is_active": m.is_active,
        # The client renders an invite button or a revoke button off this, and
        # should not have to know that user_id is the real signal.
        "has_login": m.user_id is not None,
        # Not in FamilyMemberRead, so it never reaches a client. The router
        # needs it to write the matching central platform_users row.
        "user_id": m.user_id,
    }


def _snapshot(obj: Any) -> dict[str, Any]:
    from datetime import date as _date
    from datetime import datetime as _datetime
    from decimal import Decimal as _Decimal

    from sqlalchemy import inspect

    def plain(value: Any) -> Any:
        if isinstance(value, (uuid.UUID, _date, _datetime, _Decimal)):
            return str(value)
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, (int, float, str, bool, type(None), dict, list)):
            return value
        return str(value)

    return {
        c.key: plain(getattr(obj, c.key))
        for c in inspect(obj).mapper.column_attrs
        if c.key not in {"created_at", "updated_at"}
    }
