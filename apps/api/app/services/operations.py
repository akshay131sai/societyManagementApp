"""Complaint, work, visitor and incident services.

Four policies run through the whole module.

* **The workflow is a table, not a chain of ifs.** Every status move is checked
  against ``COMPLAINT_TRANSITIONS`` / ``TASK_TRANSITIONS`` /
  ``VISITOR_TRANSITIONS`` before anything else happens, and the error names the
  moves that *are* legal. Adding a status is a change to one dict.

* **Owner scoping decides rows, permissions decide capability.** A resident
  holds ``complaint.read`` and sees their own tickets plus the common-area
  ones; a neighbour's ticket is a 404, not a 403, so probing tells them
  nothing. The narrowing comes from ``Principal.is_scoped_to_own``, never from
  a role check.

* **A side effect is part of the move.** Resolving a ticket writes the
  timestamp, the timeline entry and the resident's notification in the same
  transaction as the status. There is no path that changes one without the
  others, because there is no path that changes the status directly.

* **The gate log is append-only in spirit.** A visitor row moves forward
  through its states and never backwards; a mistake at the gate is corrected by
  a new entry under the name of whoever made it.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.permissions import Permission
from app.models.tenant import (
    COMPLAINT_TRANSITIONS,
    OPEN_COMPLAINT_STATUSES,
    RECURRENCE_DAYS,
    RECURRENCE_MONTHS,
    TASK_TRANSITIONS,
    VISITOR_TRANSITIONS,
    Complaint,
    ComplaintCategory,
    ComplaintComment,
    ComplaintStatus,
    Department,
    IncidentStatus,
    Priority,
    Recurrence,
    SecurityIncident,
    TaskStatus,
    Visitor,
    VisitorStatus,
    VisitorType,
    WorkSchedule,
    WorkTask,
)
from app.repositories.operations import (
    ComplaintRepository,
    IncidentRepository,
    ScheduleGenerationRepository,
    VisitorRepository,
    WorkScheduleRepository,
    WorkTaskRepository,
)
from app.repositories.recipients import RecipientRepository
from app.repositories.structure import FlatRepository
from app.schemas.operations import (
    ComplaintAssign,
    ComplaintCommentCreate,
    ComplaintCreate,
    ComplaintRating,
    ComplaintTransition,
    ComplaintUpdate,
    IncidentCreate,
    IncidentUpdate,
    VisitorCheckIn,
    VisitorDecision,
    VisitorGateEntry,
    VisitorGuardDecision,
    VisitorPreApprove,
    WorkScheduleCreate,
    WorkScheduleUpdate,
    WorkTaskCreate,
    WorkTaskProgress,
    WorkTaskUpdate,
)
from app.services.audit import AuditService, diff
from app.services.notifications import Category, NotificationService

log = structlog.get_logger(__name__)


class AuditAction:
    COMPLAINT_RAISED = "COMPLAINT_RAISED"
    COMPLAINT_UPDATED = "COMPLAINT_UPDATED"
    COMPLAINT_ASSIGNED = "COMPLAINT_ASSIGNED"
    COMPLAINT_TRANSITIONED = "COMPLAINT_TRANSITIONED"
    COMPLAINT_RATED = "COMPLAINT_RATED"
    COMPLAINT_COMMENTED = "COMPLAINT_COMMENTED"
    WORK_SCHEDULE_CREATED = "WORK_SCHEDULE_CREATED"
    WORK_SCHEDULE_UPDATED = "WORK_SCHEDULE_UPDATED"
    WORK_TASK_CREATED = "WORK_TASK_CREATED"
    WORK_TASK_UPDATED = "WORK_TASK_UPDATED"
    WORK_TASK_PROGRESSED = "WORK_TASK_PROGRESSED"
    WORK_TASKS_GENERATED = "WORK_TASKS_GENERATED"
    VISITOR_PRE_APPROVED = "VISITOR_PRE_APPROVED"
    VISITOR_LOGGED = "VISITOR_LOGGED"
    VISITOR_DECIDED = "VISITOR_DECIDED"
    VISITOR_CHECKED_IN = "VISITOR_CHECKED_IN"
    VISITOR_CHECKED_OUT = "VISITOR_CHECKED_OUT"
    INCIDENT_REPORTED = "INCIDENT_REPORTED"
    INCIDENT_UPDATED = "INCIDENT_UPDATED"


SLA_HOURS: dict[ComplaintCategory, int] = {
    ComplaintCategory.LIFT: 4,
    ComplaintCategory.ELECTRICAL: 8,
    ComplaintCategory.WATER_SUPPLY: 8,
    ComplaintCategory.SECURITY: 4,
    ComplaintCategory.PLUMBING: 24,
    ComplaintCategory.HOUSEKEEPING: 24,
    ComplaintCategory.COMMON_AREA: 48,
    ComplaintCategory.PARKING: 48,
    ComplaintCategory.NOISE: 24,
    ComplaintCategory.BILLING: 72,
    ComplaintCategory.OTHER: 48,
}
"""How long the society has, by category.

A stuck lift is a different promise from a billing query, and one flat number
for everything would be a promise nobody keeps. Urgency shortens it further —
see ``PRIORITY_SLA_FACTOR``.
"""

PRIORITY_SLA_FACTOR: dict[Priority, Decimal] = {
    Priority.URGENT: Decimal("0.25"),
    Priority.HIGH: Decimal("0.5"),
    Priority.MEDIUM: Decimal("1"),
    Priority.LOW: Decimal("2"),
}

DEPARTMENT_FOR_CATEGORY: dict[ComplaintCategory, Department] = {
    ComplaintCategory.PLUMBING: Department.MAINTENANCE,
    ComplaintCategory.ELECTRICAL: Department.MAINTENANCE,
    ComplaintCategory.LIFT: Department.MAINTENANCE,
    ComplaintCategory.WATER_SUPPLY: Department.MAINTENANCE,
    ComplaintCategory.HOUSEKEEPING: Department.HOUSEKEEPING,
    ComplaintCategory.COMMON_AREA: Department.HOUSEKEEPING,
}
"""A default routing, applied when nobody has assigned the ticket yet.

Categories missing from this map (billing, noise, security) have no obvious
owner and stay unassigned so a human decides.
"""

AUTO_CLOSE_DAYS = 7
"""How long a resolved ticket waits for the resident before closing itself."""

PASS_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
"""No 0/O, and none of 1/I/L. The code is read out over a phone to a guard.

L was previously left in: the exclusion list said "1/I/l" with a lowercase l,
which the alphabet being all-uppercase made a no-op. Dropping it costs one
character of a 32-symbol set — 31^6 is still ~887 million codes — and removes
the last glyph a guard could hear or read as a one.
"""

CODELESS_PRE_APPROVAL_TYPES = frozenset({VisitorType.DELIVERY, VisitorType.CAB})
"""Visitors who arrive without the resident's pass code.

A guest is told the code; a delivery rider or a cab driver never is. For these
types the gate entry is matched against the flat's open pre-approvals instead,
so "let tonight's Swiggy order up" works at midnight with nobody awake.
"""

APPROVED_VIA_APP = "APP"
APPROVED_VIA_PHONE = "PHONE"
APPROVED_VIA_GUARD = "GUARD"


def _now() -> datetime:
    return datetime.now(UTC)


def _flat_number(obj: Any) -> str | None:
    flat = getattr(obj, "flat", None)
    return getattr(flat, "flat_number", None) if flat is not None else None


def _building_name(obj: Any) -> str | None:
    building = getattr(obj, "building", None)
    return getattr(building, "name", None) if building is not None else None


def _assignee_name(obj: Any) -> str | None:
    assignee = getattr(obj, "assignee", None)
    return getattr(assignee, "full_name", None) if assignee is not None else None


def _sla_due(category: ComplaintCategory, priority: Priority, *, at: datetime) -> datetime:
    hours = Decimal(SLA_HOURS.get(category, 48)) * PRIORITY_SLA_FACTOR.get(
        priority, Decimal("1")
    )
    # A quarter of four hours is one hour; nothing is ever promised in minutes.
    return at + timedelta(hours=float(max(hours, Decimal("1"))))


def _add_months(start: date, months: int) -> date:
    """Calendar-month arithmetic that survives month ends.

    The 31st plus one month is the 30th in April, not the 1st of May: a lift
    service scheduled for month end should stay at month end rather than
    walking forward a day each quarter.
    """
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = start.day
    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, day)


def advance(current: date, recurrence: Recurrence) -> date:
    """The next occurrence after ``current``."""
    if recurrence in RECURRENCE_MONTHS:
        return _add_months(current, RECURRENCE_MONTHS[recurrence])
    return current + timedelta(days=RECURRENCE_DAYS[recurrence])


# --------------------------------------------------------------------------- #
# Complaints
# --------------------------------------------------------------------------- #


def _complaint_dict(c: Complaint, *, comment_count: int = 0) -> dict[str, Any]:
    now = _now()
    created = c.created_at or now
    reference = c.resolved_at or now
    return {
        "id": c.id,
        "ticket_number": c.ticket_number,
        "flat_id": c.flat_id,
        "flat_number": _flat_number(c),
        "raised_by": c.raised_by,
        "raised_by_name": c.raised_by_name,
        "title": c.title,
        "description": c.description,
        "category": c.category,
        "priority": c.priority,
        "status": c.status,
        "location": c.location,
        "assigned_to": c.assigned_to,
        "assignee_name": _assignee_name(c),
        "assigned_department": c.assigned_department,
        "due_by": c.due_by,
        "is_overdue": bool(
            c.due_by is not None
            and c.status in OPEN_COMPLAINT_STATUSES
            and c.due_by < now
        ),
        "acknowledged_at": c.acknowledged_at,
        "resolved_at": c.resolved_at,
        "closed_at": c.closed_at,
        "resolution_notes": c.resolution_notes,
        "reopen_count": c.reopen_count,
        "rating": c.rating,
        "rating_comment": c.rating_comment,
        "comment_count": comment_count,
        "age_hours": max(int((reference - created).total_seconds() // 3600), 0),
        "created_at": created,
        "updated_at": c.updated_at or created,
    }


def _comment_dict(c: ComplaintComment) -> dict[str, Any]:
    return {
        "id": c.id,
        "author_id": c.author_id,
        "author_name": c.author_name,
        "body": c.body,
        "is_internal": c.is_internal,
        "is_system": c.is_system,
        "created_at": c.created_at,
    }


class ComplaintService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = ComplaintRepository(tenant)
        self.recipients = RecipientRepository(tenant)
        self.notifications = NotificationService(tenant)

    # -- scoping ------------------------------------------------------------ #

    def _owner_scope(self, principal: Principal) -> list[uuid.UUID] | None:
        if principal.is_scoped_to_own(Permission.COMPLAINT_READ):
            return sorted(principal.flat_ids)
        return None

    def _can_manage(self, principal: Principal) -> bool:
        return principal.has(Permission.COMPLAINT_MANAGE)

    async def _load(self, complaint_id: uuid.UUID, principal: Principal) -> Complaint:
        complaint = await self.repo.get(complaint_id)
        if complaint is None:
            raise NotFoundError("Complaint")
        scope = self._owner_scope(principal)
        # A common-area ticket has no flat and is visible to everyone; a
        # neighbour's is invisible, and says "not found" rather than "forbidden".
        if scope is not None and complaint.flat_id is not None and complaint.flat_id not in scope:
            raise NotFoundError("Complaint")
        return complaint

    # -- reads -------------------------------------------------------------- #

    async def list(
        self,
        principal: Principal,
        *,
        page: int,
        limit: int,
        q: str | None = None,
        status: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        assigned_to: uuid.UUID | None = None,
        flat_id: uuid.UUID | None = None,
        open_only: bool = False,
        overdue_only: bool = False,
        unassigned_only: bool = False,
        mine_only: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        if mine_only and principal.tenant_user_id is not None:
            assigned_to = principal.tenant_user_id

        rows, total = await self.repo.list(
            page=page,
            limit=limit,
            q=q,
            status=status,
            category=category,
            priority=priority,
            assigned_to=assigned_to,
            flat_id=flat_id,
            open_only=open_only,
            overdue_only=overdue_only,
            unassigned_only=unassigned_only,
            only_flat_ids=self._owner_scope(principal),
        )
        counts = await self.repo.comment_counts(
            [c.id for c in rows], include_internal=self._can_manage(principal)
        )
        return [
            _complaint_dict(c, comment_count=counts.get(c.id, 0)) for c in rows
        ], total

    async def get(self, complaint_id: uuid.UUID, principal: Principal) -> dict[str, Any]:
        await self._load(complaint_id, principal)
        complaint = await self.repo.get_with_comments(complaint_id)
        assert complaint is not None

        internal_ok = self._can_manage(principal)
        comments = [
            _comment_dict(c) for c in complaint.comments if internal_ok or not c.is_internal
        ]
        data = _complaint_dict(complaint, comment_count=len(comments))
        data["comments"] = comments
        data["allowed_transitions"] = sorted(
            self._allowed(complaint, principal), key=lambda s: s.value
        )
        return data

    def _allowed(self, complaint: Complaint, principal: Principal) -> set[ComplaintStatus]:
        """What this principal may do next.

        Staff drive the ticket forward; the resident who raised it owns exactly
        two moves — accept the fix, or say it is not fixed. Handing a resident
        "In progress" would be a button that lies about who is doing the work.
        """
        legal = set(COMPLAINT_TRANSITIONS.get(complaint.status, frozenset()))
        if self._can_manage(principal):
            return legal
        owner_moves = {ComplaintStatus.CLOSED, ComplaintStatus.REOPENED}
        is_raiser = complaint.raised_by is not None and (
            complaint.raised_by == principal.tenant_user_id
        )
        return legal & owner_moves if is_raiser else set()

    async def summary(self, principal: Principal) -> dict[str, Any]:
        today = date.today()
        month_start = today.replace(day=1)
        summary = await self.repo.summary(month_start=month_start)
        summary["by_status"] = await self.repo.counts_by(Complaint.status)
        summary["by_category"] = await self.repo.counts_by(Complaint.category)
        summary["by_priority"] = await self.repo.counts_by(Complaint.priority)
        return summary

    # -- writes ------------------------------------------------------------- #

    async def create(
        self, payload: ComplaintCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        flat_id = payload.flat_id
        scope = self._owner_scope(principal)
        if scope is not None:
            # A resident files against their own flat, full stop. Taking the id
            # from the body would let one be filed in a neighbour's name.
            flat_id = scope[0] if scope else None
        elif flat_id is not None:
            if await FlatRepository(self.tenant).get(flat_id) is None:
                raise NotFoundError("Flat")

        now = _now()
        complaint = Complaint(
            flat_id=flat_id,
            raised_by=principal.tenant_user_id,
            raised_by_name=principal.display_name or principal.email,
            title=payload.title,
            description=payload.description,
            category=payload.category,
            priority=payload.priority,
            location=payload.location,
            status=ComplaintStatus.OPEN,
            due_by=_sla_due(payload.category, payload.priority, at=now),
            assigned_department=DEPARTMENT_FOR_CATEGORY.get(payload.category),
        )
        await self.repo.create(complaint)
        # The ticket number is a database default, so it only exists after the
        # INSERT has actually run.
        await self.tenant.refresh(complaint)

        await self._timeline(
            complaint,
            f"Ticket raised by {complaint.raised_by_name}.",
            principal,
            system=True,
        )

        await self.notifications.notify(
            await self.recipients.users_with_permission(Permission.COMPLAINT_MANAGE),
            category=Category.COMPLAINT_RAISED,
            title=f"New complaint: {complaint.title}",
            body=f"{complaint.ticket_number} · {complaint.category.value.replace('_', ' ').title()}",
            link=f"/app/complaints/{complaint.id}",
            payload={"complaint_id": str(complaint.id), "priority": complaint.priority.value},
            exclude=principal.tenant_user_id,
        )

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.COMPLAINT_RAISED,
            principal=principal,
            target_type="complaints",
            target_id=complaint.id,
            changes={"after": {"ticket": complaint.ticket_number, "title": complaint.title}},
            request_id=request_id,
        )
        return _complaint_dict(complaint)

    async def update(
        self,
        complaint_id: uuid.UUID,
        payload: ComplaintUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        complaint = await self._load(complaint_id, principal)
        if not self._can_manage(principal) and complaint.raised_by != principal.tenant_user_id:
            raise NotFoundError("Complaint")
        if complaint.status in (ComplaintStatus.CLOSED, ComplaintStatus.REJECTED):
            raise ConflictError(
                "This ticket is closed. Reopen it before editing, so the change "
                "is visible to everyone who saw the resolution."
            )

        before = _complaint_dict(complaint)
        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(complaint, key, value)
        await self.tenant.flush()
        await self.tenant.refresh(complaint)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.COMPLAINT_UPDATED,
            principal=principal,
            target_type="complaints",
            target_id=complaint.id,
            changes=diff(
                {k: str(v) for k, v in before.items()},
                {k: str(v) for k, v in _complaint_dict(complaint).items()},
            ),
            request_id=request_id,
        )
        return _complaint_dict(complaint)

    async def assign(
        self,
        complaint_id: uuid.UUID,
        payload: ComplaintAssign,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        complaint = await self._load(complaint_id, principal)
        if payload.assigned_to is not None and not await self.recipients.is_active_user(
            payload.assigned_to
        ):
            raise NotFoundError("User")

        complaint.assigned_to = payload.assigned_to
        if payload.assigned_department is not None:
            complaint.assigned_department = payload.assigned_department
        # Assigning is an acknowledgement: somebody has looked at it.
        if complaint.acknowledged_at is None and payload.assigned_to is not None:
            complaint.acknowledged_at = _now()
            if complaint.status is ComplaintStatus.OPEN:
                complaint.status = ComplaintStatus.ACKNOWLEDGED
        await self.tenant.flush()

        assignee_name = await self.recipients.display_name(payload.assigned_to)
        note = payload.note or (
            f"Assigned to {assignee_name}." if assignee_name else "Unassigned."
        )
        await self._timeline(complaint, note, principal, system=True)

        if payload.assigned_to is not None:
            await self.notifications.notify(
                [payload.assigned_to],
                category=Category.COMPLAINT_ASSIGNED,
                title=f"Assigned to you: {complaint.title}",
                body=complaint.ticket_number,
                link=f"/app/complaints/{complaint.id}",
                payload={"complaint_id": str(complaint.id)},
                exclude=principal.tenant_user_id,
            )

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.COMPLAINT_ASSIGNED,
            principal=principal,
            target_type="complaints",
            target_id=complaint.id,
            changes={"after": {"assigned_to": str(payload.assigned_to)}},
            request_id=request_id,
        )
        await self.tenant.refresh(complaint)
        return _complaint_dict(complaint)

    async def transition(
        self,
        complaint_id: uuid.UUID,
        payload: ComplaintTransition,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        complaint = await self._load(complaint_id, principal)
        allowed = self._allowed(complaint, principal)
        if payload.status not in allowed:
            legal = ", ".join(sorted(s.value for s in allowed)) or "nothing"
            raise ConflictError(
                f"A ticket that is {complaint.status.value} cannot become "
                f"{payload.status.value}. From here you can move it to: {legal}."
            )

        now = _now()
        previous = complaint.status
        complaint.status = payload.status

        if payload.status is ComplaintStatus.ACKNOWLEDGED and complaint.acknowledged_at is None:
            complaint.acknowledged_at = now
        elif payload.status in (ComplaintStatus.RESOLVED, ComplaintStatus.REJECTED):
            complaint.resolved_at = now
            complaint.resolution_notes = payload.note
        elif payload.status is ComplaintStatus.CLOSED:
            complaint.closed_at = now
        elif payload.status is ComplaintStatus.REOPENED:
            complaint.reopen_count += 1
            # The clock restarts, because the promise does.
            complaint.resolved_at = None
            complaint.closed_at = None
            complaint.due_by = _sla_due(complaint.category, complaint.priority, at=now)

        await self.tenant.flush()

        await self._timeline(
            complaint,
            payload.note
            or f"Status changed from {previous.value} to {payload.status.value}.",
            principal,
            system=True,
        )
        await self._announce_transition(complaint, previous, principal)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.COMPLAINT_TRANSITIONED,
            principal=principal,
            target_type="complaints",
            target_id=complaint.id,
            changes={"before": {"status": previous.value}, "after": {"status": payload.status.value}},
            request_id=request_id,
        )
        await self.tenant.refresh(complaint)
        return _complaint_dict(complaint)

    async def _announce_transition(
        self, complaint: Complaint, previous: ComplaintStatus, principal: Principal
    ) -> None:
        residents = await self.recipients.users_for_flat(complaint.flat_id)
        if complaint.raised_by is not None and complaint.raised_by not in residents:
            residents.append(complaint.raised_by)

        if complaint.status in (ComplaintStatus.RESOLVED, ComplaintStatus.REJECTED):
            verb = "resolved" if complaint.status is ComplaintStatus.RESOLVED else "closed"
            await self.notifications.notify(
                residents,
                category=Category.COMPLAINT_RESOLVED,
                title=f"Your complaint was {verb}",
                body=f"{complaint.ticket_number} · {complaint.title}",
                link=f"/app/complaints/{complaint.id}",
                payload={"complaint_id": str(complaint.id)},
                exclude=principal.tenant_user_id,
            )
        elif complaint.status is ComplaintStatus.REOPENED:
            staff = await self.recipients.users_with_permission(Permission.COMPLAINT_MANAGE)
            if complaint.assigned_to is not None:
                staff.append(complaint.assigned_to)
            await self.notifications.notify(
                staff,
                category=Category.COMPLAINT_UPDATED,
                title=f"Reopened: {complaint.title}",
                body=f"{complaint.ticket_number} · reopened {complaint.reopen_count}×",
                link=f"/app/complaints/{complaint.id}",
                payload={"complaint_id": str(complaint.id)},
                exclude=principal.tenant_user_id,
            )
        elif previous != complaint.status:
            await self.notifications.notify(
                residents,
                category=Category.COMPLAINT_UPDATED,
                title=f"{complaint.ticket_number} is now {complaint.status.value.replace('_', ' ').lower()}",
                body=complaint.title,
                link=f"/app/complaints/{complaint.id}",
                payload={"complaint_id": str(complaint.id)},
                exclude=principal.tenant_user_id,
            )

    async def rate(
        self,
        complaint_id: uuid.UUID,
        payload: ComplaintRating,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        complaint = await self._load(complaint_id, principal)
        if complaint.raised_by != principal.tenant_user_id:
            raise ConflictError("Only the resident who raised a ticket can rate it.")
        if complaint.status not in (ComplaintStatus.RESOLVED, ComplaintStatus.CLOSED):
            raise ConflictError("Rate the ticket once it has been resolved.")

        complaint.rating = payload.rating
        complaint.rating_comment = payload.comment
        await self.tenant.flush()
        # ``updated_at`` carries an onupdate, so the flush expires it. Reading
        # it back to build the response would be a lazy load inside async code.
        await self.tenant.refresh(complaint)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.COMPLAINT_RATED,
            principal=principal,
            target_type="complaints",
            target_id=complaint.id,
            changes={"after": {"rating": payload.rating}},
            request_id=request_id,
        )
        return _complaint_dict(complaint)

    async def comment(
        self,
        complaint_id: uuid.UUID,
        payload: ComplaintCommentCreate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        complaint = await self._load(complaint_id, principal)
        if payload.is_internal and not self._can_manage(principal):
            raise ValidationError(
                "An internal note is only visible to staff, so only staff can write one."
            )

        comment = await self._timeline(
            complaint, payload.body, principal, internal=payload.is_internal
        )

        if not payload.is_internal:
            audience = await self.recipients.users_for_flat(complaint.flat_id)
            if complaint.assigned_to is not None:
                audience.append(complaint.assigned_to)
            if complaint.raised_by is not None:
                audience.append(complaint.raised_by)
            await self.notifications.notify(
                audience,
                category=Category.COMPLAINT_COMMENT,
                title=f"New reply on {complaint.ticket_number}",
                body=payload.body[:140],
                link=f"/app/complaints/{complaint.id}",
                payload={"complaint_id": str(complaint.id)},
                exclude=principal.tenant_user_id,
            )

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.COMPLAINT_COMMENTED,
            principal=principal,
            target_type="complaints",
            target_id=complaint.id,
            request_id=request_id,
        )
        return _comment_dict(comment)

    async def _timeline(
        self,
        complaint: Complaint,
        body: str,
        principal: Principal,
        *,
        internal: bool = False,
        system: bool = False,
    ) -> ComplaintComment:
        comment = ComplaintComment(
            complaint_id=complaint.id,
            author_id=principal.tenant_user_id,
            author_name=principal.display_name or principal.email,
            body=body,
            is_internal=internal,
            is_system=system,
        )
        await self.repo.add_comment(comment)
        await self.tenant.refresh(comment)
        return comment

    # -- maintenance sweeps ------------------------------------------------- #

    async def auto_close_resolved(self, *, days: int = AUTO_CLOSE_DAYS) -> int:
        """Close tickets the resident never got back to.

        Without this, "open complaints" drifts upward forever and the number
        stops meaning anything. The ticket keeps its resolution notes, so a
        resident who disagrees can still reopen it.
        """
        cutoff = _now() - timedelta(days=days)
        stale = await self.repo.resolved_before(cutoff)
        for complaint in stale:
            complaint.status = ComplaintStatus.CLOSED
            complaint.closed_at = _now()
        if stale:
            await self.tenant.flush()
        return len(stale)

    async def escalate_overdue(self) -> int:
        """Tell the managers about tickets past their promised time."""
        overdue = await self.repo.overdue_open()
        if not overdue:
            return 0

        managers = await self.recipients.users_with_permission(Permission.COMPLAINT_MANAGE)
        for complaint in overdue[:50]:
            audience = list(managers)
            if complaint.assigned_to is not None:
                audience.append(complaint.assigned_to)
            await self.notifications.notify(
                audience,
                category=Category.COMPLAINT_UPDATED,
                title=f"Overdue: {complaint.title}",
                body=f"{complaint.ticket_number} passed its {complaint.priority.value.lower()} target.",
                link=f"/app/complaints/{complaint.id}",
                payload={"complaint_id": str(complaint.id), "overdue": True},
            )
        return len(overdue)


# --------------------------------------------------------------------------- #
# Work schedules and tasks
# --------------------------------------------------------------------------- #


def _schedule_dict(s: WorkSchedule, *, open_tasks: int = 0) -> dict[str, Any]:
    return {
        "id": s.id,
        "department": s.department,
        "title": s.title,
        "description": s.description,
        "area": s.area,
        "building_id": s.building_id,
        "building_name": _building_name(s),
        "recurrence": s.recurrence,
        "priority": s.priority,
        "assigned_to": s.assigned_to,
        "assignee_name": _assignee_name(s),
        "estimated_cost": s.estimated_cost,
        "vendor_name": s.vendor_name,
        "vendor_phone": s.vendor_phone,
        "starts_on": s.starts_on,
        "next_due_on": s.next_due_on,
        "ends_on": s.ends_on,
        "lead_days": s.lead_days,
        "is_active": s.is_active,
        "open_tasks": open_tasks,
        "created_at": s.created_at,
    }


def _task_dict(t: WorkTask, *, allowed: list[TaskStatus] | None = None) -> dict[str, Any]:
    schedule = t.schedule if "schedule" in t.__dict__ else None
    return {
        "id": t.id,
        "department": t.department,
        "schedule_id": t.schedule_id,
        "schedule_title": getattr(schedule, "title", None),
        "complaint_id": t.complaint_id,
        "title": t.title,
        "description": t.description,
        "area": t.area,
        "building_id": t.building_id,
        "building_name": _building_name(t),
        "status": t.status,
        "priority": t.priority,
        "assigned_to": t.assigned_to,
        "assignee_name": _assignee_name(t),
        "due_on": t.due_on,
        "is_overdue": bool(
            t.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)
            and t.due_on < date.today()
        ),
        "started_at": t.started_at,
        "completed_at": t.completed_at,
        "verified_at": t.verified_at,
        "completion_notes": t.completion_notes,
        "actual_cost": t.actual_cost,
        "vendor_name": t.vendor_name,
        "allowed_transitions": allowed or [],
        "created_at": t.created_at,
    }


class WorkService:
    """Maintenance and housekeeping, from one implementation.

    The department is fixed at construction, exactly as ``ReadingService`` fixes
    the utility: two departments with identical workflows and different
    permissions are one service with a parameter, not two files that drift.
    """

    def __init__(self, tenant: AsyncSession, *, department: Department | str) -> None:
        self.tenant = tenant
        self.department = Department(department)
        self.schedules = WorkScheduleRepository(tenant, self.department)
        self.tasks = WorkTaskRepository(tenant, self.department)
        self.recipients = RecipientRepository(tenant)
        self.notifications = NotificationService(tenant)

        self.is_maintenance = self.department is Department.MAINTENANCE
        self.route = "maintenance" if self.is_maintenance else "housekeeping"
        self.manage_permission = (
            Permission.MAINTENANCE_MANAGE
            if self.is_maintenance
            else Permission.HOUSEKEEPING_MANAGE
        )
        self._label = "Maintenance" if self.is_maintenance else "Housekeeping"

    # -- schedules ---------------------------------------------------------- #

    async def list_schedules(
        self, *, page: int, limit: int, q: str | None = None, active_only: bool = True
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.schedules.list(
            page=page, limit=limit, q=q, active_only=active_only
        )
        counts = await self.schedules.open_task_counts([s.id for s in rows])
        return [_schedule_dict(s, open_tasks=counts.get(s.id, 0)) for s in rows], total

    async def create_schedule(
        self,
        payload: WorkScheduleCreate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if payload.assigned_to is not None and not await self.recipients.is_active_user(
            payload.assigned_to
        ):
            raise NotFoundError("User")

        schedule = WorkSchedule(
            department=self.department,
            next_due_on=payload.starts_on,
            **payload.model_dump(),
        )
        await self.schedules.create(schedule)
        await self.tenant.refresh(schedule)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.WORK_SCHEDULE_CREATED,
            principal=principal,
            target_type="work_schedules",
            target_id=schedule.id,
            changes={"after": {"title": schedule.title, "recurrence": schedule.recurrence.value}},
            request_id=request_id,
        )
        return _schedule_dict(schedule)

    async def update_schedule(
        self,
        schedule_id: uuid.UUID,
        payload: WorkScheduleUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        schedule = await self.schedules.get(schedule_id)
        if schedule is None:
            raise NotFoundError(f"{self._label} schedule")

        before = _schedule_dict(schedule)
        changes = payload.model_dump(exclude_unset=True)
        recurrence_changed = (
            "recurrence" in changes and changes["recurrence"] != schedule.recurrence
        )
        for key, value in changes.items():
            setattr(schedule, key, value)
        if recurrence_changed:
            # The old next-due date was computed under the old rhythm; keeping
            # it would mean a schedule changed to weekly still fires next month.
            schedule.next_due_on = max(schedule.next_due_on, date.today())
        await self.tenant.flush()
        await self.tenant.refresh(schedule)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.WORK_SCHEDULE_UPDATED,
            principal=principal,
            target_type="work_schedules",
            target_id=schedule.id,
            changes=diff(
                {k: str(v) for k, v in before.items()},
                {k: str(v) for k, v in _schedule_dict(schedule).items()},
            ),
            request_id=request_id,
        )
        return _schedule_dict(schedule)

    # -- tasks -------------------------------------------------------------- #

    def _allowed(self, task: WorkTask, principal: Principal) -> list[TaskStatus]:
        legal = set(TASK_TRANSITIONS.get(task.status, frozenset()))
        if not principal.has(self.manage_permission):
            # A worker moves their own task along but does not sign it off —
            # that is what makes VERIFIED mean anything.
            legal -= {TaskStatus.VERIFIED, TaskStatus.CANCELLED}
        return sorted(legal, key=lambda s: s.value)

    async def list_tasks(
        self,
        principal: Principal,
        *,
        page: int,
        limit: int,
        q: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        assigned_to: uuid.UUID | None = None,
        schedule_id: uuid.UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        open_only: bool = False,
        overdue_only: bool = False,
        mine_only: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        if mine_only and principal.tenant_user_id is not None:
            assigned_to = principal.tenant_user_id

        rows, total = await self.tasks.list(
            page=page,
            limit=limit,
            q=q,
            status=status,
            priority=priority,
            assigned_to=assigned_to,
            schedule_id=schedule_id,
            from_date=from_date,
            to_date=to_date,
            open_only=open_only,
            overdue_only=overdue_only,
        )
        return [_task_dict(t, allowed=self._allowed(t, principal)) for t in rows], total

    async def get_task(self, task_id: uuid.UUID, principal: Principal) -> dict[str, Any]:
        task = await self.tasks.get(task_id)
        if task is None:
            raise NotFoundError(f"{self._label} task")
        return _task_dict(task, allowed=self._allowed(task, principal))

    async def create_task(
        self,
        payload: WorkTaskCreate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if payload.assigned_to is not None and not await self.recipients.is_active_user(
            payload.assigned_to
        ):
            raise NotFoundError("User")
        if payload.complaint_id is not None:
            if await ComplaintRepository(self.tenant).get(payload.complaint_id) is None:
                raise NotFoundError("Complaint")

        task = WorkTask(department=self.department, **payload.model_dump())
        await self.tasks.create(task)
        await self.tenant.refresh(task)

        await self._announce_assignment(task, principal)
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.WORK_TASK_CREATED,
            principal=principal,
            target_type="work_tasks",
            target_id=task.id,
            changes={"after": {"title": task.title, "due_on": str(task.due_on)}},
            request_id=request_id,
        )
        return _task_dict(task, allowed=self._allowed(task, principal))

    async def update_task(
        self,
        task_id: uuid.UUID,
        payload: WorkTaskUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        task = await self.tasks.get(task_id)
        if task is None:
            raise NotFoundError(f"{self._label} task")
        if task.status in (TaskStatus.VERIFIED, TaskStatus.CANCELLED):
            raise ConflictError("A signed-off task cannot be edited.")

        before = _task_dict(task)
        previous_assignee = task.assigned_to
        changes = payload.model_dump(exclude_unset=True)
        if changes.get("assigned_to") is not None and not await self.recipients.is_active_user(
            changes["assigned_to"]
        ):
            raise NotFoundError("User")
        for key, value in changes.items():
            setattr(task, key, value)
        await self.tenant.flush()
        await self.tenant.refresh(task)

        if task.assigned_to is not None and task.assigned_to != previous_assignee:
            await self._announce_assignment(task, principal)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.WORK_TASK_UPDATED,
            principal=principal,
            target_type="work_tasks",
            target_id=task.id,
            changes=diff(
                {k: str(v) for k, v in before.items()},
                {k: str(v) for k, v in _task_dict(task).items()},
            ),
            request_id=request_id,
        )
        return _task_dict(task, allowed=self._allowed(task, principal))

    async def progress(
        self,
        task_id: uuid.UUID,
        payload: WorkTaskProgress,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        task = await self.tasks.get(task_id)
        if task is None:
            raise NotFoundError(f"{self._label} task")

        allowed = self._allowed(task, principal)
        if payload.status not in allowed:
            legal = ", ".join(s.value for s in allowed) or "nothing"
            raise ConflictError(
                f"A {task.status.value} task cannot become {payload.status.value}. "
                f"From here you can move it to: {legal}."
            )

        now = _now()
        previous = task.status
        task.status = payload.status
        if payload.notes:
            task.completion_notes = payload.notes
        if payload.actual_cost is not None:
            task.actual_cost = payload.actual_cost

        if payload.status is TaskStatus.IN_PROGRESS and task.started_at is None:
            task.started_at = now
        elif payload.status is TaskStatus.COMPLETED:
            task.completed_at = now
            task.completed_by = principal.tenant_user_id
            if task.started_at is None:
                # A short job done on the spot never had a separate start.
                task.started_at = now
        elif payload.status is TaskStatus.VERIFIED:
            task.verified_at = now
            task.verified_by = principal.tenant_user_id

        await self.tenant.flush()
        await self.tenant.refresh(task)
        await self._announce_progress(task, previous, principal)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.WORK_TASK_PROGRESSED,
            principal=principal,
            target_type="work_tasks",
            target_id=task.id,
            changes={
                "before": {"status": previous.value},
                "after": {"status": payload.status.value},
            },
            request_id=request_id,
        )
        return _task_dict(task, allowed=self._allowed(task, principal))

    async def _announce_assignment(self, task: WorkTask, principal: Principal) -> None:
        if task.assigned_to is None:
            return
        await self.notifications.notify(
            [task.assigned_to],
            category=Category.TASK_ASSIGNED,
            title=f"{self._label}: {task.title}",
            body=f"Due {task.due_on:%d %b %Y}",
            link=f"/app/{self.route}",
            payload={"task_id": str(task.id), "department": self.department.value},
            exclude=principal.tenant_user_id,
        )

    async def _announce_progress(
        self, task: WorkTask, previous: TaskStatus, principal: Principal
    ) -> None:
        if task.status is not TaskStatus.COMPLETED or previous is TaskStatus.COMPLETED:
            return
        await self.notifications.notify(
            await self.recipients.users_with_permission(self.manage_permission),
            category=Category.TASK_COMPLETED,
            title=f"{self._label} completed: {task.title}",
            body=task.completion_notes or None,
            link=f"/app/{self.route}",
            payload={"task_id": str(task.id)},
            exclude=principal.tenant_user_id,
        )

    async def summary(self) -> dict[str, Any]:
        today = date.today()
        summary = await self.tasks.summary(month_start=today.replace(day=1), today=today)
        summary["department"] = self.department
        summary["active_schedules"] = await self.schedules.active_count()
        return summary


class ScheduleGenerator:
    """Turns schedules into tasks.

    Runs from the nightly worker and from an explicit admin button, and is
    idempotent either way: the ``(schedule_id, due_on)`` unique index and the
    pre-read of existing occurrences mean running it twice on the same morning
    creates nothing the second time.
    """

    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = ScheduleGenerationRepository(tenant)

    async def run(
        self, *, on: date | None = None, principal: Principal | None = None
    ) -> dict[str, int]:
        today = on or date.today()
        due = await self.repo.due(on=today)
        if not due:
            return {
                "schedules_examined": 0,
                "tasks_created": 0,
                "schedules_advanced": 0,
                "skipped_existing": 0,
            }

        existing = await self.repo.existing_occurrences([s.id for s in due])
        tasks: list[WorkTask] = []
        advanced = 0
        skipped = 0

        for schedule in due:
            occurrence = schedule.next_due_on
            # A schedule left alone for months catches up rather than firing
            # once — but only for occurrences that are actually in the past, so
            # a long-dormant schedule cannot flood the board.
            guard = 0
            while occurrence - timedelta(days=schedule.lead_days) <= today and guard < 24:
                guard += 1
                if schedule.ends_on is not None and occurrence > schedule.ends_on:
                    break
                if (schedule.id, occurrence) in existing:
                    skipped += 1
                else:
                    tasks.append(
                        WorkTask(
                            department=schedule.department,
                            schedule_id=schedule.id,
                            title=schedule.title,
                            description=schedule.description,
                            area=schedule.area,
                            building_id=schedule.building_id,
                            priority=schedule.priority,
                            assigned_to=schedule.assigned_to,
                            due_on=occurrence,
                            vendor_name=schedule.vendor_name,
                        )
                    )
                occurrence = advance(occurrence, schedule.recurrence)

            if occurrence != schedule.next_due_on:
                schedule.next_due_on = occurrence
                advanced += 1
                if schedule.ends_on is not None and occurrence > schedule.ends_on:
                    schedule.is_active = False

        if tasks:
            await WorkTaskRepository(self.tenant).create_many(tasks)
        await self.tenant.flush()

        if principal is not None and tasks:
            await AuditService.tenant(
                self.tenant,
                action=AuditAction.WORK_TASKS_GENERATED,
                principal=principal,
                target_type="work_tasks",
                changes={"after": {"created": len(tasks)}},
            )

        log.info(
            "work.schedule.generated",
            examined=len(due),
            created=len(tasks),
            advanced=advanced,
        )
        return {
            "schedules_examined": len(due),
            "tasks_created": len(tasks),
            "schedules_advanced": advanced,
            "skipped_existing": skipped,
        }


# --------------------------------------------------------------------------- #
# Visitors
# --------------------------------------------------------------------------- #


def _visitor_dict(v: Visitor) -> dict[str, Any]:
    duration: int | None = None
    if v.checked_in_at is not None and v.checked_out_at is not None:
        duration = int((v.checked_out_at - v.checked_in_at).total_seconds() // 60)
    return {
        "id": v.id,
        "pass_code": v.pass_code,
        "flat_id": v.flat_id,
        "flat_number": _flat_number(v),
        "visitor_name": v.visitor_name,
        "visitor_phone": v.visitor_phone,
        "visitor_type": v.visitor_type,
        "company": v.company,
        "purpose": v.purpose,
        "accompanying_count": v.accompanying_count,
        "vehicle_number": v.vehicle_number,
        "status": v.status,
        "expected_from": v.expected_from,
        "expected_to": v.expected_to,
        "approved_at": v.approved_at,
        "denial_reason": v.denial_reason,
        "approved_via": v.approved_via,
        "confirmed_with": v.confirmed_with,
        "checked_in_at": v.checked_in_at,
        "checked_out_at": v.checked_out_at,
        "duration_minutes": duration,
        "notes": v.notes,
        "created_at": v.created_at,
    }


class VisitorService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = VisitorRepository(tenant)
        self.recipients = RecipientRepository(tenant)
        self.notifications = NotificationService(tenant)

    def _owner_scope(self, principal: Principal) -> list[uuid.UUID] | None:
        if principal.is_scoped_to_own(Permission.VISITOR_READ):
            return sorted(principal.flat_ids)
        return None

    def _assert_can_see(self, flat_id: uuid.UUID, principal: Principal) -> None:
        scope = self._owner_scope(principal)
        if scope is not None and flat_id not in scope:
            raise NotFoundError("Visitor")

    async def _generate_code(self) -> str:
        """A short code that is free right now.

        Six characters from a 32-symbol alphabet is a billion possibilities; the
        collision check exists for the codes currently live, not for entropy.
        """
        for _ in range(12):
            code = "".join(secrets.choice(PASS_CODE_ALPHABET) for _ in range(6))
            if not await self.repo.code_in_use(code):
                return code
        raise ConflictError("Could not allocate a visitor pass code. Please try again.")

    # -- reads -------------------------------------------------------------- #

    async def list(
        self,
        principal: Principal,
        *,
        page: int,
        limit: int,
        q: str | None = None,
        status: str | None = None,
        visitor_type: str | None = None,
        flat_id: uuid.UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        on_premises_only: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        if flat_id is not None:
            self._assert_can_see(flat_id, principal)
        rows, total = await self.repo.list(
            page=page,
            limit=limit,
            q=q,
            status=status,
            visitor_type=visitor_type,
            flat_id=flat_id,
            from_date=from_date,
            to_date=to_date,
            on_premises_only=on_premises_only,
            only_flat_ids=self._owner_scope(principal),
        )
        return [_visitor_dict(v) for v in rows], total

    async def get(self, visitor_id: uuid.UUID, principal: Principal) -> dict[str, Any]:
        visitor = await self.repo.get(visitor_id)
        if visitor is None:
            raise NotFoundError("Visitor")
        self._assert_can_see(visitor.flat_id, principal)
        return _visitor_dict(visitor)

    async def summary(self) -> dict[str, int]:
        start = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC)
        return await self.repo.summary(day_start=start)

    # -- writes ------------------------------------------------------------- #

    async def pre_approve(
        self,
        payload: VisitorPreApprove,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        flat_id = payload.flat_id
        scope = self._owner_scope(principal)
        if scope is not None:
            if flat_id is None:
                flat_id = scope[0] if scope else None
            elif flat_id not in scope:
                raise NotFoundError("Flat")
        if flat_id is None:
            raise ValidationError("Choose the flat this visitor is coming to.")
        if await FlatRepository(self.tenant).get(flat_id) is None:
            raise NotFoundError("Flat")
        if payload.expected_to < _now():
            raise ValidationError("The expected window has already passed.")

        data = payload.model_dump(exclude={"flat_id"})
        visitor = Visitor(
            flat_id=flat_id,
            status=VisitorStatus.EXPECTED,
            approved_by=principal.tenant_user_id,
            approved_at=_now(),
            approved_via=APPROVED_VIA_APP,
            pass_code=await self._generate_code(),
            **data,
        )
        await self.repo.create(visitor)
        await self.tenant.refresh(visitor)

        await self.notifications.notify(
            await self.recipients.users_with_permission(Permission.SECURITY_READ),
            category=Category.VISITOR_ARRIVED,
            title=f"Expected visitor: {visitor.visitor_name}",
            body=f"Pass {visitor.pass_code} · {_flat_number(visitor) or 'flat'}",
            link="/app/visitors",
            payload={"visitor_id": str(visitor.id), "pass_code": visitor.pass_code},
            exclude=principal.tenant_user_id,
        )

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.VISITOR_PRE_APPROVED,
            principal=principal,
            target_type="visitors",
            target_id=visitor.id,
            changes={"after": {"name": visitor.visitor_name}},
            request_id=request_id,
        )
        return _visitor_dict(visitor)

    async def log_at_gate(
        self,
        payload: VisitorGateEntry,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if await FlatRepository(self.tenant).get(payload.flat_id) is None:
            raise NotFoundError("Flat")

        if payload.visitor_type in CODELESS_PRE_APPROVAL_TYPES:
            matched = await self.repo.matching_pre_approval(
                flat_id=payload.flat_id,
                visitor_type=payload.visitor_type,
                company=payload.company,
                at=_now(),
            )
            if matched is not None:
                return await self._fill_pre_approval(
                    matched, payload, principal, request_id=request_id
                )

        visitor = Visitor(
            status=VisitorStatus.AWAITING_APPROVAL,
            pass_code=await self._generate_code(),
            **payload.model_dump(),
        )
        await self.repo.create(visitor)
        await self.tenant.refresh(visitor)

        await self.notifications.notify(
            await self.recipients.users_for_flat(visitor.flat_id),
            category=Category.VISITOR_AWAITING,
            title=f"{visitor.visitor_name} is at the gate",
            body=visitor.purpose or visitor.visitor_type.value.replace("_", " ").title(),
            link="/app/visitors",
            payload={"visitor_id": str(visitor.id), "needs_decision": True},
        )

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.VISITOR_LOGGED,
            principal=principal,
            target_type="visitors",
            target_id=visitor.id,
            changes={"after": {"name": visitor.visitor_name}},
            request_id=request_id,
        )
        return _visitor_dict(visitor)

    async def decide(
        self,
        visitor_id: uuid.UUID,
        payload: VisitorDecision,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        visitor = await self.repo.get(visitor_id)
        if visitor is None:
            raise NotFoundError("Visitor")
        # A resident may only answer for their own flat; the guard's
        # ``security.manage`` broadens the same permission society-wide.
        self._assert_can_see(visitor.flat_id, principal)

        target = VisitorStatus.APPROVED if payload.approved else VisitorStatus.DENIED
        legal = VISITOR_TRANSITIONS.get(visitor.status, frozenset())
        if target not in legal:
            raise ConflictError(
                f"A visitor who is {visitor.status.value} cannot be "
                f"{target.value.lower()} — the decision has already been made."
            )

        visitor.status = target
        visitor.approved_by = principal.tenant_user_id
        visitor.approved_at = _now()
        visitor.approved_via = APPROVED_VIA_APP
        if not payload.approved:
            visitor.denial_reason = payload.reason
        await self.tenant.flush()

        guards = await self.recipients.users_with_permission(Permission.SECURITY_READ)
        await self.notifications.notify(
            guards,
            category=Category.VISITOR_DENIED if not payload.approved else Category.VISITOR_ARRIVED,
            title=(
                f"{visitor.visitor_name}: approved"
                if payload.approved
                else f"{visitor.visitor_name}: turned away"
            ),
            body=payload.reason or f"Pass {visitor.pass_code}",
            link="/app/visitors",
            payload={"visitor_id": str(visitor.id)},
            exclude=principal.tenant_user_id,
        )

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.VISITOR_DECIDED,
            principal=principal,
            target_type="visitors",
            target_id=visitor.id,
            changes={"after": {"status": target.value}},
            request_id=request_id,
        )
        await self.tenant.refresh(visitor)
        return _visitor_dict(visitor)

    async def _fill_pre_approval(
        self,
        visitor: Visitor,
        payload: VisitorGateEntry,
        principal: Principal,
        *,
        request_id: str | None,
    ) -> dict[str, Any]:
        """Turn "a Swiggy order tonight" into the rider actually at the gate.

        The resident's row keeps its approval and moves to APPROVED, so the
        guard's next tap is Check in and a second rider cannot claim the same
        pre-approval. The resident's own label is kept in the notes — the gate
        log should show both what was approved and who turned up.
        """
        approved_as = visitor.visitor_name
        visitor.status = VisitorStatus.APPROVED
        visitor.visitor_name = payload.visitor_name
        visitor.visitor_phone = payload.visitor_phone or visitor.visitor_phone
        visitor.company = payload.company or visitor.company
        visitor.vehicle_number = payload.vehicle_number or visitor.vehicle_number
        visitor.accompanying_count = payload.accompanying_count
        visitor.notes = "\n".join(
            part
            for part in (f"Pre-approved by the flat as: {approved_as}", payload.notes)
            if part
        )
        await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.VISITOR_LOGGED,
            principal=principal,
            target_type="visitors",
            target_id=visitor.id,
            changes={
                "after": {"name": visitor.visitor_name, "matched_pre_approval": approved_as}
            },
            request_id=request_id,
        )
        await self.tenant.refresh(visitor)
        return _visitor_dict(visitor)

    async def guard_decide(
        self,
        visitor_id: uuid.UUID,
        payload: VisitorGuardDecision,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """The guard answers for a flat that did not answer in the app.

        Two cases, and the schema already insists on the evidence for each:

        * **Admit** — only after calling the flat. ``confirmed_with`` names the
          resident who said yes, and every resident of the flat is told, so a
          "yes" nobody in the flat actually gave is noticed the same night.
        * **Turn away** — the guard's own call is enough; an unwanted person is
          never let in by default.
        """
        visitor = await self.repo.get(visitor_id)
        if visitor is None:
            raise NotFoundError("Visitor")
        if visitor.status is not VisitorStatus.AWAITING_APPROVAL:
            raise ConflictError(
                f"A visitor who is {visitor.status.value.replace('_', ' ').lower()} "
                "has already been decided."
            )

        target = VisitorStatus.APPROVED if payload.approved else VisitorStatus.DENIED
        visitor.status = target
        visitor.approved_by = principal.tenant_user_id
        visitor.approved_at = _now()
        visitor.confirmed_with = payload.confirmed_with
        visitor.approved_via = (
            APPROVED_VIA_PHONE if payload.confirmed_with else APPROVED_VIA_GUARD
        )
        if not payload.approved:
            visitor.denial_reason = payload.reason
        await self.tenant.flush()

        if payload.approved:
            title = f"{visitor.visitor_name} let in after a call"
            body = f"Security confirmed by phone with {payload.confirmed_with}."
        else:
            title = f"{visitor.visitor_name} turned away at the gate"
            body = payload.reason
        await self.notifications.notify(
            await self.recipients.users_for_flat(visitor.flat_id),
            category=Category.VISITOR_ARRIVED if payload.approved else Category.VISITOR_DENIED,
            title=title,
            body=body,
            link="/app/visitors",
            payload={"visitor_id": str(visitor.id)},
            exclude=principal.tenant_user_id,
        )

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.VISITOR_DECIDED,
            principal=principal,
            target_type="visitors",
            target_id=visitor.id,
            changes={
                "after": {
                    "status": target.value,
                    "approved_via": visitor.approved_via,
                    "confirmed_with": payload.confirmed_with,
                }
            },
            request_id=request_id,
        )
        await self.tenant.refresh(visitor)
        return _visitor_dict(visitor)

    async def check_in(
        self,
        payload: VisitorCheckIn,
        principal: Principal,
        *,
        visitor_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if visitor_id is not None:
            visitor = await self.repo.get(visitor_id)
        elif payload.pass_code:
            visitor = await self.repo.get_by_pass_code(payload.pass_code)
        else:
            raise ValidationError("Provide a pass code or select the visitor.")
        if visitor is None:
            raise NotFoundError("Visitor pass")

        if VisitorStatus.CHECKED_IN not in VISITOR_TRANSITIONS.get(visitor.status, frozenset()):
            if visitor.status is VisitorStatus.AWAITING_APPROVAL:
                raise ConflictError(
                    "This visitor has not been approved by the flat yet."
                )
            raise ConflictError(
                f"A visitor who is {visitor.status.value.replace('_', ' ').lower()} "
                "cannot be checked in."
            )

        now = _now()
        if visitor.expected_to is not None and visitor.expected_to < now:
            raise ConflictError(
                "This pass expired at "
                f"{visitor.expected_to:%d %b %H:%M}. Log the visitor as a new entry."
            )

        visitor.status = VisitorStatus.CHECKED_IN
        visitor.checked_in_at = now
        visitor.checked_in_by = principal.tenant_user_id
        if payload.vehicle_number:
            visitor.vehicle_number = payload.vehicle_number
        if payload.accompanying_count is not None:
            visitor.accompanying_count = payload.accompanying_count
        if payload.notes:
            visitor.notes = payload.notes
        await self.tenant.flush()

        await self.notifications.notify(
            await self.recipients.users_for_flat(visitor.flat_id),
            category=Category.VISITOR_ARRIVED,
            title=f"{visitor.visitor_name} has arrived",
            body=visitor.purpose or None,
            link="/app/visitors",
            payload={"visitor_id": str(visitor.id)},
            exclude=principal.tenant_user_id,
        )

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.VISITOR_CHECKED_IN,
            principal=principal,
            target_type="visitors",
            target_id=visitor.id,
            request_id=request_id,
        )
        await self.tenant.refresh(visitor)
        return _visitor_dict(visitor)

    async def check_out(
        self, visitor_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        visitor = await self.repo.get(visitor_id)
        if visitor is None:
            raise NotFoundError("Visitor")
        if visitor.status is not VisitorStatus.CHECKED_IN:
            raise ConflictError("This visitor is not currently on the premises.")

        visitor.status = VisitorStatus.CHECKED_OUT
        visitor.checked_out_at = _now()
        visitor.checked_out_by = principal.tenant_user_id
        await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.VISITOR_CHECKED_OUT,
            principal=principal,
            target_type="visitors",
            target_id=visitor.id,
            request_id=request_id,
        )
        await self.tenant.refresh(visitor)
        return _visitor_dict(visitor)

    async def expire_stale(self) -> int:
        """Close out pre-approvals nobody used.

        Without this, yesterday's plumber sits in "expected" forever and the
        guard's board stops being a picture of today.
        """
        stale = await self.repo.stale_expected(_now())
        for visitor in stale:
            visitor.status = VisitorStatus.EXPIRED
        if stale:
            await self.tenant.flush()
        return len(stale)


# --------------------------------------------------------------------------- #
# Security incidents
# --------------------------------------------------------------------------- #


def _incident_dict(i: SecurityIncident) -> dict[str, Any]:
    return {
        "id": i.id,
        "title": i.title,
        "description": i.description,
        "severity": i.severity,
        "status": i.status,
        "location": i.location,
        "building_id": i.building_id,
        "building_name": _building_name(i),
        "flat_id": i.flat_id,
        "flat_number": _flat_number(i),
        "occurred_at": i.occurred_at,
        "reported_by": i.reported_by,
        "reported_by_name": i.reported_by_name,
        "action_taken": i.action_taken,
        "resolved_at": i.resolved_at,
        "police_reference": i.police_reference,
        "people_involved": i.people_involved,
        "created_at": i.created_at,
    }


class IncidentService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = IncidentRepository(tenant)
        self.recipients = RecipientRepository(tenant)
        self.notifications = NotificationService(tenant)

    async def list(
        self,
        *,
        page: int,
        limit: int,
        q: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        open_only: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.repo.list(
            page=page,
            limit=limit,
            q=q,
            status=status,
            severity=severity,
            from_date=from_date,
            to_date=to_date,
            open_only=open_only,
        )
        return [_incident_dict(i) for i in rows], total

    async def get(self, incident_id: uuid.UUID) -> dict[str, Any]:
        incident = await self.repo.get(incident_id)
        if incident is None:
            raise NotFoundError("Incident")
        return _incident_dict(incident)

    async def create(
        self, payload: IncidentCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        if payload.occurred_at > _now() + timedelta(minutes=5):
            raise ValidationError("An incident cannot be recorded as happening later today.")

        incident = SecurityIncident(
            reported_by=principal.tenant_user_id,
            reported_by_name=principal.display_name or principal.email,
            **payload.model_dump(),
        )
        await self.repo.create(incident)
        await self.tenant.refresh(incident)

        await self.notifications.notify(
            await self.recipients.users_with_permission(Permission.SECURITY_MANAGE),
            category=Category.INCIDENT_REPORTED,
            title=f"{incident.severity.value.title()} incident: {incident.title}",
            body=incident.location or None,
            link="/app/security",
            payload={"incident_id": str(incident.id), "severity": incident.severity.value},
            exclude=principal.tenant_user_id,
        )

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.INCIDENT_REPORTED,
            principal=principal,
            target_type="security_incidents",
            target_id=incident.id,
            changes={"after": {"title": incident.title, "severity": incident.severity.value}},
            request_id=request_id,
        )
        return _incident_dict(incident)

    async def update(
        self,
        incident_id: uuid.UUID,
        payload: IncidentUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        incident = await self.repo.get(incident_id)
        if incident is None:
            raise NotFoundError("Incident")

        before = _incident_dict(incident)
        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(incident, key, value)
        if (
            changes.get("status") in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED)
            and incident.resolved_at is None
        ):
            incident.resolved_at = _now()
        await self.tenant.flush()
        await self.tenant.refresh(incident)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.INCIDENT_UPDATED,
            principal=principal,
            target_type="security_incidents",
            target_id=incident.id,
            changes=diff(
                {k: str(v) for k, v in before.items()},
                {k: str(v) for k, v in _incident_dict(incident).items()},
            ),
            request_id=request_id,
        )
        return _incident_dict(incident)


class SecurityDashboardService:
    """The guard's home screen, assembled in one transaction.

    Six round trips on a gate tablet's connection is a guard staring at
    spinners while somebody waits at the barrier.
    """

    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant

    async def build(self) -> dict[str, Any]:
        today = date.today()
        visitors = VisitorRepository(self.tenant)
        incidents = IncidentRepository(self.tenant)

        summary = await visitors.summary(
            day_start=datetime.combine(today, datetime.min.time(), tzinfo=UTC)
        )
        counts = await incidents.summary(month_start=today.replace(day=1))
        return {
            "visitors": summary,
            **counts,
            "recent_incidents": [_incident_dict(i) for i in await incidents.recent(5)],
            "on_premises": [_visitor_dict(v) for v in await visitors.on_premises(25)],
        }
