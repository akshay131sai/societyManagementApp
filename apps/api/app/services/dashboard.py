"""The resident dashboard.

One endpoint assembles the whole screen. A phone on a lift-lobby connection
should not make eight round trips to render a home page, and the numbers on it
(outstanding, next due, charge mix) must agree with each other — which they can
only be relied on to do if they were read in one transaction.

Nothing here is society-wide: every query is filtered to
``principal.flat_ids``, which was resolved server-side from the tenant
database, never from the request.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.principal import Principal
from app.models.tenant import (
    BillLineItem,
    BillStatus,
    Block,
    ElectricityReading,
    Flat,
    Floor,
    MaintenanceBill,
    ParkingSlot,
    Payment,
    PaymentStatus,
    Pet,
    Vehicle,
    WaterReading,
)
from app.services.utilities import ReadingService

log = structlog.get_logger(__name__)

ZERO = Decimal("0")


def _bill_dict(bill: MaintenanceBill, today: date) -> dict[str, Any]:
    balance = bill.total - bill.amount_paid
    return {
        "id": bill.id,
        "bill_number": bill.bill_number,
        "period_label": bill.period_label,
        "total_amount": bill.total,
        "amount_paid": bill.amount_paid,
        "balance": balance,
        "due_date": bill.due_date,
        "status": str(bill.payment_status),
        "is_overdue": balance > ZERO and bill.due_date < today,
        "days_until_due": (bill.due_date - today).days,
    }


class ResidentDashboardService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant

    async def build(self, principal: Principal) -> dict[str, Any]:
        today = date.today()
        flat_ids = sorted(principal.flat_ids)

        if not flat_ids:
            # A committee member with no flat of their own still gets a valid,
            # empty dashboard rather than an error.
            return {
                "flats": [],
                "outstanding": ZERO,
                "overdue_count": 0,
                "next_due": None,
                "recent_bills": [],
                "recent_payments": [],
                "charge_breakdown": [],
                "water": None,
                "electricity": None,
                "vehicles": 0,
                "parking_slots": 0,
                "pets": 0,
                "paid_this_year": ZERO,
            }

        flats = list(
            await self.tenant.scalars(
                select(Flat)
                .where(Flat.id.in_(flat_ids))
                .options(selectinload(Flat.floor).selectinload(Floor.block).selectinload(Block.building))
                .order_by(Flat.flat_number)
            )
        )

        bills = list(
            await self.tenant.scalars(
                select(MaintenanceBill)
                .where(
                    MaintenanceBill.flat_id.in_(flat_ids),
                    MaintenanceBill.status == BillStatus.PUBLISHED,
                )
                .order_by(MaintenanceBill.period_start.desc())
                .limit(12)
            )
        )

        outstanding = Decimal(
            str(
                await self.tenant.scalar(
                    select(
                        func.coalesce(
                            func.sum(MaintenanceBill.total - MaintenanceBill.amount_paid), 0
                        )
                    ).where(
                        MaintenanceBill.flat_id.in_(flat_ids),
                        MaintenanceBill.status == BillStatus.PUBLISHED,
                        MaintenanceBill.payment_status != PaymentStatus.PAID,
                    )
                )
                or 0
            )
        )

        overdue_count = int(
            await self.tenant.scalar(
                select(func.count())
                .select_from(MaintenanceBill)
                .where(
                    MaintenanceBill.flat_id.in_(flat_ids),
                    MaintenanceBill.status == BillStatus.PUBLISHED,
                    MaintenanceBill.payment_status != PaymentStatus.PAID,
                    MaintenanceBill.due_date < today,
                )
            )
            or 0
        )

        # The oldest unpaid bill is what the resident actually owes next —
        # not the newest, which is what a naive "latest bill" card would show.
        next_due_bill = await self.tenant.scalar(
            select(MaintenanceBill)
            .where(
                MaintenanceBill.flat_id.in_(flat_ids),
                MaintenanceBill.status == BillStatus.PUBLISHED,
                MaintenanceBill.payment_status != PaymentStatus.PAID,
            )
            .order_by(MaintenanceBill.due_date)
            .limit(1)
        )

        payments = list(
            await self.tenant.scalars(
                select(Payment)
                .where(
                    Payment.flat_id.in_(flat_ids),
                    Payment.status == PaymentStatus.SUCCESS,
                )
                .options(selectinload(Payment.bill))
                .order_by(Payment.paid_at.desc().nullslast(), Payment.created_at.desc())
                .limit(6)
            )
        )

        return {
            "flats": [
                {
                    "id": f.id,
                    "flat_number": f.flat_number,
                    "building_name": f.floor.block.building.name if f.floor else None,
                    "block_name": f.floor.block.name if f.floor else None,
                    "floor_name": f.floor.name if f.floor else None,
                    "area_sqft": f.area_sqft,
                }
                for f in flats
            ],
            "outstanding": outstanding,
            "overdue_count": overdue_count,
            "next_due": _bill_dict(next_due_bill, today) if next_due_bill else None,
            "recent_bills": [_bill_dict(b, today) for b in bills[:6]],
            "recent_payments": [
                {
                    "id": p.id,
                    "amount": p.amount,
                    "paid_on": (p.paid_at.date() if p.paid_at else p.created_at.date()),
                    "method": str(p.method),
                    "reference": p.reference_number,
                    "bill_number": p.bill.bill_number if p.bill else None,
                }
                for p in payments
            ],
            "charge_breakdown": await self._charge_breakdown(bills),
            "water": await self._trend(flat_ids[0], principal, "water"),
            "electricity": await self._trend(flat_ids[0], principal, "electricity"),
            "vehicles": await self._count(Vehicle, flat_ids),
            "parking_slots": await self._count(ParkingSlot, flat_ids),
            "pets": await self._count(Pet, flat_ids),
            "paid_this_year": await self._paid_this_year(flat_ids, today),
        }

    async def _charge_breakdown(
        self, bills: list[MaintenanceBill]
    ) -> list[dict[str, Any]]:
        """Where the money goes, from the most recent bill only.

        Summing several periods would mix a quarterly charge with a monthly one
        and produce a chart nobody can act on.
        """
        if not bills:
            return []
        rows = await self.tenant.execute(
            select(
                BillLineItem.label,
                func.sum(BillLineItem.amount),
            )
            .where(
                BillLineItem.bill_id == bills[0].id,
                BillLineItem.is_credit.is_(False),
            )
            .group_by(BillLineItem.label)
            .order_by(func.sum(BillLineItem.amount).desc())
        )
        return [{"label": label, "amount": Decimal(str(amount))} for label, amount in rows]

    async def _trend(
        self, flat_id: uuid.UUID, principal: Principal, utility: str
    ) -> dict[str, Any] | None:
        service = ReadingService(self.tenant, utility=utility)
        if not principal.has(service.read_permission):
            return None
        trend = await service.trend(flat_id, principal, limit=12)
        return trend if trend["points"] else None

    async def _count(self, model: Any, flat_ids: list[uuid.UUID]) -> int:
        return int(
            await self.tenant.scalar(
                select(func.count())
                .select_from(model)
                .where(model.flat_id.in_(flat_ids), model.is_active.is_(True))
            )
            or 0
        )

    async def _paid_this_year(self, flat_ids: list[uuid.UUID], today: date) -> Decimal:
        """Indian financial year: April to March."""
        fy_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
        total = await self.tenant.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.flat_id.in_(flat_ids),
                Payment.status == PaymentStatus.SUCCESS,
                func.coalesce(Payment.paid_at, Payment.created_at) >= fy_start,
            )
        )
        return Decimal(str(total or 0))


class SocietyUtilityDashboardService:
    """The admin-side counterpart: society-wide consumption and asset counts."""

    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant

    async def build(self, months: int = 12) -> dict[str, Any]:
        water = ReadingService(self.tenant, utility="water")
        electricity = ReadingService(self.tenant, utility="electricity")

        parking = await self.tenant.execute(
            select(func.count(), func.count(ParkingSlot.flat_id)).where(
                ParkingSlot.is_active.is_(True)
            )
        )
        total_slots, allotted = parking.first() or (0, 0)

        vehicle_rows = await self.tenant.execute(
            select(Vehicle.vehicle_type, func.count())
            .where(Vehicle.is_active.is_(True))
            .group_by(Vehicle.vehicle_type)
        )

        return {
            "water": await water.society_trend(months),
            "electricity": await electricity.society_trend(months),
            "parking": {
                "total": int(total_slots),
                "allotted": int(allotted),
                "available": int(total_slots) - int(allotted),
            },
            "vehicles_by_type": {str(t): int(c) for t, c in vehicle_rows},
            "pets": int(
                await self.tenant.scalar(
                    select(func.count()).select_from(Pet).where(Pet.is_active.is_(True))
                )
                or 0
            ),
            "flats_missing_water": await self._missing(WaterReading),
            "flats_missing_electricity": await self._missing(ElectricityReading),
        }

    async def _missing(self, model: Any) -> int:
        """Active flats that have never had a reading — the gap an admin must
        close before a consumption-based bill can be generated."""
        recorded = select(model.flat_id).distinct().subquery()
        return int(
            await self.tenant.scalar(
                select(func.count())
                .select_from(Flat)
                .outerjoin(recorded, Flat.id == recorded.c.flat_id)
                .where(Flat.is_active.is_(True), recorded.c.flat_id.is_(None))
            )
            or 0
        )
