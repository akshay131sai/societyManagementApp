"""Reports.

A report here is a function that returns ``columns`` and ``rows``. Everything
else — the envelope, the totals footer, the CSV writer, the permission check,
the row cap — is shared, so adding "outstanding by building" is one function and
one registry entry rather than a new endpoint, a new schema and a new export
path.

Two rules the reports obey:

* **Money is summed by PostgreSQL, in one query.** A report that pulls 4,000
  bills into Python to add them up is a report that times out on the society
  that most needs it.

* **A capped report says so.** ``truncated`` is set when the limit is reached.
  A silently shortened defaulter list is worse than no list.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.permissions import OWNER_SCOPED_PERMISSIONS, Permission
from app.engines.billing.periods import financial_year_label, financial_year_start
from app.models.tenant import (
    OPEN_COMPLAINT_STATUSES,
    OPEN_TASK_STATUSES,
    ACTIVE_BOOKING_STATUSES,
    Amenity,
    AmenityBooking,
    BillStatus,
    Block,
    Building,
    Complaint,
    ElectricityReading,
    Flat,
    MaintenanceBill,
    Payment,
    PaymentStatus,
    Resident,
    SecurityIncident,
    Visitor,
    VisitorStatus,
    WaterReading,
    WorkTask,
)
from app.schemas.reports import ColumnType, ReportRequest

log = structlog.get_logger(__name__)

ZERO = Decimal("0")


def _col(
    key: str, label: str, type_: ColumnType = ColumnType.TEXT, *, total: bool = False
) -> dict[str, Any]:
    return {"key": key, "label": label, "type": type_, "total": total}


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == ZERO:
        return ZERO
    return (numerator / denominator * 100).quantize(Decimal("0.1"))


@dataclass(frozen=True, slots=True)
class ReportDefinition:
    key: str
    title: str
    description: str
    permission: Permission
    build: Callable[["ReportService", ReportRequest], Awaitable[dict[str, Any]]]
    accepts_period: bool = True
    accepts_dates: bool = True


class ReportService:
    """Builds any registered report.

    ``REPORTS`` is populated at the bottom of the module, after the builders
    exist. The registry is the only place a report's identity, title and
    required permission are written down — the router reads it, the catalogue
    endpoint returns it, and the CSV export reuses it.
    """

    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant

    # -- entry points -------------------------------------------------------- #

    def catalogue(self, held: frozenset[Permission]) -> list[dict[str, Any]]:
        """Reports this principal may actually run.

        Listing a report someone cannot open is a menu item that 403s, so the
        catalogue is filtered rather than the click.
        """
        return [
            {
                "key": r.key,
                "title": r.title,
                "description": r.description,
                "permission": r.permission.value,
                "accepts_period": r.accepts_period,
                "accepts_dates": r.accepts_dates,
            }
            for r in REPORTS.values()
            if r.permission in held
        ]

    async def run(
        self, key: str, request: ReportRequest, *, held: frozenset[Permission]
    ) -> dict[str, Any]:
        if (
            request.from_date is not None
            and request.to_date is not None
            and request.to_date < request.from_date
        ):
            raise ValidationError("The end date is before the start date.")

        definition = REPORTS.get(key)
        if definition is None or definition.permission not in held:
            # A report a principal cannot run is a report that does not exist,
            # for the same reason a neighbour's flat 404s.
            raise NotFoundError("Report")

        built = await definition.build(self, request)
        columns: list[dict[str, Any]] = built["columns"]

        # The cap is applied here, not in each builder. Several reports have
        # naturally bounded row counts and pass no LIMIT of their own; enforcing
        # it centrally is what makes ``truncated`` mean the same thing for all
        # ten, rather than "the builder happened to remember".
        produced: list[dict[str, Any]] = built["rows"]
        truncated = len(produced) > request.limit
        rows = produced[: request.limit] if truncated else produced

        # A counted column totals to an integer and a money column to a
        # Decimal. Summing everything as Decimal would send "12" for a bill
        # count, and every client would have to know which columns to coerce.
        totals: dict[str, Any] = {}
        for column in columns:
            if not column["total"]:
                continue
            values = [r.get(column["key"], 0) or 0 for r in rows]
            if column["type"] is ColumnType.NUMBER:
                totals[column["key"]] = sum(int(v) for v in values)
            else:
                totals[column["key"]] = sum(
                    (Decimal(str(v)) for v in values), ZERO
                )

        return {
            "key": definition.key,
            "title": definition.title,
            "description": definition.description,
            "generated_at": date.today(),
            "period_label": built.get("period_label") or request.period_key,
            "from_date": request.from_date,
            "to_date": request.to_date,
            "columns": columns,
            "rows": rows,
            "totals": totals,
            "summary": built.get("summary", {}),
            "row_count": len(rows),
            "truncated": truncated,
        }

    @staticmethod
    def to_csv(report: dict[str, Any]) -> str:
        """The same rows, as a file a treasurer can open in Excel.

        Written from ``columns`` rather than from the first row's keys, so the
        column order matches the screen and an empty report still exports its
        headers.
        """
        buffer = io.StringIO()
        columns = report["columns"]
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow([c["label"] for c in columns])
        for row in report["rows"]:
            writer.writerow([_csv_cell(row.get(c["key"])) for c in columns])

        totals = report.get("totals") or {}
        if totals:
            writer.writerow([])
            writer.writerow(
                ["Total" if i == 0 else _csv_cell(totals.get(c["key"], ""))
                 for i, c in enumerate(columns)]
            )
        return buffer.getvalue()

    # -- shared query pieces ------------------------------------------------- #

    def _window(
        self, request: ReportRequest, *, default_days: int = 90, forward_days: int = 0
    ) -> tuple[date, date]:
        """The reporting window, with the caller's dates taking precedence.

        ``forward_days`` exists because not every report looks backwards. A
        facility is *booked ahead*, and a utilisation report whose default
        window ends today reads as zero on the very week the clubhouse is full.
        """
        today = date.today()
        to_date = request.to_date or (today + timedelta(days=forward_days))
        from_date = request.from_date or (today - timedelta(days=default_days))
        return from_date, to_date

    def _by_building(self, stmt: Select, column: Any, request: ReportRequest) -> Select:
        if request.building_id:
            stmt = stmt.where(column == uuid.UUID(request.building_id))
        return stmt

    # -- builders ------------------------------------------------------------ #

    async def collection(self, request: ReportRequest) -> dict[str, Any]:
        """Billed against collected, one row per billing period.

        The single most-asked question in a society AGM, and the reason the
        figures are grouped by ``period_key`` rather than by payment date: money
        received in July for June belongs to June.
        """
        stmt = (
            select(
                MaintenanceBill.period_key,
                func.min(MaintenanceBill.period_label),
                func.count(),
                func.coalesce(func.sum(MaintenanceBill.total), 0),
                func.coalesce(func.sum(MaintenanceBill.amount_paid), 0),
                func.count().filter(
                    MaintenanceBill.payment_status == PaymentStatus.PAID
                ),
                func.min(MaintenanceBill.period_start),
            )
            .where(MaintenanceBill.status == BillStatus.PUBLISHED)
            .group_by(MaintenanceBill.period_key)
        )
        if request.from_date:
            stmt = stmt.having(func.min(MaintenanceBill.period_start) >= request.from_date)
        if request.to_date:
            stmt = stmt.having(func.min(MaintenanceBill.period_start) <= request.to_date)

        rows: list[dict[str, Any]] = []
        billed_total = ZERO
        collected_total = ZERO
        for key, label, count, billed, paid, settled, _start in (
            await self.tenant.execute(stmt.order_by(func.min(MaintenanceBill.period_start).desc()).limit(request.limit))
        ):
            billed_amount = _money(billed)
            collected = _money(paid)
            billed_total += billed_amount
            collected_total += collected
            rows.append(
                {
                    "period": label or key,
                    "bills": int(count),
                    "billed": billed_amount,
                    "collected": collected,
                    "outstanding": billed_amount - collected,
                    "settled_flats": int(settled),
                    "collection_rate": _pct(collected, billed_amount),
                }
            )

        return {
            "columns": [
                _col("period", "Period"),
                _col("bills", "Bills", ColumnType.NUMBER, total=True),
                _col("billed", "Billed", ColumnType.MONEY, total=True),
                _col("collected", "Collected", ColumnType.MONEY, total=True),
                _col("outstanding", "Outstanding", ColumnType.MONEY, total=True),
                _col("settled_flats", "Fully paid", ColumnType.NUMBER, total=True),
                _col("collection_rate", "Collection", ColumnType.PERCENT),
            ],
            "rows": rows,
            "summary": {
                "billed": billed_total,
                "collected": collected_total,
                "outstanding": billed_total - collected_total,
                "collection_rate": _pct(collected_total, billed_total),
            },
        }

    async def defaulters(self, request: ReportRequest) -> dict[str, Any]:
        """Who owes what, oldest debt first.

        Ordered by the age of the oldest unpaid bill rather than by amount: a
        flat three quarters behind is a different conversation from one that
        missed this month, even if the second owes more.
        """
        balance = MaintenanceBill.total - MaintenanceBill.amount_paid
        stmt = (
            select(
                Flat.id,
                Flat.flat_number,
                Building.name,
                func.count(),
                func.coalesce(func.sum(balance), 0),
                func.min(MaintenanceBill.due_date),
            )
            .join(MaintenanceBill, MaintenanceBill.flat_id == Flat.id)
            .join(Building, Building.id == Flat.building_id)
            .where(
                MaintenanceBill.status == BillStatus.PUBLISHED,
                balance > 0,
            )
            .group_by(Flat.id, Flat.flat_number, Building.name)
        )
        stmt = self._by_building(stmt, Flat.building_id, request)

        today = date.today()
        rows: list[dict[str, Any]] = []
        for flat_id, number, building, count, owed, oldest in await self.tenant.execute(
            stmt.order_by(func.min(MaintenanceBill.due_date)).limit(request.limit)
        ):
            rows.append(
                {
                    "flat_id": str(flat_id),
                    "flat": number,
                    "building": building,
                    "unpaid_bills": int(count),
                    "outstanding": _money(owed),
                    "oldest_due": oldest,
                    "days_overdue": max((today - oldest).days, 0) if oldest else 0,
                }
            )

        outstanding = sum((r["outstanding"] for r in rows), ZERO)
        return {
            "columns": [
                _col("flat", "Flat"),
                _col("building", "Building"),
                _col("unpaid_bills", "Unpaid bills", ColumnType.NUMBER, total=True),
                _col("outstanding", "Outstanding", ColumnType.MONEY, total=True),
                _col("oldest_due", "Oldest due", ColumnType.DATE),
                _col("days_overdue", "Days overdue", ColumnType.NUMBER),
            ],
            "rows": rows,
            "summary": {
                "flats": len(rows),
                "outstanding": outstanding,
                "worst_days": max((r["days_overdue"] for r in rows), default=0),
            },
        }

    async def payments(self, request: ReportRequest) -> dict[str, Any]:
        """Receipts in a window, grouped by how the money arrived."""
        from_date, to_date = self._window(request)
        stmt = (
            select(
                Payment.method,
                func.count(),
                func.coalesce(func.sum(Payment.amount), 0),
            )
            .where(
                Payment.status == PaymentStatus.SUCCESS,
                Payment.paid_at.is_not(None),
                func.date(Payment.paid_at) >= from_date,
                func.date(Payment.paid_at) <= to_date,
            )
            .group_by(Payment.method)
        )

        rows = [
            {
                "method": str(getattr(method, "value", method)).title(),
                "count": int(count),
                "amount": _money(amount),
            }
            for method, count, amount in await self.tenant.execute(
                stmt.order_by(func.sum(Payment.amount).desc())
            )
        ]
        total = sum((r["amount"] for r in rows), ZERO)
        for row in rows:
            row["share"] = _pct(row["amount"], total)

        return {
            "columns": [
                _col("method", "Method"),
                _col("count", "Payments", ColumnType.NUMBER, total=True),
                _col("amount", "Amount", ColumnType.MONEY, total=True),
                _col("share", "Share", ColumnType.PERCENT),
            ],
            "rows": rows,
            "summary": {"collected": total, "from": from_date, "to": to_date},
        }

    async def complaints(self, request: ReportRequest) -> dict[str, Any]:
        """Complaint volume and SLA performance, by category.

        ``within_sla`` counts tickets resolved before ``due_by``, which is the
        promise recorded when the ticket was raised — not the promise the
        current configuration would make, which would let a society improve its
        history by editing a constant.
        """
        from_date, to_date = self._window(request, default_days=180)
        resolution_hours = (
            func.extract("epoch", Complaint.resolved_at - Complaint.created_at) / 3600.0
        )
        stmt = (
            select(
                Complaint.category,
                func.count(),
                func.count().filter(Complaint.status.in_(list(OPEN_COMPLAINT_STATUSES))),
                func.count().filter(Complaint.resolved_at.is_not(None)),
                func.avg(resolution_hours).filter(Complaint.resolved_at.is_not(None)),
                func.count().filter(
                    and_(
                        Complaint.resolved_at.is_not(None),
                        Complaint.due_by.is_not(None),
                        Complaint.resolved_at <= Complaint.due_by,
                    )
                ),
                func.avg(Complaint.rating).filter(Complaint.rating.is_not(None)),
            )
            .where(
                func.date(Complaint.created_at) >= from_date,
                func.date(Complaint.created_at) <= to_date,
            )
            .group_by(Complaint.category)
        )

        rows: list[dict[str, Any]] = []
        for category, total, open_count, resolved, avg_hours, in_sla, rating in (
            await self.tenant.execute(stmt.order_by(func.count().desc()))
        ):
            rows.append(
                {
                    "category": str(getattr(category, "value", category))
                    .replace("_", " ")
                    .title(),
                    "raised": int(total),
                    "open": int(open_count),
                    "resolved": int(resolved),
                    "avg_hours": (
                        Decimal(str(avg_hours)).quantize(Decimal("0.1"))
                        if avg_hours is not None
                        else ZERO
                    ),
                    "within_sla": _pct(Decimal(int(in_sla)), Decimal(max(int(resolved), 1))),
                    "rating": (
                        Decimal(str(rating)).quantize(Decimal("0.01"))
                        if rating is not None
                        else None
                    ),
                }
            )

        raised = sum(r["raised"] for r in rows)
        resolved_total = sum(r["resolved"] for r in rows)
        return {
            "columns": [
                _col("category", "Category"),
                _col("raised", "Raised", ColumnType.NUMBER, total=True),
                _col("open", "Still open", ColumnType.NUMBER, total=True),
                _col("resolved", "Resolved", ColumnType.NUMBER, total=True),
                _col("avg_hours", "Avg hours", ColumnType.NUMBER),
                _col("within_sla", "Within target", ColumnType.PERCENT),
                _col("rating", "Rating", ColumnType.NUMBER),
            ],
            "rows": rows,
            "summary": {
                "raised": raised,
                "resolved": resolved_total,
                "resolution_rate": _pct(
                    Decimal(resolved_total), Decimal(max(raised, 1))
                ),
                "from": from_date,
                "to": to_date,
            },
        }

    async def work(self, request: ReportRequest) -> dict[str, Any]:
        """Maintenance and housekeeping throughput and spend.

        Also spans forward, by the longest lead time a schedule may use: work
        already raised for next month is work a supervisor is planning around.
        """
        from_date, to_date = self._window(request, default_days=180, forward_days=90)
        stmt = (
            select(
                WorkTask.department,
                func.count(),
                func.count().filter(WorkTask.status.in_(list(OPEN_TASK_STATUSES))),
                func.count().filter(
                    and_(
                        WorkTask.status.in_(list(OPEN_TASK_STATUSES)),
                        WorkTask.due_on < date.today(),
                    )
                ),
                func.count().filter(WorkTask.completed_at.is_not(None)),
                func.coalesce(func.sum(WorkTask.actual_cost), 0),
            )
            .where(WorkTask.due_on >= from_date, WorkTask.due_on <= to_date)
            .group_by(WorkTask.department)
        )

        rows = [
            {
                "department": str(getattr(dept, "value", dept)).title(),
                "tasks": int(total),
                "open": int(open_count),
                "overdue": int(overdue),
                "completed": int(done),
                "cost": _money(cost),
                "completion_rate": _pct(Decimal(int(done)), Decimal(max(int(total), 1))),
            }
            for dept, total, open_count, overdue, done, cost in await self.tenant.execute(stmt)
        ]

        return {
            "columns": [
                _col("department", "Department"),
                _col("tasks", "Tasks", ColumnType.NUMBER, total=True),
                _col("open", "Open", ColumnType.NUMBER, total=True),
                _col("overdue", "Overdue", ColumnType.NUMBER, total=True),
                _col("completed", "Completed", ColumnType.NUMBER, total=True),
                _col("cost", "Spend", ColumnType.MONEY, total=True),
                _col("completion_rate", "Completed", ColumnType.PERCENT),
            ],
            "rows": rows,
            "summary": {
                "spend": sum((r["cost"] for r in rows), ZERO),
                "from": from_date,
                "to": to_date,
            },
        }

    async def utilities(self, request: ReportRequest) -> dict[str, Any]:
        """Water and electricity consumption per reading round."""
        from_date, to_date = self._window(request, default_days=365)

        async def totals(model: Any, label: str) -> list[dict[str, Any]]:
            rows = await self.tenant.execute(
                select(
                    model.reading_date,
                    func.count(),
                    func.coalesce(func.sum(model.consumption), 0),
                    func.coalesce(func.avg(model.consumption), 0),
                )
                .where(model.reading_date >= from_date, model.reading_date <= to_date)
                .group_by(model.reading_date)
                .order_by(model.reading_date.desc())
                .limit(request.limit)
            )
            return [
                {
                    "utility": label,
                    "reading_date": read_date,
                    "flats": int(count),
                    "consumption": Decimal(str(total or 0)).quantize(Decimal("0.001")),
                    "average": Decimal(str(avg or 0)).quantize(Decimal("0.001")),
                }
                for read_date, count, total, avg in rows
            ]

        rows = await totals(WaterReading, "Water") + await totals(
            ElectricityReading, "Electricity"
        )
        rows.sort(key=lambda r: (r["reading_date"], r["utility"]), reverse=True)

        return {
            "columns": [
                _col("utility", "Utility"),
                _col("reading_date", "Reading date", ColumnType.DATE),
                _col("flats", "Flats read", ColumnType.NUMBER),
                _col("consumption", "Total", ColumnType.NUMBER, total=True),
                _col("average", "Avg per flat", ColumnType.NUMBER),
            ],
            "rows": rows[: request.limit],
            "summary": {"from": from_date, "to": to_date},
        }

    async def occupancy(self, request: ReportRequest) -> dict[str, Any]:
        """Flats, residents and occupancy mix, by building and block."""
        stmt = (
            select(
                Building.name,
                Block.name,
                func.count(func.distinct(Flat.id)),
                func.count(func.distinct(Flat.id)).filter(
                    Flat.occupancy_status == "OWNER_OCCUPIED"
                ),
                func.count(func.distinct(Flat.id)).filter(Flat.occupancy_status == "RENTED"),
                func.count(func.distinct(Flat.id)).filter(Flat.occupancy_status == "VACANT"),
                func.coalesce(func.sum(func.distinct(Flat.area_sqft)), 0),
            )
            .select_from(Flat)
            .join(Building, Building.id == Flat.building_id)
            .join(Block, Block.id == Flat.block_id)
            .where(Flat.is_active.is_(True))
            .group_by(Building.name, Block.name)
        )
        stmt = self._by_building(stmt, Flat.building_id, request)

        rows: list[dict[str, Any]] = []
        for building, block, flats, owner, rented, vacant, _area in (
            await self.tenant.execute(stmt.order_by(Building.name, Block.name))
        ):
            rows.append(
                {
                    "building": building,
                    "block": block,
                    "flats": int(flats),
                    "owner_occupied": int(owner),
                    "rented": int(rented),
                    "vacant": int(vacant),
                    "occupancy": _pct(
                        Decimal(int(flats) - int(vacant)), Decimal(max(int(flats), 1))
                    ),
                }
            )

        residents = int(
            await self.tenant.scalar(
                select(func.count()).select_from(Resident).where(Resident.is_active.is_(True))
            )
            or 0
        )
        total_flats = sum(r["flats"] for r in rows)
        vacant_total = sum(r["vacant"] for r in rows)
        return {
            "columns": [
                _col("building", "Building"),
                _col("block", "Block"),
                _col("flats", "Flats", ColumnType.NUMBER, total=True),
                _col("owner_occupied", "Owner occupied", ColumnType.NUMBER, total=True),
                _col("rented", "Rented", ColumnType.NUMBER, total=True),
                _col("vacant", "Vacant", ColumnType.NUMBER, total=True),
                _col("occupancy", "Occupied", ColumnType.PERCENT),
            ],
            "rows": rows,
            "summary": {
                "flats": total_flats,
                "residents": residents,
                "vacant": vacant_total,
                "occupancy": _pct(
                    Decimal(total_flats - vacant_total), Decimal(max(total_flats, 1))
                ),
            },
        }

    async def visitors(self, request: ReportRequest) -> dict[str, Any]:
        """Gate traffic by visitor type over a window."""
        from_date, to_date = self._window(request, default_days=30)
        duration = (
            func.extract("epoch", Visitor.checked_out_at - Visitor.checked_in_at) / 60.0
        )
        stmt = (
            select(
                Visitor.visitor_type,
                func.count(),
                func.count().filter(Visitor.checked_in_at.is_not(None)),
                func.count().filter(Visitor.status == VisitorStatus.DENIED),
                func.count().filter(Visitor.status == VisitorStatus.EXPIRED),
                func.avg(duration).filter(Visitor.checked_out_at.is_not(None)),
            )
            .where(
                func.date(Visitor.created_at) >= from_date,
                func.date(Visitor.created_at) <= to_date,
            )
            .group_by(Visitor.visitor_type)
        )

        rows = [
            {
                "visitor_type": str(getattr(vtype, "value", vtype))
                .replace("_", " ")
                .title(),
                "logged": int(total),
                "entered": int(entered),
                "denied": int(denied),
                "expired": int(expired),
                "avg_minutes": (
                    int(avg_minutes) if avg_minutes is not None else 0
                ),
            }
            for vtype, total, entered, denied, expired, avg_minutes in (
                await self.tenant.execute(stmt.order_by(func.count().desc()))
            )
        ]

        incidents = int(
            await self.tenant.scalar(
                select(func.count())
                .select_from(SecurityIncident)
                .where(
                    func.date(SecurityIncident.occurred_at) >= from_date,
                    func.date(SecurityIncident.occurred_at) <= to_date,
                )
            )
            or 0
        )
        return {
            "columns": [
                _col("visitor_type", "Type"),
                _col("logged", "Logged", ColumnType.NUMBER, total=True),
                _col("entered", "Entered", ColumnType.NUMBER, total=True),
                _col("denied", "Denied", ColumnType.NUMBER, total=True),
                _col("expired", "Expired", ColumnType.NUMBER, total=True),
                _col("avg_minutes", "Avg stay (min)", ColumnType.NUMBER),
            ],
            "rows": rows,
            "summary": {
                "logged": sum(r["logged"] for r in rows),
                "entered": sum(r["entered"] for r in rows),
                "incidents": incidents,
                "from": from_date,
                "to": to_date,
            },
        }

    async def amenities(self, request: ReportRequest) -> dict[str, Any]:
        """Amenity utilisation and the revenue it produced.

        Deliberately spans forward as well as back: the question an amenity
        report answers is "is the clubhouse being used", and next Saturday's
        booking is part of that answer.
        """
        from_date, to_date = self._window(request, default_days=30, forward_days=60)
        stmt = (
            select(
                Amenity.name,
                func.count(AmenityBooking.id),
                func.coalesce(func.sum(AmenityBooking.slots), 0),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                AmenityBooking.status.in_(list(ACTIVE_BOOKING_STATUSES))
                                | (AmenityBooking.status == "COMPLETED"),
                                AmenityBooking.charge,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.count(AmenityBooking.id).filter(AmenityBooking.status == "CANCELLED"),
            )
            .select_from(Amenity)
            .join(
                AmenityBooking,
                and_(
                    AmenityBooking.amenity_id == Amenity.id,
                    AmenityBooking.booking_date >= from_date,
                    AmenityBooking.booking_date <= to_date,
                ),
                isouter=True,
            )
            .group_by(Amenity.id, Amenity.name)
        )

        rows = [
            {
                "amenity": name,
                "bookings": int(count),
                "slots": int(slots or 0),
                "revenue": _money(revenue),
                "cancelled": int(cancelled),
            }
            for name, count, slots, revenue, cancelled in await self.tenant.execute(
                stmt.order_by(func.count(AmenityBooking.id).desc())
            )
        ]

        return {
            "columns": [
                _col("amenity", "Amenity"),
                _col("bookings", "Bookings", ColumnType.NUMBER, total=True),
                _col("slots", "Slots", ColumnType.NUMBER, total=True),
                _col("cancelled", "Cancelled", ColumnType.NUMBER, total=True),
                _col("revenue", "Revenue", ColumnType.MONEY, total=True),
            ],
            "rows": rows,
            "summary": {
                "revenue": sum((r["revenue"] for r in rows), ZERO),
                "from": from_date,
                "to": to_date,
            },
        }

    async def financial_year(self, request: ReportRequest) -> dict[str, Any]:
        """A financial-year ledger by month.

        Indian societies close their books on 31 March, so the rows run April
        to March and the label says ``FY2026-27``. Reusing the billing engine's
        own boundary function means the report and the bills agree on where the
        year starts.
        """
        anchor = request.to_date or date.today()
        fy_start = financial_year_start(anchor, 4)
        label = financial_year_label(fy_start)
        fy_end = date(fy_start.year + 1, fy_start.month, fy_start.day) - timedelta(days=1)

        # One expression object, reused. Spelling ``to_char(...)`` out twice
        # emits two different bind parameters, and PostgreSQL then cannot see
        # that the grouped expression is the selected one.
        month = func.to_char(MaintenanceBill.period_start, "Mon YYYY").label("month")
        billed = await self.tenant.execute(
            select(
                month,
                func.min(MaintenanceBill.period_start),
                func.coalesce(func.sum(MaintenanceBill.total), 0),
                func.coalesce(func.sum(MaintenanceBill.amount_paid), 0),
                func.count(),
            )
            .where(
                MaintenanceBill.status == BillStatus.PUBLISHED,
                MaintenanceBill.period_start >= fy_start,
                MaintenanceBill.period_start <= fy_end,
            )
            .group_by(month)
            .order_by(func.min(MaintenanceBill.period_start))
        )

        rows = [
            {
                "month": month,
                "bills": int(count),
                "billed": _money(total),
                "collected": _money(paid),
                "outstanding": _money(total) - _money(paid),
            }
            for month, _start, total, paid, count in billed
        ]

        return {
            "period_label": label,
            "columns": [
                _col("month", "Month"),
                _col("bills", "Bills", ColumnType.NUMBER, total=True),
                _col("billed", "Billed", ColumnType.MONEY, total=True),
                _col("collected", "Collected", ColumnType.MONEY, total=True),
                _col("outstanding", "Outstanding", ColumnType.MONEY, total=True),
            ],
            "rows": rows,
            "summary": {
                "financial_year": label,
                "from": fy_start,
                "to": fy_end,
                "billed": sum((r["billed"] for r in rows), ZERO),
                "collected": sum((r["collected"] for r in rows), ZERO),
            },
        }


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:f}"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


REPORTS: dict[str, ReportDefinition] = {
    definition.key: definition
    for definition in (
        ReportDefinition(
            key="collection",
            title="Collection summary",
            description="Billed against collected, by billing period.",
            permission=Permission.REPORT_READ,
            build=ReportService.collection,
        ),
        ReportDefinition(
            key="defaulters",
            title="Outstanding dues",
            description="Flats with an unpaid balance, oldest debt first.",
            permission=Permission.BILLING_READ_ALL,
            build=ReportService.defaulters,
            accepts_period=False,
        ),
        ReportDefinition(
            key="payments",
            title="Payments received",
            description="Receipts in a window, grouped by payment method.",
            # Not ``payment.read``: a resident holds that for their own bills,
            # and this report is every receipt in the society.
            permission=Permission.REPORT_READ,
            build=ReportService.payments,
            accepts_period=False,
        ),
        ReportDefinition(
            key="financial-year",
            title="Financial year ledger",
            description="April to March, month by month.",
            permission=Permission.REPORT_READ,
            build=ReportService.financial_year,
            accepts_period=False,
        ),
        ReportDefinition(
            key="complaints",
            title="Complaint performance",
            description="Volume, resolution time and SLA adherence by category.",
            permission=Permission.REPORT_READ,
            build=ReportService.complaints,
            accepts_period=False,
        ),
        ReportDefinition(
            key="work",
            title="Maintenance and housekeeping",
            description="Task throughput, overdue work and spend.",
            permission=Permission.REPORT_READ,
            build=ReportService.work,
            accepts_period=False,
        ),
        ReportDefinition(
            key="utilities",
            title="Utility consumption",
            description="Water and electricity totals per reading round.",
            permission=Permission.REPORT_READ,
            build=ReportService.utilities,
            accepts_period=False,
        ),
        ReportDefinition(
            key="occupancy",
            title="Occupancy",
            description="Flats, residents and the owner/tenant/vacant mix.",
            permission=Permission.REPORT_READ,
            build=ReportService.occupancy,
            accepts_period=False,
            accepts_dates=False,
        ),
        ReportDefinition(
            key="visitors",
            title="Gate traffic",
            description="Visitor volume by type, with denials and average stay.",
            permission=Permission.REPORT_READ,
            build=ReportService.visitors,
            accepts_period=False,
        ),
        ReportDefinition(
            key="amenities",
            title="Amenity utilisation",
            description="Bookings, cancellations and revenue per facility.",
            permission=Permission.REPORT_READ,
            build=ReportService.amenities,
            accepts_period=False,
        ),
    )
}
"""The catalogue. Adding a report is a builder method and an entry here."""


REPORT_KEYS: tuple[str, ...] = tuple(REPORTS)

# A report is society-wide by nature: its rows aggregate across every flat.
# Gating one on an owner-scoped permission would hand a resident the whole
# society's figures, so the possibility is closed off at import.
assert not (
    {d.permission for d in REPORTS.values()} & OWNER_SCOPED_PERMISSIONS
), "a report must not be gated on an owner-scoped permission"
