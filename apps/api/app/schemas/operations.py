"""Complaint, work-task, visitor and incident schemas.

Two conventions worth naming:

* **Status is never a writable field.** A complaint moves through
  ``POST /complaints/{id}/transition`` and a task through
  ``/tasks/{id}/progress``, because each move has side effects — a timestamp, a
  timeline entry, a notification — that a ``PATCH {"status": ...}`` would let a
  caller skip.

* **Read models are flat.** A ticket row carries ``flat_number`` and
  ``assignee_name`` rather than nested objects, so the list screen renders from
  one payload without a lookup table per column.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.tenant import (
    ComplaintCategory,
    ComplaintStatus,
    Department,
    IncidentSeverity,
    IncidentStatus,
    Priority,
    Recurrence,
    TaskStatus,
    VisitorStatus,
    VisitorType,
)

Money = Annotated[Decimal, Field(ge=0, le=99_999_999, max_digits=14, decimal_places=2)]
Phone = Annotated[str, Field(pattern=r"^[6-9][0-9]{9}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=200)]
Body = Annotated[str, Field(min_length=1, max_length=5000)]


def _strip(value: str) -> str:
    return " ".join(value.strip().split())


# --------------------------------------------------------------------------- #
# Complaints
# --------------------------------------------------------------------------- #


class ComplaintCreate(BaseModel):
    """``flat_id`` is optional and, for a resident, ignored.

    A resident's ticket is always filed against their own flat — the service
    takes it from the principal rather than the body, so nobody can raise a
    complaint in a neighbour's name. Staff reporting a common-area problem
    leave it null.
    """

    title: ShortText
    description: Body
    category: ComplaintCategory = ComplaintCategory.OTHER
    priority: Priority = Priority.MEDIUM
    flat_id: uuid.UUID | None = None
    location: Annotated[str | None, Field(max_length=200)] = None

    @field_validator("title")
    @classmethod
    def _clean_title(cls, v: str) -> str:
        return _strip(v)


class ComplaintUpdate(BaseModel):
    """Editable facts. Status, assignment and resolution have their own routes."""

    title: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    description: Annotated[str | None, Field(min_length=1, max_length=5000)] = None
    category: ComplaintCategory | None = None
    priority: Priority | None = None
    location: Annotated[str | None, Field(max_length=200)] = None


class ComplaintAssign(BaseModel):
    assigned_to: uuid.UUID | None = None
    """``null`` unassigns, putting the ticket back in the unclaimed queue."""

    assigned_department: Department | None = None
    note: Annotated[str | None, Field(max_length=1000)] = None


class ComplaintTransition(BaseModel):
    """One move through the workflow, with the note that explains it."""

    status: ComplaintStatus
    note: Annotated[str | None, Field(max_length=2000)] = None

    @model_validator(mode="after")
    def _resolution_needs_a_note(self) -> ComplaintTransition:
        # "Resolved." with no explanation is the thing residents complain about
        # after the complaint, so the note is required exactly where it matters.
        if self.status in (ComplaintStatus.RESOLVED, ComplaintStatus.REJECTED) and not (
            self.note and self.note.strip()
        ):
            raise ValueError(
                "Say what was done. A resolution without an explanation is what "
                "gets a ticket reopened."
            )
        return self


class ComplaintRating(BaseModel):
    """The resident's verdict, accepted once the ticket is resolved or closed."""

    rating: Annotated[int, Field(ge=1, le=5)]
    comment: Annotated[str | None, Field(max_length=1000)] = None


class ComplaintCommentCreate(BaseModel):
    body: Annotated[str, Field(min_length=1, max_length=5000)]
    is_internal: bool = False
    """Staff-only. The service refuses it from an owner-scoped principal, so a
    resident cannot write a note they would then be unable to see."""


class ComplaintCommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    author_id: uuid.UUID | None = None
    author_name: str
    body: str
    is_internal: bool
    is_system: bool
    created_at: datetime


class ComplaintRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_number: str
    flat_id: uuid.UUID | None = None
    flat_number: str | None = None
    raised_by: uuid.UUID | None = None
    raised_by_name: str
    title: str
    description: str
    category: ComplaintCategory
    priority: Priority
    status: ComplaintStatus
    location: str | None = None
    assigned_to: uuid.UUID | None = None
    assignee_name: str | None = None
    assigned_department: Department | None = None
    due_by: datetime | None = None
    is_overdue: bool = False
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    resolution_notes: str | None = None
    reopen_count: int
    rating: int | None = None
    rating_comment: str | None = None
    comment_count: int = 0
    age_hours: int = 0
    created_at: datetime
    updated_at: datetime


class ComplaintDetail(ComplaintRead):
    comments: list[ComplaintCommentRead] = []
    allowed_transitions: list[ComplaintStatus] = []
    """What this principal can do next. The client renders buttons from this
    rather than re-implementing the transition table."""


class ComplaintSummary(BaseModel):
    """The operations dashboard header."""

    total: int
    open: int
    overdue: int
    resolved_this_month: int
    unassigned: int
    by_status: dict[str, int]
    by_category: dict[str, int]
    by_priority: dict[str, int]
    average_resolution_hours: Decimal | None = None
    satisfaction: Decimal | None = None
    """Mean rating out of 5, over rated tickets only."""


# --------------------------------------------------------------------------- #
# Work schedules and tasks
# --------------------------------------------------------------------------- #


class WorkScheduleCreate(BaseModel):
    title: ShortText
    recurrence: Recurrence
    starts_on: date
    description: Annotated[str | None, Field(max_length=5000)] = None
    area: Annotated[str | None, Field(max_length=200)] = None
    building_id: uuid.UUID | None = None
    priority: Priority = Priority.MEDIUM
    assigned_to: uuid.UUID | None = None
    estimated_cost: Money | None = None
    vendor_name: Annotated[str | None, Field(max_length=150)] = None
    vendor_phone: Phone | None = None
    ends_on: date | None = None
    lead_days: Annotated[int, Field(ge=0, le=90)] = 3

    @field_validator("title")
    @classmethod
    def _clean_title(cls, v: str) -> str:
        return _strip(v)

    @model_validator(mode="after")
    def _dates_make_sense(self) -> WorkScheduleCreate:
        if self.ends_on is not None and self.ends_on < self.starts_on:
            raise ValueError("A schedule cannot end before it starts.")
        return self


class WorkScheduleUpdate(BaseModel):
    title: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    description: Annotated[str | None, Field(max_length=5000)] = None
    area: Annotated[str | None, Field(max_length=200)] = None
    building_id: uuid.UUID | None = None
    recurrence: Recurrence | None = None
    priority: Priority | None = None
    assigned_to: uuid.UUID | None = None
    estimated_cost: Money | None = None
    vendor_name: Annotated[str | None, Field(max_length=150)] = None
    vendor_phone: Phone | None = None
    ends_on: date | None = None
    lead_days: Annotated[int | None, Field(ge=0, le=90)] = None
    is_active: bool | None = None


class WorkScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    department: Department
    title: str
    description: str | None = None
    area: str | None = None
    building_id: uuid.UUID | None = None
    building_name: str | None = None
    recurrence: Recurrence
    priority: Priority
    assigned_to: uuid.UUID | None = None
    assignee_name: str | None = None
    estimated_cost: Decimal | None = None
    vendor_name: str | None = None
    vendor_phone: str | None = None
    starts_on: date
    next_due_on: date
    ends_on: date | None = None
    lead_days: int
    is_active: bool
    open_tasks: int = 0
    created_at: datetime


class WorkTaskCreate(BaseModel):
    title: ShortText
    due_on: date
    description: Annotated[str | None, Field(max_length=5000)] = None
    area: Annotated[str | None, Field(max_length=200)] = None
    building_id: uuid.UUID | None = None
    priority: Priority = Priority.MEDIUM
    assigned_to: uuid.UUID | None = None
    complaint_id: uuid.UUID | None = None
    """Raised from a ticket. Resolving the task offers to resolve the ticket."""

    vendor_name: Annotated[str | None, Field(max_length=150)] = None

    @field_validator("title")
    @classmethod
    def _clean_title(cls, v: str) -> str:
        return _strip(v)


class WorkTaskUpdate(BaseModel):
    title: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    description: Annotated[str | None, Field(max_length=5000)] = None
    area: Annotated[str | None, Field(max_length=200)] = None
    building_id: uuid.UUID | None = None
    priority: Priority | None = None
    assigned_to: uuid.UUID | None = None
    due_on: date | None = None
    vendor_name: Annotated[str | None, Field(max_length=150)] = None


class WorkTaskProgress(BaseModel):
    """A worker's move on a task.

    ``actual_cost`` and ``notes`` ride along with the completion rather than
    needing a second call, because the person holding the phone is standing in
    a plant room and will not make two.
    """

    status: TaskStatus
    notes: Annotated[str | None, Field(max_length=2000)] = None
    actual_cost: Money | None = None

    @model_validator(mode="after")
    def _terminal_moves_need_a_reason(self) -> WorkTaskProgress:
        if self.status in (TaskStatus.CANCELLED, TaskStatus.SKIPPED) and not (
            self.notes and self.notes.strip()
        ):
            raise ValueError("Say why the task was not done.")
        return self


class WorkTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    department: Department
    schedule_id: uuid.UUID | None = None
    schedule_title: str | None = None
    complaint_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    area: str | None = None
    building_id: uuid.UUID | None = None
    building_name: str | None = None
    status: TaskStatus
    priority: Priority
    assigned_to: uuid.UUID | None = None
    assignee_name: str | None = None
    due_on: date
    is_overdue: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None
    verified_at: datetime | None = None
    completion_notes: str | None = None
    actual_cost: Decimal | None = None
    vendor_name: str | None = None
    allowed_transitions: list[TaskStatus] = []
    created_at: datetime


class WorkSummary(BaseModel):
    department: Department
    total: int
    pending: int
    in_progress: int
    overdue: int
    completed_this_month: int
    awaiting_verification: int
    active_schedules: int
    cost_this_month: Decimal


class ScheduleRunResult(BaseModel):
    """What a generation pass did. Also the shape the nightly worker logs."""

    schedules_examined: int
    tasks_created: int
    schedules_advanced: int
    skipped_existing: int


# --------------------------------------------------------------------------- #
# Visitors
# --------------------------------------------------------------------------- #


class VisitorPreApprove(BaseModel):
    """A resident expecting someone. Produces a pass code to share."""

    visitor_name: ShortText
    visitor_type: VisitorType = VisitorType.GUEST
    expected_from: datetime
    expected_to: datetime
    flat_id: uuid.UUID | None = None
    visitor_phone: Phone | None = None
    company: Annotated[str | None, Field(max_length=120)] = None
    purpose: Annotated[str | None, Field(max_length=300)] = None
    accompanying_count: Annotated[int, Field(ge=0, le=50)] = 0
    vehicle_number: Annotated[str | None, Field(max_length=20)] = None

    @field_validator("visitor_name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        return _strip(v)

    @model_validator(mode="after")
    def _window_is_sane(self) -> VisitorPreApprove:
        if self.expected_to <= self.expected_from:
            raise ValueError("The expected window must end after it starts.")
        return self


class VisitorGateEntry(BaseModel):
    """A guard logging someone who arrived without a pass.

    The row starts at AWAITING_APPROVAL and the resident is notified. A guard
    can check the visitor in only after approval, which is the whole point.
    """

    flat_id: uuid.UUID
    visitor_name: ShortText
    visitor_type: VisitorType = VisitorType.GUEST
    visitor_phone: Phone | None = None
    company: Annotated[str | None, Field(max_length=120)] = None
    purpose: Annotated[str | None, Field(max_length=300)] = None
    accompanying_count: Annotated[int, Field(ge=0, le=50)] = 0
    vehicle_number: Annotated[str | None, Field(max_length=20)] = None
    notes: Annotated[str | None, Field(max_length=2000)] = None

    @field_validator("visitor_name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        return _strip(v)


class VisitorDecision(BaseModel):
    approved: bool
    reason: Annotated[str | None, Field(max_length=300)] = None

    @model_validator(mode="after")
    def _denial_needs_a_reason(self) -> VisitorDecision:
        if not self.approved and not (self.reason and self.reason.strip()):
            raise ValueError("Say why the visitor was turned away.")
        return self


class VisitorGuardDecision(BaseModel):
    """A guard acting on a walk-up the flat has not answered in the app.

    Admitting needs ``confirmed_with`` — the resident the guard called and who
    said yes. Turning someone away needs a reason, and the guard may do that on
    their own judgement, so ``confirmed_with`` is optional there.
    """

    approved: bool
    confirmed_with: Annotated[str | None, Field(max_length=150)] = None
    reason: Annotated[str | None, Field(max_length=300)] = None

    @model_validator(mode="after")
    def _each_answer_needs_its_proof(self) -> VisitorGuardDecision:
        if self.confirmed_with is not None:
            self.confirmed_with = self.confirmed_with.strip() or None
        if self.approved and not self.confirmed_with:
            raise ValueError(
                "Name the resident who approved this visitor on the phone. "
                "A guard cannot admit anyone on their own."
            )
        if not self.approved and not (self.reason and self.reason.strip()):
            raise ValueError("Say why the visitor was turned away.")
        return self


class VisitorCheckIn(BaseModel):
    """A guard admitting someone. A pass code resolves the row; an id also works."""

    pass_code: Annotated[str | None, Field(min_length=4, max_length=8)] = None
    vehicle_number: Annotated[str | None, Field(max_length=20)] = None
    accompanying_count: Annotated[int | None, Field(ge=0, le=50)] = None
    notes: Annotated[str | None, Field(max_length=2000)] = None


class VisitorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pass_code: str | None = None
    flat_id: uuid.UUID
    flat_number: str | None = None
    visitor_name: str
    visitor_phone: str | None = None
    visitor_type: VisitorType
    company: str | None = None
    purpose: str | None = None
    accompanying_count: int
    vehicle_number: str | None = None
    status: VisitorStatus
    expected_from: datetime | None = None
    expected_to: datetime | None = None
    approved_at: datetime | None = None
    denial_reason: str | None = None
    approved_via: str | None = None
    confirmed_with: str | None = None
    checked_in_at: datetime | None = None
    checked_out_at: datetime | None = None
    duration_minutes: int | None = None
    notes: str | None = None
    created_at: datetime


class VisitorSummary(BaseModel):
    on_premises: int
    expected_today: int
    awaiting_approval: int
    entries_today: int
    denied_today: int


# --------------------------------------------------------------------------- #
# Security incidents
# --------------------------------------------------------------------------- #


class IncidentCreate(BaseModel):
    title: ShortText
    description: Body
    occurred_at: datetime
    severity: IncidentSeverity = IncidentSeverity.MINOR
    location: Annotated[str | None, Field(max_length=200)] = None
    building_id: uuid.UUID | None = None
    flat_id: uuid.UUID | None = None
    people_involved: Annotated[int | None, Field(ge=0, le=10_000)] = None
    police_reference: Annotated[str | None, Field(max_length=60)] = None

    @field_validator("title")
    @classmethod
    def _clean_title(cls, v: str) -> str:
        return _strip(v)


class IncidentUpdate(BaseModel):
    title: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    description: Annotated[str | None, Field(min_length=1, max_length=5000)] = None
    severity: IncidentSeverity | None = None
    status: IncidentStatus | None = None
    location: Annotated[str | None, Field(max_length=200)] = None
    action_taken: Annotated[str | None, Field(max_length=5000)] = None
    police_reference: Annotated[str | None, Field(max_length=60)] = None
    people_involved: Annotated[int | None, Field(ge=0, le=10_000)] = None


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    severity: IncidentSeverity
    status: IncidentStatus
    location: str | None = None
    building_id: uuid.UUID | None = None
    building_name: str | None = None
    flat_id: uuid.UUID | None = None
    flat_number: str | None = None
    occurred_at: datetime
    reported_by: uuid.UUID | None = None
    reported_by_name: str
    action_taken: str | None = None
    resolved_at: datetime | None = None
    police_reference: str | None = None
    people_involved: int | None = None
    created_at: datetime


class SecurityDashboard(BaseModel):
    """One request behind the guard's home screen."""

    visitors: VisitorSummary
    open_incidents: int
    critical_incidents: int
    incidents_this_month: int
    recent_incidents: list[IncidentRead]
    on_premises: list[VisitorRead]
