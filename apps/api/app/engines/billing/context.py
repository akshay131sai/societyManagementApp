"""Building the evaluation context for a billing run.

The performance-critical part of billing. Inputs are loaded **per run**, not
per flat: a 500-flat run issues a handful of queries, not two thousand.

Every loader here returns a ``dict[flat_id, value]``, and
``BillingContextBuilder`` assembles one ``EvaluationContext`` per flat from
those maps. Adding a billing input means adding one loader and one line in
``build`` — never a special case in the evaluator.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.billing.periods import BillingPeriod
from app.engines.formula import EvaluationContext
from app.models.tenant import (
    Block,
    Flat,
    Floor,
    OccupancyStatus,
    Resident,
)

ZERO = Decimal(0)


@dataclass(slots=True)
class FlatInputs:
    """Everything one flat contributes to a formula."""

    flat: Flat
    floor_number: int = 0
    resident_count: int = 0
    water_consumption: Decimal = ZERO
    water_previous: Decimal = ZERO
    water_current: Decimal = ZERO
    electricity_units: Decimal = ZERO
    electricity_amount: Decimal = ZERO
    parking_slot_count: int = 0
    parking_charge_total: Decimal = ZERO
    vehicle_count: int = 0
    two_wheeler_count: int = 0
    four_wheeler_count: int = 0
    pet_count: int = 0
    pet_fee_total: Decimal = ZERO
    outstanding_balance: Decimal = ZERO
    days_overdue: int = 0

    def as_values(self, period: BillingPeriod, base_maintenance: Decimal) -> dict[str, Any]:
        return {
            "flat_area": self.flat.area_sqft,
            "carpet_area": self.flat.carpet_area_sqft or ZERO,
            "floor_number": Decimal(self.floor_number),
            "flat_type": self.flat.flat_type or "",
            "occupancy_status": self.flat.occupancy_status.value,
            "is_vacant": self.flat.occupancy_status is OccupancyStatus.VACANT,
            "is_rented": self.flat.occupancy_status is OccupancyStatus.RENTED,
            # A per-flat override beats the template's parameter, which is the
            # whole point of having the column.
            "base_maintenance": (
                self.flat.base_maintenance_override
                if self.flat.base_maintenance_override is not None
                else base_maintenance
            ),
            "water_consumption": self.water_consumption,
            "water_previous": self.water_previous,
            "water_current": self.water_current,
            "electricity_units": self.electricity_units,
            "electricity_amount": self.electricity_amount,
            "parking_slot_count": Decimal(self.parking_slot_count),
            "parking_charge_total": self.parking_charge_total,
            "vehicle_count": Decimal(self.vehicle_count),
            "two_wheeler_count": Decimal(self.two_wheeler_count),
            "four_wheeler_count": Decimal(self.four_wheeler_count),
            "pet_count": Decimal(self.pet_count),
            "pet_fee_total": self.pet_fee_total,
            "resident_count": Decimal(self.resident_count),
            "outstanding_balance": self.outstanding_balance,
            "days_overdue": Decimal(self.days_overdue),
            "period_months": Decimal(period.months),
        }


@dataclass(slots=True)
class BillingInputs:
    """All flats' inputs for one run, loaded in bulk."""

    period: BillingPeriod
    parameters: dict[str, Any] = field(default_factory=dict)
    flats: dict[uuid.UUID, FlatInputs] = field(default_factory=dict)

    def context_for(self, flat_id: uuid.UUID) -> EvaluationContext:
        inputs = self.flats[flat_id]
        base = Decimal(str(self.parameters.get("base_maintenance", 0)))
        return EvaluationContext(
            values=inputs.as_values(self.period, base),
            parameters=self.parameters,
        )


class BillingContextBuilder:
    """Loads every input a run needs, in bulk.

    Utility and asset tables arrive in Phase 4; until they exist the loaders
    return empty maps and the corresponding fields bill as zero. That is the
    honest answer for "no reading recorded" and keeps a formula that references
    water from failing before the meters are wired up.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(
        self,
        flats: list[Flat],
        period: BillingPeriod,
        parameters: dict[str, Any],
    ) -> BillingInputs:
        flat_ids = [f.id for f in flats]
        inputs = BillingInputs(period=period, parameters=dict(parameters))

        floor_numbers = await self._floor_numbers(flat_ids)
        resident_counts = await self._resident_counts(flat_ids)
        water = await self._water(flat_ids, period)
        electricity = await self._electricity(flat_ids, period)
        parking = await self._parking(flat_ids)
        vehicles = await self._vehicles(flat_ids)
        pets = await self._pets(flat_ids)
        outstanding = await self._outstanding(period)
        overdue = await self._overdue(period)

        for flat in flats:
            w = water.get(flat.id, (ZERO, ZERO, ZERO))
            e = electricity.get(flat.id, (ZERO, ZERO))
            p = parking.get(flat.id, (0, ZERO))
            v = vehicles.get(flat.id, (0, 0, 0))
            pet = pets.get(flat.id, (0, ZERO))

            inputs.flats[flat.id] = FlatInputs(
                flat=flat,
                floor_number=floor_numbers.get(flat.id, 0),
                resident_count=resident_counts.get(flat.id, 0),
                water_consumption=w[0],
                water_previous=w[1],
                water_current=w[2],
                electricity_units=e[0],
                electricity_amount=e[1],
                parking_slot_count=p[0],
                parking_charge_total=p[1],
                vehicle_count=v[0],
                two_wheeler_count=v[1],
                four_wheeler_count=v[2],
                pet_count=pet[0],
                pet_fee_total=pet[1],
                outstanding_balance=outstanding.get(flat.id, ZERO),
                days_overdue=overdue.get(flat.id, 0),
            )

        return inputs

    # ------------------------------------------------------------------ #

    async def _floor_numbers(self, flat_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not flat_ids:
            return {}
        rows = await self.session.execute(
            select(Flat.id, Floor.number)
            .join(Floor, Floor.id == Flat.floor_id)
            .where(Flat.id.in_(flat_ids))
        )
        return {k: int(v) for k, v in rows}

    async def _resident_counts(self, flat_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not flat_ids:
            return {}
        rows = await self.session.execute(
            select(Resident.flat_id, func.count())
            .where(Resident.flat_id.in_(flat_ids), Resident.is_active.is_(True))
            .group_by(Resident.flat_id)
        )
        return {k: int(v) for k, v in rows}

    async def _table_exists(self, name: str) -> bool:
        from sqlalchemy import inspect

        conn = await self.session.connection()
        return await conn.run_sync(lambda c: inspect(c).has_table(name))

    async def _water(
        self, flat_ids: list[uuid.UUID], period: BillingPeriod
    ) -> dict[uuid.UUID, tuple[Decimal, Decimal, Decimal]]:
        if not flat_ids or not await self._table_exists("water_readings"):
            return {}
        from app.models.tenant.utilities import WaterReading

        rows = await self.session.execute(
            select(
                WaterReading.flat_id,
                func.sum(WaterReading.consumption),
                func.min(WaterReading.previous_reading),
                func.max(WaterReading.current_reading),
            )
            .where(
                WaterReading.flat_id.in_(flat_ids),
                WaterReading.reading_date >= period.start,
                WaterReading.reading_date <= period.end,
            )
            .group_by(WaterReading.flat_id)
        )
        return {
            k: (Decimal(str(c or 0)), Decimal(str(p or 0)), Decimal(str(cur or 0)))
            for k, c, p, cur in rows
        }

    async def _electricity(
        self, flat_ids: list[uuid.UUID], period: BillingPeriod
    ) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
        if not flat_ids or not await self._table_exists("electricity_readings"):
            return {}
        from app.models.tenant.utilities import ElectricityReading

        rows = await self.session.execute(
            select(
                ElectricityReading.flat_id,
                func.sum(ElectricityReading.consumption),
                func.sum(ElectricityReading.amount),
            )
            .where(
                ElectricityReading.flat_id.in_(flat_ids),
                ElectricityReading.reading_date >= period.start,
                ElectricityReading.reading_date <= period.end,
            )
            .group_by(ElectricityReading.flat_id)
        )
        return {k: (Decimal(str(u or 0)), Decimal(str(a or 0))) for k, u, a in rows}

    async def _parking(
        self, flat_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[int, Decimal]]:
        if not flat_ids or not await self._table_exists("parking_slots"):
            return {}
        from app.models.tenant.assets import ParkingSlot

        rows = await self.session.execute(
            select(
                ParkingSlot.flat_id,
                func.count(),
                func.coalesce(func.sum(ParkingSlot.monthly_charge), 0),
            )
            .where(ParkingSlot.flat_id.in_(flat_ids), ParkingSlot.is_active.is_(True))
            .group_by(ParkingSlot.flat_id)
        )
        return {k: (int(n), Decimal(str(total or 0))) for k, n, total in rows}

    async def _vehicles(
        self, flat_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[int, int, int]]:
        if not flat_ids or not await self._table_exists("vehicles"):
            return {}
        from app.models.tenant.assets import Vehicle, VehicleType

        rows = await self.session.execute(
            select(Vehicle.flat_id, Vehicle.vehicle_type, func.count())
            .where(Vehicle.flat_id.in_(flat_ids), Vehicle.is_active.is_(True))
            .group_by(Vehicle.flat_id, Vehicle.vehicle_type)
        )
        result: dict[uuid.UUID, list[int]] = {}
        for flat_id, kind, count in rows:
            bucket = result.setdefault(flat_id, [0, 0, 0])
            bucket[0] += int(count)
            if kind is VehicleType.TWO_WHEELER:
                bucket[1] += int(count)
            elif kind is VehicleType.FOUR_WHEELER:
                bucket[2] += int(count)
        return {k: (v[0], v[1], v[2]) for k, v in result.items()}

    async def _pets(self, flat_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, Decimal]]:
        if not flat_ids or not await self._table_exists("pets"):
            return {}
        from app.models.tenant.assets import Pet

        rows = await self.session.execute(
            select(Pet.flat_id, func.count(), func.coalesce(func.sum(Pet.monthly_fee), 0))
            .where(Pet.flat_id.in_(flat_ids), Pet.is_active.is_(True))
            .group_by(Pet.flat_id)
        )
        return {k: (int(n), Decimal(str(fee or 0))) for k, n, fee in rows}

    async def _outstanding(self, period: BillingPeriod) -> dict[uuid.UUID, Decimal]:
        from app.repositories.billing import BillRepository

        return await BillRepository(self.session).outstanding_bulk(period.start)

    async def _overdue(self, period: BillingPeriod) -> dict[uuid.UUID, int]:
        from app.repositories.billing import BillRepository

        return await BillRepository(self.session).oldest_overdue_bulk(period.start)
