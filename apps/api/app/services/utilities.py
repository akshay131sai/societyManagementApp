"""Utility reading and asset services.

Two policies run through the whole module:

* **Owner scoping.** A resident holds ``water.read`` and still sees only their
  own meter. The narrowing comes from ``Principal.is_scoped_to_own(...)``, and
  an out-of-scope record raises ``NotFoundError`` rather than a 403 — a
  resident should not be able to confirm that flat B-704 exists by probing.

* **Meter arithmetic stays in the database.** ``consumption`` is a generated
  column. Nothing here computes it, so a correction to one reading can never
  leave a stale consumption behind.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import (
    AlreadyExistsError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.permissions import Permission
from app.models.tenant import (
    ElectricityReading,
    Flat,
    ParkingSlot,
    Pet,
    Vehicle,
    WaterReading,
)
from app.repositories.structure import FlatRepository
from app.repositories.utilities import (
    ParkingRepository,
    PetRepository,
    ReadingRepository,
    VehicleRepository,
)
from app.schemas.utilities import (
    BulkReadingCreate,
    ElectricityReadingCreate,
    ParkingAllotment,
    ParkingSlotCreate,
    ParkingSlotUpdate,
    PetCreate,
    PetUpdate,
    ReadingUpdate,
    VehicleCreate,
    VehicleUpdate,
    WaterReadingCreate,
)
from app.services.audit import AuditService, diff

log = structlog.get_logger(__name__)

ZERO = Decimal("0")


class AuditAction:
    WATER_READING_CREATED = "WATER_READING_CREATED"
    WATER_READING_UPDATED = "WATER_READING_UPDATED"
    WATER_READING_DELETED = "WATER_READING_DELETED"
    WATER_READINGS_BULK_CREATED = "WATER_READINGS_BULK_CREATED"
    ELECTRICITY_READING_CREATED = "ELECTRICITY_READING_CREATED"
    ELECTRICITY_READING_UPDATED = "ELECTRICITY_READING_UPDATED"
    ELECTRICITY_READING_DELETED = "ELECTRICITY_READING_DELETED"
    ELECTRICITY_READINGS_BULK_CREATED = "ELECTRICITY_READINGS_BULK_CREATED"
    PARKING_SLOT_CREATED = "PARKING_SLOT_CREATED"
    PARKING_SLOT_UPDATED = "PARKING_SLOT_UPDATED"
    PARKING_SLOT_ALLOTTED = "PARKING_SLOT_ALLOTTED"
    PARKING_SLOT_RELEASED = "PARKING_SLOT_RELEASED"
    VEHICLE_CREATED = "VEHICLE_CREATED"
    VEHICLE_UPDATED = "VEHICLE_UPDATED"
    VEHICLE_REMOVED = "VEHICLE_REMOVED"
    PET_CREATED = "PET_CREATED"
    PET_UPDATED = "PET_UPDATED"
    PET_REMOVED = "PET_REMOVED"


def _flat_number(obj: Any) -> str | None:
    flat = getattr(obj, "flat", None)
    return getattr(flat, "flat_number", None) if flat is not None else None


def _reading_dict(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "flat_id": r.flat_id,
        "flat_number": _flat_number(r),
        "reading_date": r.reading_date,
        "period_key": r.period_key,
        "previous_reading": r.previous_reading,
        "current_reading": r.current_reading,
        "consumption": r.consumption,
        "meter_number": r.meter_number,
        "remarks": r.remarks,
        "amount": getattr(r, "amount", None),
        "created_at": r.created_at,
    }


def _label(d: date) -> str:
    return d.strftime("%b %Y")


# --------------------------------------------------------------------------- #
# Readings
# --------------------------------------------------------------------------- #


class ReadingService:
    """Water and electricity share every behaviour; only the model, permission
    set and unit differ, so they share one service rather than two near-copies
    that drift apart."""

    def __init__(self, tenant: AsyncSession, *, utility: str) -> None:
        if utility not in ("water", "electricity"):
            raise ValueError(f"Unknown utility: {utility}")
        self.tenant = tenant
        self.utility = utility
        self.model = WaterReading if utility == "water" else ElectricityReading
        self.repo = ReadingRepository(tenant, self.model)
        self.unit = "kL" if utility == "water" else "kWh"
        self.read_permission = (
            Permission.WATER_READ if utility == "water" else Permission.ELECTRICITY_READ
        )
        self._resource = "Water reading" if utility == "water" else "Electricity reading"

    # -- scoping ------------------------------------------------------------ #

    def _owner_scope(self, principal: Principal) -> list[uuid.UUID] | None:
        if principal.is_scoped_to_own(self.read_permission):
            return sorted(principal.flat_ids)
        return None

    def _assert_can_see(self, flat_id: uuid.UUID, principal: Principal) -> None:
        scope = self._owner_scope(principal)
        if scope is not None and flat_id not in scope:
            raise NotFoundError(self._resource)

    # -- reads -------------------------------------------------------------- #

    async def list(
        self,
        principal: Principal,
        *,
        page: int,
        limit: int,
        flat_id: uuid.UUID | None = None,
        period_key: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        if flat_id is not None:
            self._assert_can_see(flat_id, principal)
        rows, total = await self.repo.list(
            page=page,
            limit=limit,
            flat_id=flat_id,
            period_key=period_key,
            from_date=from_date,
            to_date=to_date,
            only_flat_ids=self._owner_scope(principal),
        )
        return [_reading_dict(r) for r in rows], total

    async def get(self, reading_id: uuid.UUID, principal: Principal) -> dict[str, Any]:
        reading = await self.repo.get(reading_id)
        if reading is None:
            raise NotFoundError(self._resource)
        self._assert_can_see(reading.flat_id, principal)
        return _reading_dict(reading)

    async def trend(
        self, flat_id: uuid.UUID, principal: Principal, *, limit: int = 12
    ) -> dict[str, Any]:
        """The chart series plus the headline numbers behind it."""
        self._assert_can_see(flat_id, principal)
        if await FlatRepository(self.tenant).get(flat_id) is None:
            raise NotFoundError("Flat")

        rows = await self.repo.history(flat_id, limit=limit)
        points = [
            {
                "reading_date": r.reading_date,
                "label": _label(r.reading_date),
                "consumption": r.consumption,
                "current_reading": r.current_reading,
                "amount": getattr(r, "amount", None),
            }
            for r in rows
        ]
        stats = await self.repo.stats_for_flat(flat_id)

        latest = rows[-1].consumption if rows else None
        previous = rows[-2].consumption if len(rows) > 1 else None
        change: Decimal | None = None
        if latest is not None and previous not in (None, ZERO):
            assert previous is not None
            change = ((latest - previous) / previous * 100).quantize(Decimal("0.1"))

        return {
            "unit": self.unit,
            "points": points,
            "stats": stats,
            "latest": latest,
            "previous": previous,
            "change_pct": change,
        }

    async def society_trend(self, months: int = 12) -> list[dict[str, Any]]:
        since = date.today() - timedelta(days=31 * months)
        return [
            {"reading_date": d, "label": _label(d), "total": total}
            for d, total in await self.repo.society_totals(from_date=since)
        ]

    async def pending(self, principal: Principal) -> list[dict[str, Any]]:
        """Every flat with its last closing reading — the bulk entry worklist."""
        flats, _ = await FlatRepository(self.tenant).list(page=1, limit=1000)
        scope = self._owner_scope(principal)
        if scope is not None:
            flats = [f for f in flats if f.id in set(scope)]

        latest = await self.repo.latest_bulk([f.id for f in flats])
        return [
            {
                "flat_id": f.id,
                "flat_number": f.flat_number,
                "building_name": f.floor.block.building.name if f.floor else None,
                "previous_reading": latest.get(f.id, (None, None))[0],
                "last_reading_date": latest.get(f.id, (None, None))[1],
            }
            for f in flats
        ]

    # -- writes ------------------------------------------------------------- #

    async def create(
        self,
        payload: WaterReadingCreate | ElectricityReadingCreate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if await FlatRepository(self.tenant).get(payload.flat_id) is None:
            raise NotFoundError("Flat")
        if await self.repo.exists_for(payload.flat_id, payload.reading_date):
            raise AlreadyExistsError(
                f"A reading for this flat on {payload.reading_date:%d %b %Y} already "
                "exists. Edit it instead of adding a second one."
            )

        data = payload.model_dump()
        if data.get("previous_reading") is None:
            # Carry the last closing value forward so a reader only enters one
            # number and the series stays continuous.
            last = await self.repo.latest_for_flat(payload.flat_id)
            if last is not None:
                data["previous_reading"] = last.current_reading
                if payload.current_reading < last.current_reading:
                    raise ValidationError(
                        f"The reading {payload.current_reading} is below the last "
                        f"recorded value {last.current_reading}. Check the entry, or "
                        "record the meter replacement in remarks."
                    )

        reading = self.model(**data, recorded_by=principal.tenant_user_id)
        await self.repo.create(reading)
        await self.tenant.refresh(reading)  # pick up the generated consumption

        await AuditService.tenant(
            self.tenant,
            action=getattr(AuditAction, f"{self.utility.upper()}_READING_CREATED"),
            principal=principal,
            target_type=self.model.__tablename__,
            target_id=reading.id,
            changes={"after": {k: str(v) for k, v in data.items()}},
            request_id=request_id,
        )
        return _reading_dict(reading)

    async def bulk_create(
        self,
        payload: BulkReadingCreate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        flat_ids = [r.flat_id for r in payload.rows]
        known = {
            f.id
            for f in await self.tenant.scalars(
                select(Flat).where(Flat.id.in_(flat_ids), Flat.is_active.is_(True))
            )
        }
        unknown = [fid for fid in flat_ids if fid not in known]
        if unknown:
            raise ValidationError(
                f"{len(unknown)} of the flats in this batch do not exist in this society."
            )

        existing = {
            r.flat_id
            for r in await self.tenant.scalars(
                select(self.model).where(
                    self.model.flat_id.in_(flat_ids),
                    self.model.reading_date == payload.reading_date,
                )
            )
        }
        if existing and not payload.skip_existing:
            raise ConflictError(
                f"{len(existing)} flats already have a reading dated "
                f"{payload.reading_date:%d %b %Y}."
            )

        previous = await self.repo.latest_bulk(flat_ids)
        readings: list[Any] = []
        for row in payload.rows:
            if row.flat_id in existing:
                continue
            opening = row.previous_reading
            if opening is None:
                found = previous.get(row.flat_id)
                opening = found[0] if found else None
            if opening is not None and row.current_reading < opening:
                raise ValidationError(
                    f"A reading in this batch ({row.current_reading}) is below the "
                    f"flat's last recorded value ({opening}). No readings were saved."
                )
            values: dict[str, Any] = {
                "flat_id": row.flat_id,
                "reading_date": payload.reading_date,
                "period_key": payload.period_key,
                "previous_reading": opening,
                "current_reading": row.current_reading,
                "meter_number": row.meter_number,
                "recorded_by": principal.tenant_user_id,
            }
            if self.utility == "electricity" and row.amount is not None:
                values["amount"] = row.amount
            readings.append(self.model(**values))

        if readings:
            await self.repo.create_many(readings)

        await AuditService.tenant(
            self.tenant,
            action=getattr(AuditAction, f"{self.utility.upper()}_READINGS_BULK_CREATED"),
            principal=principal,
            target_type=self.model.__tablename__,
            changes={
                "after": {
                    "reading_date": str(payload.reading_date),
                    "created": len(readings),
                    "skipped": len(existing),
                }
            },
            request_id=request_id,
        )
        return {
            "created": len(readings),
            "skipped": len(existing),
            "skipped_flat_ids": sorted(existing, key=str),
        }

    async def update(
        self,
        reading_id: uuid.UUID,
        payload: ReadingUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        reading = await self.repo.get(reading_id)
        if reading is None:
            raise NotFoundError(self._resource)

        before = _reading_dict(reading)
        changes = payload.model_dump(exclude_unset=True)
        if self.utility == "water":
            changes.pop("amount", None)

        for key, value in changes.items():
            setattr(reading, key, value)

        current = reading.current_reading
        opening = reading.previous_reading
        if opening is not None and current < opening:
            raise ValidationError(
                "The corrected reading is below the opening value for the period."
            )

        await self.tenant.flush()
        await self.tenant.refresh(reading)

        await AuditService.tenant(
            self.tenant,
            action=getattr(AuditAction, f"{self.utility.upper()}_READING_UPDATED"),
            principal=principal,
            target_type=self.model.__tablename__,
            target_id=reading.id,
            changes=diff(
                {k: str(v) for k, v in before.items()},
                {k: str(v) for k, v in _reading_dict(reading).items()},
            ),
            request_id=request_id,
        )
        return _reading_dict(reading)

    async def delete(
        self, reading_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        reading = await self.repo.get(reading_id)
        if reading is None:
            raise NotFoundError(self._resource)
        snapshot = {k: str(v) for k, v in _reading_dict(reading).items()}
        await self.tenant.delete(reading)
        await self.tenant.flush()
        await AuditService.tenant(
            self.tenant,
            action=getattr(AuditAction, f"{self.utility.upper()}_READING_DELETED"),
            principal=principal,
            target_type=self.model.__tablename__,
            target_id=reading_id,
            changes={"before": snapshot},
            request_id=request_id,
        )


# --------------------------------------------------------------------------- #
# Parking
# --------------------------------------------------------------------------- #


def _slot_dict(s: ParkingSlot) -> dict[str, Any]:
    return {
        "id": s.id,
        "slot_number": s.slot_number,
        "building_id": s.building_id,
        "level": s.level,
        "slot_type": s.slot_type,
        "monthly_charge": s.monthly_charge,
        "flat_id": s.flat_id,
        "flat_number": _flat_number(s),
        "notes": s.notes,
        "is_active": s.is_active,
        "created_at": s.created_at,
    }


class ParkingService:
    """Slots are a shared society resource, so allotment is an admin action even
    though the vehicle standing in one belongs to a resident."""

    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = ParkingRepository(tenant)

    def _owner_scope(self, principal: Principal) -> list[uuid.UUID] | None:
        if principal.is_scoped_to_own(Permission.PARKING_READ):
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
        unallotted_only: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.repo.list(
            page=page,
            limit=limit,
            q=q,
            flat_id=flat_id,
            unallotted_only=unallotted_only,
            only_flat_ids=self._owner_scope(principal),
        )
        return [_slot_dict(s) for s in rows], total

    async def summary(self) -> dict[str, int]:
        return await self.repo.summary()

    async def create(
        self, payload: ParkingSlotCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        if await self.repo.get_by_number(payload.slot_number):
            raise AlreadyExistsError(f"Slot '{payload.slot_number}' already exists.")
        if payload.flat_id is not None:
            if await FlatRepository(self.tenant).get(payload.flat_id) is None:
                raise NotFoundError("Flat")

        slot = ParkingSlot(**payload.model_dump())
        await self.repo.create(slot)
        await self.tenant.refresh(slot)
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.PARKING_SLOT_CREATED,
            principal=principal,
            target_type="parking_slots",
            target_id=slot.id,
            changes={"after": {"slot_number": slot.slot_number}},
            request_id=request_id,
        )
        return _slot_dict(slot)

    async def update(
        self,
        slot_id: uuid.UUID,
        payload: ParkingSlotUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        slot = await self.repo.get(slot_id)
        if slot is None:
            raise NotFoundError("Parking slot")
        before = _slot_dict(slot)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(slot, key, value)
        await self.tenant.flush()
        await self.tenant.refresh(slot)
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.PARKING_SLOT_UPDATED,
            principal=principal,
            target_type="parking_slots",
            target_id=slot.id,
            changes=diff(
                {k: str(v) for k, v in before.items()},
                {k: str(v) for k, v in _slot_dict(slot).items()},
            ),
            request_id=request_id,
        )
        return _slot_dict(slot)

    async def allot(
        self,
        slot_id: uuid.UUID,
        payload: ParkingAllotment,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        slot = await self.repo.get(slot_id)
        if slot is None:
            raise NotFoundError("Parking slot")
        if payload.flat_id is not None:
            if await FlatRepository(self.tenant).get(payload.flat_id) is None:
                raise NotFoundError("Flat")
            if slot.flat_id is not None and slot.flat_id != payload.flat_id:
                raise ConflictError(
                    f"Slot {slot.slot_number} is already allotted. Release it first."
                )

        previous = slot.flat_id
        slot.flat_id = payload.flat_id

        if payload.flat_id is None:
            # A released slot must not leave a vehicle pointing at it.
            for vehicle in await self.tenant.scalars(
                select(Vehicle).where(Vehicle.parking_slot_id == slot.id)
            ):
                vehicle.parking_slot_id = None

        await self.tenant.flush()
        await self.tenant.refresh(slot)
        await AuditService.tenant(
            self.tenant,
            action=(
                AuditAction.PARKING_SLOT_RELEASED
                if payload.flat_id is None
                else AuditAction.PARKING_SLOT_ALLOTTED
            ),
            principal=principal,
            target_type="parking_slots",
            target_id=slot.id,
            changes={
                "before": {"flat_id": str(previous) if previous else None},
                "after": {"flat_id": str(payload.flat_id) if payload.flat_id else None},
            },
            request_id=request_id,
        )
        return _slot_dict(slot)


# --------------------------------------------------------------------------- #
# Vehicles
# --------------------------------------------------------------------------- #


def _vehicle_dict(v: Vehicle) -> dict[str, Any]:
    slot = v.parking_slot
    return {
        "id": v.id,
        "flat_id": v.flat_id,
        "flat_number": _flat_number(v),
        "registration_number": v.registration_number,
        "vehicle_type": v.vehicle_type,
        "make": v.make,
        "model": v.model,
        "color": v.color,
        "parking_slot_id": v.parking_slot_id,
        "parking_slot_number": slot.slot_number if slot else None,
        "is_active": v.is_active,
        "created_at": v.created_at,
    }


class VehicleService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = VehicleRepository(tenant)

    def _owner_scope(self, principal: Principal) -> list[uuid.UUID] | None:
        if principal.is_scoped_to_own(Permission.VEHICLE_READ):
            return sorted(principal.flat_ids)
        return None

    def _assert_owns(self, flat_id: uuid.UUID, principal: Principal) -> None:
        """A resident may register a vehicle, but only against their own flat."""
        if principal.is_scoped_to_own(Permission.VEHICLE_MANAGE) and not principal.owns_flat(
            flat_id
        ):
            raise NotFoundError("Flat")

    async def list(
        self,
        principal: Principal,
        *,
        page: int,
        limit: int,
        q: str | None = None,
        flat_id: uuid.UUID | None = None,
        vehicle_type: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.repo.list(
            page=page,
            limit=limit,
            q=q,
            flat_id=flat_id,
            vehicle_type=vehicle_type,
            only_flat_ids=self._owner_scope(principal),
        )
        return [_vehicle_dict(v) for v in rows], total

    async def get(self, vehicle_id: uuid.UUID, principal: Principal) -> dict[str, Any]:
        vehicle = await self.repo.get(vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle")
        scope = self._owner_scope(principal)
        if scope is not None and vehicle.flat_id not in scope:
            raise NotFoundError("Vehicle")
        return _vehicle_dict(vehicle)

    async def create(
        self, payload: VehicleCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        self._assert_owns(payload.flat_id, principal)
        if await FlatRepository(self.tenant).get(payload.flat_id) is None:
            raise NotFoundError("Flat")

        clash = await self.repo.get_by_registration(payload.registration_number)
        if clash is not None:
            raise AlreadyExistsError(
                f"Vehicle {payload.registration_number} is already registered in this "
                "society. If it has changed hands, remove the old registration first."
            )
        if payload.parking_slot_id is not None:
            await self._assert_slot_usable(payload.parking_slot_id, payload.flat_id)

        vehicle = Vehicle(**payload.model_dump())
        await self.repo.create(vehicle)
        await self.tenant.refresh(vehicle)
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.VEHICLE_CREATED,
            principal=principal,
            target_type="vehicles",
            target_id=vehicle.id,
            changes={"after": {"registration_number": vehicle.registration_number}},
            request_id=request_id,
        )
        return _vehicle_dict(vehicle)

    async def _assert_slot_usable(self, slot_id: uuid.UUID, flat_id: uuid.UUID) -> None:
        slot = await ParkingRepository(self.tenant).get(slot_id)
        if slot is None or not slot.is_active:
            raise NotFoundError("Parking slot")
        if slot.flat_id is not None and slot.flat_id != flat_id:
            raise ConflictError(
                f"Slot {slot.slot_number} is allotted to a different flat."
            )

    async def update(
        self,
        vehicle_id: uuid.UUID,
        payload: VehicleUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        vehicle = await self.repo.get(vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle")
        self._assert_owns(vehicle.flat_id, principal)

        before = _vehicle_dict(vehicle)
        changes = payload.model_dump(exclude_unset=True)
        if changes.get("parking_slot_id") is not None:
            await self._assert_slot_usable(changes["parking_slot_id"], vehicle.flat_id)
        for key, value in changes.items():
            setattr(vehicle, key, value)
        await self.tenant.flush()
        await self.tenant.refresh(vehicle)
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.VEHICLE_UPDATED,
            principal=principal,
            target_type="vehicles",
            target_id=vehicle.id,
            changes=diff(
                {k: str(v) for k, v in before.items()},
                {k: str(v) for k, v in _vehicle_dict(vehicle).items()},
            ),
            request_id=request_id,
        )
        return _vehicle_dict(vehicle)

    async def remove(
        self, vehicle_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        """Deactivated rather than deleted — a gate log referencing this plate
        must still resolve to the flat it belonged to at the time."""
        vehicle = await self.repo.get(vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle")
        self._assert_owns(vehicle.flat_id, principal)
        vehicle.is_active = False
        vehicle.parking_slot_id = None
        await self.tenant.flush()
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.VEHICLE_REMOVED,
            principal=principal,
            target_type="vehicles",
            target_id=vehicle_id,
            changes={"before": {"registration_number": vehicle.registration_number}},
            request_id=request_id,
        )


# --------------------------------------------------------------------------- #
# Pets
# --------------------------------------------------------------------------- #


def _pet_dict(p: Pet) -> dict[str, Any]:
    return {
        "id": p.id,
        "flat_id": p.flat_id,
        "flat_number": _flat_number(p),
        "name": p.name,
        "pet_type": p.pet_type,
        "breed": p.breed,
        "registration_number": p.registration_number,
        "vaccination_expiry": p.vaccination_expiry,
        "vaccination_due": (
            p.vaccination_expiry is not None and p.vaccination_expiry <= date.today()
        ),
        "monthly_fee": p.monthly_fee,
        "is_active": p.is_active,
        "created_at": p.created_at,
    }


class PetService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = PetRepository(tenant)

    def _owner_scope(self, principal: Principal) -> list[uuid.UUID] | None:
        if principal.is_scoped_to_own(Permission.PET_READ):
            return sorted(principal.flat_ids)
        return None

    def _assert_owns(self, flat_id: uuid.UUID, principal: Principal) -> None:
        if principal.is_scoped_to_own(Permission.PET_MANAGE) and not principal.owns_flat(
            flat_id
        ):
            raise NotFoundError("Flat")

    async def list(
        self,
        principal: Principal,
        *,
        page: int,
        limit: int,
        q: str | None = None,
        flat_id: uuid.UUID | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.repo.list(
            page=page, limit=limit, q=q, flat_id=flat_id, only_flat_ids=self._owner_scope(principal)
        )
        return [_pet_dict(p) for p in rows], total

    async def create(
        self, payload: PetCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        self._assert_owns(payload.flat_id, principal)
        if await FlatRepository(self.tenant).get(payload.flat_id) is None:
            raise NotFoundError("Flat")
        pet = Pet(**payload.model_dump())
        await self.repo.create(pet)
        await self.tenant.refresh(pet)
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.PET_CREATED,
            principal=principal,
            target_type="pets",
            target_id=pet.id,
            changes={"after": {"name": pet.name, "pet_type": str(pet.pet_type)}},
            request_id=request_id,
        )
        return _pet_dict(pet)

    async def update(
        self,
        pet_id: uuid.UUID,
        payload: PetUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        pet = await self.repo.get(pet_id)
        if pet is None:
            raise NotFoundError("Pet")
        self._assert_owns(pet.flat_id, principal)
        before = _pet_dict(pet)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(pet, key, value)
        await self.tenant.flush()
        await self.tenant.refresh(pet)
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.PET_UPDATED,
            principal=principal,
            target_type="pets",
            target_id=pet.id,
            changes=diff(
                {k: str(v) for k, v in before.items()},
                {k: str(v) for k, v in _pet_dict(pet).items()},
            ),
            request_id=request_id,
        )
        return _pet_dict(pet)

    async def remove(
        self, pet_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        pet = await self.repo.get(pet_id)
        if pet is None:
            raise NotFoundError("Pet")
        self._assert_owns(pet.flat_id, principal)
        pet.is_active = False
        await self.tenant.flush()
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.PET_REMOVED,
            principal=principal,
            target_type="pets",
            target_id=pet_id,
            changes={"before": {"name": pet.name}},
            request_id=request_id,
        )
