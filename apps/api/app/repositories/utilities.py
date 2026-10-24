"""Utility reading and asset repositories."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tenant import (
    ElectricityReading,
    Flat,
    ParkingSlot,
    Pet,
    Vehicle,
    VehicleType,
    WaterReading,
)

ReadingModel = type[WaterReading] | type[ElectricityReading]


async def _count(session: AsyncSession, stmt: Select) -> int:
    subq = stmt.order_by(None).subquery()
    return int(await session.scalar(select(func.count()).select_from(subq)) or 0)


class ReadingRepository:
    """Shared across water and electricity — the shapes are identical."""

    def __init__(self, session: AsyncSession, model: ReadingModel) -> None:
        self.session = session
        self.model = model

    async def get(self, reading_id: uuid.UUID) -> Any:
        return await self.session.get(self.model, reading_id)

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        flat_id: uuid.UUID | None = None,
        period_key: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        only_flat_ids: Sequence[uuid.UUID] | None = None,
    ) -> tuple[Sequence[Any], int]:
        stmt = select(self.model).options(selectinload(self.model.flat))
        if flat_id is not None:
            stmt = stmt.where(self.model.flat_id == flat_id)
        if period_key:
            stmt = stmt.where(self.model.period_key == period_key)
        if from_date:
            stmt = stmt.where(self.model.reading_date >= from_date)
        if to_date:
            stmt = stmt.where(self.model.reading_date <= to_date)
        if only_flat_ids is not None:
            stmt = stmt.where(
                self.model.flat_id.in_(list(only_flat_ids)) if only_flat_ids else False
            )

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(self.model.reading_date.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total

    async def latest_for_flat(self, flat_id: uuid.UUID) -> Any:
        """The most recent reading, used to prefill the next one's opening value."""
        return await self.session.scalar(
            select(self.model)
            .where(self.model.flat_id == flat_id)
            .order_by(self.model.reading_date.desc())
            .limit(1)
        )

    async def latest_bulk(
        self, flat_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[Decimal, date]]:
        """Latest closing reading and its date per flat, in one query.

        The bulk entry screen needs both: the value to prefill, and the date so
        a reader can see which flats are overdue for a round.
        """
        if not flat_ids:
            return {}
        newest = (
            select(
                self.model.flat_id,
                func.max(self.model.reading_date).label("latest"),
            )
            .where(self.model.flat_id.in_(list(flat_ids)))
            .group_by(self.model.flat_id)
            .subquery()
        )
        rows = await self.session.execute(
            select(
                self.model.flat_id, self.model.current_reading, self.model.reading_date
            ).join(
                newest,
                (self.model.flat_id == newest.c.flat_id)
                & (self.model.reading_date == newest.c.latest),
            )
        )
        return {k: (Decimal(str(v)), d) for k, v, d in rows}

    async def exists_for(self, flat_id: uuid.UUID, reading_date: date) -> bool:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(self.model)
                .where(
                    self.model.flat_id == flat_id,
                    self.model.reading_date == reading_date,
                )
            )
        ) > 0

    async def create(self, reading: Any) -> Any:
        self.session.add(reading)
        await self.session.flush()
        return reading

    async def create_many(self, readings: Sequence[Any]) -> None:
        self.session.add_all(list(readings))
        await self.session.flush()

    async def history(
        self, flat_id: uuid.UUID, limit: int = 12
    ) -> Sequence[Any]:
        """Recent readings, oldest first — the shape a chart wants."""
        rows = await self.session.scalars(
            select(self.model)
            .where(self.model.flat_id == flat_id)
            .order_by(self.model.reading_date.desc())
            .limit(limit)
        )
        return list(reversed(list(rows)))

    async def society_totals(
        self, from_date: date | None = None
    ) -> list[tuple[date, Decimal]]:
        """Consumption per reading date across the society, for the admin chart.

        Opening readings are excluded. ``consumption`` is generated as
        ``current_reading - COALESCE(previous_reading, 0)``, so a meter's very
        first reading reports its whole cumulative face value as if it had all
        been used in one period. Summed across every flat that dwarfs the real
        rounds by orders of magnitude and makes the society total unreadable.

        A round with no prior reading has no consumption *period*, so it is not
        a data point. The reading itself is untouched and still listed.
        """
        stmt = (
            select(self.model.reading_date, func.sum(self.model.consumption))
            .where(self.model.previous_reading.is_not(None))
            .group_by(self.model.reading_date)
        )
        if from_date:
            stmt = stmt.where(self.model.reading_date >= from_date)
        rows = await self.session.execute(stmt.order_by(self.model.reading_date))
        return [(d, Decimal(str(c or 0))) for d, c in rows]

    async def stats_for_flat(self, flat_id: uuid.UUID) -> dict[str, Any]:
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.coalesce(func.avg(self.model.consumption), 0),
                    func.coalesce(func.max(self.model.consumption), 0),
                    func.coalesce(func.min(self.model.consumption), 0),
                    func.coalesce(func.sum(self.model.consumption), 0),
                ).where(self.model.flat_id == flat_id)
            )
        ).first()
        count, avg, high, low, total = row or (0, 0, 0, 0, 0)
        return {
            "readings": int(count),
            "average": Decimal(str(avg)).quantize(Decimal("0.001")),
            "highest": Decimal(str(high)),
            "lowest": Decimal(str(low)),
            "total": Decimal(str(total)),
        }


class ParkingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, slot_id: uuid.UUID) -> ParkingSlot | None:
        return await self.session.get(ParkingSlot, slot_id)

    async def get_by_number(self, slot_number: str) -> ParkingSlot | None:
        return await self.session.scalar(
            select(ParkingSlot).where(
                func.upper(ParkingSlot.slot_number) == slot_number.upper()
            )
        )

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        flat_id: uuid.UUID | None = None,
        unallotted_only: bool = False,
        only_flat_ids: Sequence[uuid.UUID] | None = None,
    ) -> tuple[Sequence[ParkingSlot], int]:
        stmt = select(ParkingSlot).options(selectinload(ParkingSlot.flat))
        stmt = stmt.where(ParkingSlot.is_active.is_(True))
        if q:
            stmt = stmt.where(func.lower(ParkingSlot.slot_number).like(f"%{q.lower()}%"))
        if flat_id is not None:
            stmt = stmt.where(ParkingSlot.flat_id == flat_id)
        if unallotted_only:
            stmt = stmt.where(ParkingSlot.flat_id.is_(None))
        if only_flat_ids is not None:
            stmt = stmt.where(
                ParkingSlot.flat_id.in_(list(only_flat_ids)) if only_flat_ids else False
            )

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(ParkingSlot.slot_number).offset((page - 1) * limit).limit(limit)
        )
        return list(rows), total

    async def create(self, slot: ParkingSlot) -> ParkingSlot:
        self.session.add(slot)
        await self.session.flush()
        return slot

    async def summary(self) -> dict[str, int]:
        rows = await self.session.execute(
            select(
                func.count(),
                func.count(ParkingSlot.flat_id),
            ).where(ParkingSlot.is_active.is_(True))
        )
        total, allotted = rows.first() or (0, 0)
        return {
            "total": int(total),
            "allotted": int(allotted),
            "available": int(total) - int(allotted),
        }


class VehicleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, vehicle_id: uuid.UUID) -> Vehicle | None:
        return await self.session.get(Vehicle, vehicle_id)

    async def get_by_registration(self, registration: str) -> Vehicle | None:
        return await self.session.scalar(
            select(Vehicle).where(
                func.upper(Vehicle.registration_number) == registration.upper(),
                Vehicle.is_active.is_(True),
            )
        )

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        flat_id: uuid.UUID | None = None,
        vehicle_type: str | None = None,
        only_flat_ids: Sequence[uuid.UUID] | None = None,
    ) -> tuple[Sequence[Vehicle], int]:
        stmt = (
            select(Vehicle)
            .options(selectinload(Vehicle.flat), selectinload(Vehicle.parking_slot))
            .where(Vehicle.is_active.is_(True))
        )
        if q:
            stmt = stmt.where(
                func.lower(Vehicle.registration_number).like(f"%{q.lower()}%")
            )
        if flat_id is not None:
            stmt = stmt.where(Vehicle.flat_id == flat_id)
        if vehicle_type:
            stmt = stmt.where(Vehicle.vehicle_type == vehicle_type)
        if only_flat_ids is not None:
            stmt = stmt.where(
                Vehicle.flat_id.in_(list(only_flat_ids)) if only_flat_ids else False
            )

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(Vehicle.registration_number).offset((page - 1) * limit).limit(limit)
        )
        return list(rows), total

    async def create(self, vehicle: Vehicle) -> Vehicle:
        self.session.add(vehicle)
        await self.session.flush()
        return vehicle

    async def counts_by_type(self) -> dict[str, int]:
        rows = await self.session.execute(
            select(Vehicle.vehicle_type, func.count())
            .where(Vehicle.is_active.is_(True))
            .group_by(Vehicle.vehicle_type)
        )
        return {str(t.value): int(c) for t, c in rows}


class PetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, pet_id: uuid.UUID) -> Pet | None:
        return await self.session.get(Pet, pet_id)

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        flat_id: uuid.UUID | None = None,
        only_flat_ids: Sequence[uuid.UUID] | None = None,
    ) -> tuple[Sequence[Pet], int]:
        stmt = select(Pet).options(selectinload(Pet.flat)).where(Pet.is_active.is_(True))
        if q:
            stmt = stmt.where(func.lower(Pet.name).like(f"%{q.lower()}%"))
        if flat_id is not None:
            stmt = stmt.where(Pet.flat_id == flat_id)
        if only_flat_ids is not None:
            stmt = stmt.where(Pet.flat_id.in_(list(only_flat_ids)) if only_flat_ids else False)

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(Pet.name).offset((page - 1) * limit).limit(limit)
        )
        return list(rows), total

    async def create(self, pet: Pet) -> Pet:
        self.session.add(pet)
        await self.session.flush()
        return pet

    async def count(self) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).select_from(Pet).where(Pet.is_active.is_(True))
            )
            or 0
        )


class FlatLookupRepository:
    """Flats with their latest readings — the bulk meter-entry screen."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def all_active(self, limit: int = 2000) -> Sequence[Flat]:
        rows = await self.session.scalars(
            select(Flat).where(Flat.is_active.is_(True)).order_by(Flat.flat_number).limit(limit)
        )
        return list(rows)
