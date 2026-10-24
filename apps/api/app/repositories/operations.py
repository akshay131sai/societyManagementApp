"""Complaint, work, visitor and incident repositories.

All SQL, no decisions. Owner scoping arrives here as an explicit
``only_flat_ids`` argument — a repository never asks who is calling, because a
repository that reads a principal is a repository that can be forgotten to.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tenant import (
    OPEN_COMPLAINT_STATUSES,
    OPEN_TASK_STATUSES,
    Complaint,
    ComplaintComment,
    ComplaintStatus,
    Department,
    IncidentStatus,
    SecurityIncident,
    TaskStatus,
    Visitor,
    VisitorStatus,
    VisitorType,
    WorkSchedule,
    WorkTask,
)

UNANSWERED_WALK_UP_HOURS = 6
"""A gate request nobody answered within this long is closed by the nightly sweep."""

async def _count(session: AsyncSession, stmt: Select) -> int:
    subq = stmt.order_by(None).subquery()
    return int(await session.scalar(select(func.count()).select_from(subq)) or 0)


def _restrict(stmt: Select, column: Any, only_flat_ids: Sequence[uuid.UUID] | None) -> Select:
    """Narrow to a principal's own flats.

    An empty list means "scoped, but owns nothing", which must return nothing —
    not everything. Spelling that out here keeps the mistake out of five call
    sites.
    """
    if only_flat_ids is None:
        return stmt
    if not only_flat_ids:
        return stmt.where(False)
    return stmt.where(column.in_(list(only_flat_ids)))


# --------------------------------------------------------------------------- #
# Complaints
# --------------------------------------------------------------------------- #


class ComplaintRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, complaint_id: uuid.UUID) -> Complaint | None:
        return await self.session.get(Complaint, complaint_id)

    async def get_with_comments(self, complaint_id: uuid.UUID) -> Complaint | None:
        return await self.session.scalar(
            select(Complaint)
            .options(selectinload(Complaint.comments))
            .where(Complaint.id == complaint_id)
        )

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        status: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        assigned_to: uuid.UUID | None = None,
        flat_id: uuid.UUID | None = None,
        open_only: bool = False,
        overdue_only: bool = False,
        unassigned_only: bool = False,
        only_flat_ids: Sequence[uuid.UUID] | None = None,
    ) -> tuple[Sequence[Complaint], int]:
        stmt = select(Complaint)
        if q:
            needle = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Complaint.title).like(needle),
                    func.lower(Complaint.ticket_number).like(needle),
                )
            )
        if status:
            stmt = stmt.where(Complaint.status == status)
        if category:
            stmt = stmt.where(Complaint.category == category)
        if priority:
            stmt = stmt.where(Complaint.priority == priority)
        if assigned_to is not None:
            stmt = stmt.where(Complaint.assigned_to == assigned_to)
        if flat_id is not None:
            stmt = stmt.where(Complaint.flat_id == flat_id)
        if open_only:
            stmt = stmt.where(Complaint.status.in_(list(OPEN_COMPLAINT_STATUSES)))
        if overdue_only:
            stmt = stmt.where(
                Complaint.status.in_(list(OPEN_COMPLAINT_STATUSES)),
                Complaint.due_by.is_not(None),
                Complaint.due_by < func.now(),
            )
        if unassigned_only:
            stmt = stmt.where(Complaint.assigned_to.is_(None))

        # A common-area complaint (no flat) belongs to everyone, so an
        # owner-scoped principal sees their own flat's tickets *and* the shared
        # ones. Narrowing to ``flat_id IN (...)`` alone would hide the burst
        # pipe in the lobby from the people walking past it.
        if only_flat_ids is not None:
            own = (
                Complaint.flat_id.in_(list(only_flat_ids)) if only_flat_ids else false()
            )
            stmt = stmt.where(or_(Complaint.flat_id.is_(None), own))

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(Complaint.created_at.desc()).offset((page - 1) * limit).limit(limit)
        )
        return list(rows), total

    async def create(self, complaint: Complaint) -> Complaint:
        self.session.add(complaint)
        await self.session.flush()
        return complaint

    async def add_comment(self, comment: ComplaintComment) -> ComplaintComment:
        self.session.add(comment)
        await self.session.flush()
        return comment

    async def comment_counts(
        self, complaint_ids: Sequence[uuid.UUID], *, include_internal: bool
    ) -> dict[uuid.UUID, int]:
        if not complaint_ids:
            return {}
        stmt = (
            select(ComplaintComment.complaint_id, func.count())
            .where(ComplaintComment.complaint_id.in_(list(complaint_ids)))
            .group_by(ComplaintComment.complaint_id)
        )
        if not include_internal:
            stmt = stmt.where(ComplaintComment.is_internal.is_(False))
        return {cid: int(n) for cid, n in await self.session.execute(stmt)}

    async def counts_by(self, column: Any) -> dict[str, int]:
        rows = await self.session.execute(
            select(column, func.count()).select_from(Complaint).group_by(column)
        )
        return {str(getattr(k, "value", k)): int(n) for k, n in rows}

    async def summary(self, *, month_start: date) -> dict[str, Any]:
        """Every headline number in one round trip.

        Six separate COUNT queries would each re-scan the table and could
        disagree with each other if a ticket moved between them.
        """
        open_statuses = list(OPEN_COMPLAINT_STATUSES)
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.count().filter(Complaint.status.in_(open_statuses)),
                    func.count().filter(
                        and_(
                            Complaint.status.in_(open_statuses),
                            Complaint.due_by.is_not(None),
                            Complaint.due_by < func.now(),
                        )
                    ),
                    func.count().filter(
                        and_(
                            Complaint.resolved_at.is_not(None),
                            Complaint.resolved_at >= month_start,
                        )
                    ),
                    func.count().filter(
                        and_(
                            Complaint.assigned_to.is_(None),
                            Complaint.status.in_(open_statuses),
                        )
                    ),
                    func.avg(
                        func.extract("epoch", Complaint.resolved_at - Complaint.created_at)
                        / 3600.0
                    ).filter(Complaint.resolved_at.is_not(None)),
                    func.avg(Complaint.rating).filter(Complaint.rating.is_not(None)),
                ).select_from(Complaint)
            )
        ).first()

        total, open_count, overdue, resolved, unassigned, avg_hours, avg_rating = row or (
            0,
            0,
            0,
            0,
            0,
            None,
            None,
        )
        return {
            "total": int(total or 0),
            "open": int(open_count or 0),
            "overdue": int(overdue or 0),
            "resolved_this_month": int(resolved or 0),
            "unassigned": int(unassigned or 0),
            "average_resolution_hours": (
                Decimal(str(avg_hours)).quantize(Decimal("0.1"))
                if avg_hours is not None
                else None
            ),
            "satisfaction": (
                Decimal(str(avg_rating)).quantize(Decimal("0.01"))
                if avg_rating is not None
                else None
            ),
        }

    async def overdue_open(self, limit: int = 500) -> Sequence[Complaint]:
        """Open tickets past their promised time — the escalation worklist."""
        rows = await self.session.scalars(
            select(Complaint)
            .where(
                Complaint.status.in_(list(OPEN_COMPLAINT_STATUSES)),
                Complaint.due_by.is_not(None),
                Complaint.due_by < func.now(),
            )
            .order_by(Complaint.due_by)
            .limit(limit)
        )
        return list(rows)

    async def resolved_before(self, cutoff: datetime, limit: int = 500) -> Sequence[Complaint]:
        """Resolved tickets nobody closed. The auto-close sweep's input."""
        rows = await self.session.scalars(
            select(Complaint)
            .where(
                Complaint.status == ComplaintStatus.RESOLVED,
                Complaint.resolved_at.is_not(None),
                Complaint.resolved_at < cutoff,
            )
            .limit(limit)
        )
        return list(rows)


# --------------------------------------------------------------------------- #
# Work schedules and tasks
# --------------------------------------------------------------------------- #


class WorkScheduleRepository:
    """Scoped to one department. The department is a constructor argument, not
    a filter a caller can forget: a housekeeping supervisor must not be one
    missing ``where`` away from the lift service contract."""

    def __init__(self, session: AsyncSession, department: Department) -> None:
        self.session = session
        self.department = department

    async def get(self, schedule_id: uuid.UUID) -> WorkSchedule | None:
        schedule = await self.session.get(WorkSchedule, schedule_id)
        if schedule is None or schedule.department != self.department:
            return None
        return schedule

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        active_only: bool = True,
    ) -> tuple[Sequence[WorkSchedule], int]:
        stmt = select(WorkSchedule).where(WorkSchedule.department == self.department)
        if active_only:
            stmt = stmt.where(WorkSchedule.is_active.is_(True))
        if q:
            stmt = stmt.where(func.lower(WorkSchedule.title).like(f"%{q.lower()}%"))

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(WorkSchedule.next_due_on).offset((page - 1) * limit).limit(limit)
        )
        return list(rows), total

    async def create(self, schedule: WorkSchedule) -> WorkSchedule:
        self.session.add(schedule)
        await self.session.flush()
        return schedule

    async def open_task_counts(
        self, schedule_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        if not schedule_ids:
            return {}
        rows = await self.session.execute(
            select(WorkTask.schedule_id, func.count())
            .where(
                WorkTask.schedule_id.in_(list(schedule_ids)),
                WorkTask.status.in_(list(OPEN_TASK_STATUSES)),
            )
            .group_by(WorkTask.schedule_id)
        )
        return {sid: int(n) for sid, n in rows if sid is not None}

    async def active_count(self) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(WorkSchedule)
                .where(
                    WorkSchedule.department == self.department,
                    WorkSchedule.is_active.is_(True),
                )
            )
            or 0
        )


class ScheduleGenerationRepository:
    """Department-agnostic, because the generator runs for the whole society."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def due(self, *, on: date, limit: int = 1000) -> Sequence[WorkSchedule]:
        """Schedules whose next occurrence has entered its lead window.

        ``next_due_on - lead_days`` is date arithmetic PostgreSQL does itself,
        and it reads the same way the rule does: raise the task ``lead_days``
        before it is due.
        """
        rows = await self.session.scalars(
            select(WorkSchedule)
            .where(
                WorkSchedule.is_active.is_(True),
                WorkSchedule.next_due_on - WorkSchedule.lead_days <= on,
                or_(WorkSchedule.ends_on.is_(None), WorkSchedule.ends_on >= on),
            )
            .order_by(WorkSchedule.next_due_on)
            .limit(limit)
        )
        return list(rows)

    async def existing_occurrences(
        self, schedule_ids: Sequence[uuid.UUID]
    ) -> set[tuple[uuid.UUID, date]]:
        """``(schedule_id, due_on)`` pairs already generated.

        The unique index would refuse a duplicate anyway; reading them first
        turns "insert and handle the error" into "insert only what is missing",
        which keeps one clash from aborting the whole batch.
        """
        if not schedule_ids:
            return set()
        rows = await self.session.execute(
            select(WorkTask.schedule_id, WorkTask.due_on).where(
                WorkTask.schedule_id.in_(list(schedule_ids))
            )
        )
        return {(sid, due) for sid, due in rows if sid is not None}


class WorkTaskRepository:
    def __init__(self, session: AsyncSession, department: Department | None = None) -> None:
        self.session = session
        self.department = department

    async def get(self, task_id: uuid.UUID) -> WorkTask | None:
        task = await self.session.get(WorkTask, task_id)
        if task is None:
            return None
        if self.department is not None and task.department != self.department:
            return None
        return task

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        assigned_to: uuid.UUID | None = None,
        schedule_id: uuid.UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        open_only: bool = False,
        overdue_only: bool = False,
    ) -> tuple[Sequence[WorkTask], int]:
        stmt = select(WorkTask)
        if self.department is not None:
            stmt = stmt.where(WorkTask.department == self.department)
        if q:
            stmt = stmt.where(func.lower(WorkTask.title).like(f"%{q.lower()}%"))
        if status:
            stmt = stmt.where(WorkTask.status == status)
        if priority:
            stmt = stmt.where(WorkTask.priority == priority)
        if assigned_to is not None:
            stmt = stmt.where(WorkTask.assigned_to == assigned_to)
        if schedule_id is not None:
            stmt = stmt.where(WorkTask.schedule_id == schedule_id)
        if from_date:
            stmt = stmt.where(WorkTask.due_on >= from_date)
        if to_date:
            stmt = stmt.where(WorkTask.due_on <= to_date)
        if open_only:
            stmt = stmt.where(WorkTask.status.in_(list(OPEN_TASK_STATUSES)))
        if overdue_only:
            stmt = stmt.where(
                WorkTask.status.in_(list(OPEN_TASK_STATUSES)),
                WorkTask.due_on < date.today(),
            )

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(WorkTask.due_on, WorkTask.created_at)
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total

    async def create(self, task: WorkTask) -> WorkTask:
        self.session.add(task)
        await self.session.flush()
        return task

    async def create_many(self, tasks: Sequence[WorkTask]) -> None:
        self.session.add_all(list(tasks))
        await self.session.flush()

    async def summary(self, *, month_start: date, today: date) -> dict[str, Any]:
        open_statuses = list(OPEN_TASK_STATUSES)
        stmt = select(
            func.count(),
            func.count().filter(WorkTask.status == TaskStatus.PENDING),
            func.count().filter(WorkTask.status == TaskStatus.IN_PROGRESS),
            func.count().filter(
                and_(WorkTask.status.in_(open_statuses), WorkTask.due_on < today)
            ),
            func.count().filter(
                and_(
                    WorkTask.completed_at.is_not(None),
                    WorkTask.completed_at >= month_start,
                )
            ),
            func.count().filter(WorkTask.status == TaskStatus.COMPLETED),
            func.coalesce(
                func.sum(WorkTask.actual_cost).filter(
                    and_(
                        WorkTask.completed_at.is_not(None),
                        WorkTask.completed_at >= month_start,
                    )
                ),
                0,
            ),
        ).select_from(WorkTask)
        if self.department is not None:
            stmt = stmt.where(WorkTask.department == self.department)

        row = (await self.session.execute(stmt)).first()
        total, pending, running, overdue, done, awaiting, cost = row or (0, 0, 0, 0, 0, 0, 0)
        return {
            "total": int(total or 0),
            "pending": int(pending or 0),
            "in_progress": int(running or 0),
            "overdue": int(overdue or 0),
            "completed_this_month": int(done or 0),
            "awaiting_verification": int(awaiting or 0),
            "cost_this_month": Decimal(str(cost or 0)),
        }


# --------------------------------------------------------------------------- #
# Visitors
# --------------------------------------------------------------------------- #


class VisitorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, visitor_id: uuid.UUID) -> Visitor | None:
        return await self.session.get(Visitor, visitor_id)

    async def get_by_pass_code(self, code: str) -> Visitor | None:
        """Resolves a code to the one live pass that holds it."""
        return await self.session.scalar(
            select(Visitor).where(
                func.upper(Visitor.pass_code) == code.upper(),
                Visitor.status.in_(
                    [
                        VisitorStatus.EXPECTED,
                        VisitorStatus.AWAITING_APPROVAL,
                        VisitorStatus.APPROVED,
                        VisitorStatus.CHECKED_IN,
                    ]
                ),
            )
        )

    async def code_in_use(self, code: str) -> bool:
        return (await self.get_by_pass_code(code)) is not None

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        status: str | None = None,
        visitor_type: str | None = None,
        flat_id: uuid.UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        on_premises_only: bool = False,
        only_flat_ids: Sequence[uuid.UUID] | None = None,
    ) -> tuple[Sequence[Visitor], int]:
        stmt = select(Visitor)
        if q:
            needle = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Visitor.visitor_name).like(needle),
                    func.lower(func.coalesce(Visitor.vehicle_number, "")).like(needle),
                    func.lower(func.coalesce(Visitor.pass_code, "")).like(needle),
                )
            )
        if status:
            stmt = stmt.where(Visitor.status == status)
        if visitor_type:
            stmt = stmt.where(Visitor.visitor_type == visitor_type)
        if flat_id is not None:
            stmt = stmt.where(Visitor.flat_id == flat_id)
        if from_date:
            stmt = stmt.where(Visitor.created_at >= from_date)
        if to_date:
            stmt = stmt.where(Visitor.created_at < to_date + timedelta(days=1))
        if on_premises_only:
            stmt = stmt.where(Visitor.status == VisitorStatus.CHECKED_IN)
        stmt = _restrict(stmt, Visitor.flat_id, only_flat_ids)

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(Visitor.created_at.desc()).offset((page - 1) * limit).limit(limit)
        )
        return list(rows), total

    async def create(self, visitor: Visitor) -> Visitor:
        self.session.add(visitor)
        await self.session.flush()
        return visitor

    async def on_premises(self, limit: int = 50) -> Sequence[Visitor]:
        rows = await self.session.scalars(
            select(Visitor)
            .where(Visitor.status == VisitorStatus.CHECKED_IN)
            .order_by(Visitor.checked_in_at.desc())
            .limit(limit)
        )
        return list(rows)

    async def summary(self, *, day_start: datetime) -> dict[str, int]:
        row = (
            await self.session.execute(
                select(
                    func.count().filter(Visitor.status == VisitorStatus.CHECKED_IN),
                    func.count().filter(
                        and_(
                            Visitor.status.in_(
                                [VisitorStatus.EXPECTED, VisitorStatus.APPROVED]
                            ),
                            Visitor.expected_from.is_not(None),
                            Visitor.expected_from >= day_start,
                            Visitor.expected_from < day_start + timedelta(days=1),
                        )
                    ),
                    func.count().filter(Visitor.status == VisitorStatus.AWAITING_APPROVAL),
                    func.count().filter(
                        and_(
                            Visitor.checked_in_at.is_not(None),
                            Visitor.checked_in_at >= day_start,
                        )
                    ),
                    func.count().filter(
                        and_(
                            Visitor.status == VisitorStatus.DENIED,
                            Visitor.updated_at >= day_start,
                        )
                    ),
                ).select_from(Visitor)
            )
        ).first()
        inside, expected, awaiting, entries, denied = row or (0, 0, 0, 0, 0)
        return {
            "on_premises": int(inside or 0),
            "expected_today": int(expected or 0),
            "awaiting_approval": int(awaiting or 0),
            "entries_today": int(entries or 0),
            "denied_today": int(denied or 0),
        }

    async def matching_pre_approval(
        self,
        *,
        flat_id: uuid.UUID,
        visitor_type: VisitorType,
        company: str | None,
        at: datetime,
    ) -> Visitor | None:
        """An open pre-approval that covers someone arriving now without a code.

        A delivery rider does not carry the resident's pass code, so a
        pre-approval for "a Swiggy delivery tonight" has to be matched on what
        the guard can see: the flat, the kind of visitor and, if the resident
        named one, the company. A pre-approval that names a company admits
        only that company.
        """
        stmt = select(Visitor).where(
            Visitor.flat_id == flat_id,
            Visitor.visitor_type == visitor_type,
            Visitor.status == VisitorStatus.EXPECTED,
            Visitor.expected_from <= at,
            Visitor.expected_to >= at,
        )
        needle = (company or "").strip().lower()
        stmt = stmt.where(
            or_(
                func.coalesce(func.btrim(Visitor.company), "") == "",
                func.lower(func.btrim(Visitor.company)) == needle,
            )
            if needle
            else func.coalesce(func.btrim(Visitor.company), "") == ""
        )
        # The narrowest window first: tonight's food order before an all-week
        # "any courier" pass.
        return await self.session.scalar(
            stmt.order_by(Visitor.expected_to - Visitor.expected_from).limit(1)
        )

    async def stale_expected(self, cutoff: datetime, limit: int = 500) -> Sequence[Visitor]:
        """Passes nobody will use any more.

        Pre-approvals whose window has closed, and walk-ups nobody answered
        within ``UNANSWERED_WALK_UP_HOURS`` — the delivery rider who was turned
        back at midnight is not still standing at the gate the next morning.
        """
        rows = await self.session.scalars(
            select(Visitor)
            .where(
                Visitor.status.in_(
                    [
                        VisitorStatus.EXPECTED,
                        VisitorStatus.APPROVED,
                        VisitorStatus.AWAITING_APPROVAL,
                    ]
                ),
                or_(
                    and_(Visitor.expected_to.is_not(None), Visitor.expected_to < cutoff),
                    and_(
                        Visitor.expected_to.is_(None),
                        Visitor.status == VisitorStatus.AWAITING_APPROVAL,
                        Visitor.created_at
                        < cutoff - timedelta(hours=UNANSWERED_WALK_UP_HOURS),
                    ),
                ),
            )
            .limit(limit)
        )
        return list(rows)


# --------------------------------------------------------------------------- #
# Security incidents
# --------------------------------------------------------------------------- #


class IncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, incident_id: uuid.UUID) -> SecurityIncident | None:
        return await self.session.get(SecurityIncident, incident_id)

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        open_only: bool = False,
    ) -> tuple[Sequence[SecurityIncident], int]:
        stmt = select(SecurityIncident)
        if q:
            stmt = stmt.where(func.lower(SecurityIncident.title).like(f"%{q.lower()}%"))
        if status:
            stmt = stmt.where(SecurityIncident.status == status)
        if severity:
            stmt = stmt.where(SecurityIncident.severity == severity)
        if from_date:
            stmt = stmt.where(SecurityIncident.occurred_at >= from_date)
        if to_date:
            stmt = stmt.where(
                SecurityIncident.occurred_at < to_date + timedelta(days=1)
            )
        if open_only:
            stmt = stmt.where(
                SecurityIncident.status.in_(
                    [IncidentStatus.REPORTED, IncidentStatus.INVESTIGATING]
                )
            )

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(SecurityIncident.occurred_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total

    async def create(self, incident: SecurityIncident) -> SecurityIncident:
        self.session.add(incident)
        await self.session.flush()
        return incident

    async def summary(self, *, month_start: date) -> dict[str, int]:
        row = (
            await self.session.execute(
                select(
                    func.count().filter(
                        SecurityIncident.status.in_(
                            [IncidentStatus.REPORTED, IncidentStatus.INVESTIGATING]
                        )
                    ),
                    func.count().filter(
                        and_(
                            SecurityIncident.severity == "CRITICAL",
                            SecurityIncident.status.in_(
                                [IncidentStatus.REPORTED, IncidentStatus.INVESTIGATING]
                            ),
                        )
                    ),
                    func.count().filter(SecurityIncident.occurred_at >= month_start),
                ).select_from(SecurityIncident)
            )
        ).first()
        open_count, critical, this_month = row or (0, 0, 0)
        return {
            "open_incidents": int(open_count or 0),
            "critical_incidents": int(critical or 0),
            "incidents_this_month": int(this_month or 0),
        }

    async def recent(self, limit: int = 5) -> Sequence[SecurityIncident]:
        rows = await self.session.scalars(
            select(SecurityIncident)
            .order_by(SecurityIncident.occurred_at.desc())
            .limit(limit)
        )
        return list(rows)
