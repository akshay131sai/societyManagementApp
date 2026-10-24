"""Operations: complaints, work tasks, visitors and security incidents.

Four ideas run through this module.

* **A ticket number is the database's job.** ``complaints.ticket_number``
  defaults to an expression over a sequence, so two residents pressing Submit
  in the same millisecond cannot be handed the same number — and no service
  has to hold a lock to avoid it.

* **Maintenance and housekeeping are one table.** They have identical
  workflows and separate permissions, so ``work_tasks.department`` tells them
  apart. Two tables would have drifted apart by the third bug fix.

* **A schedule is not a task.** ``work_schedules`` describes the intention
  ("the lift is serviced monthly"); ``work_tasks`` records what actually
  happened on a given date. The scheduler creates the second from the first,
  which is why a skipped month is visible rather than silently absent.

* **Time is stored, not derived.** ``acknowledged_at``, ``resolved_at`` and
  ``checked_out_at`` are columns because an SLA report reads them years later,
  when nobody remembers what the status transitions were.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import TenantBase, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.tenant.enums import (
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
    complaint_category_enum,
    complaint_status_enum,
    department_enum,
    incident_severity_enum,
    incident_status_enum,
    priority_enum,
    recurrence_enum,
    task_status_enum,
    visitor_status_enum,
    visitor_type_enum,
)

TICKET_SEQUENCE = "complaint_ticket_seq"

TICKET_DEFAULT = (
    "'CMP-' || to_char(now() AT TIME ZONE 'Asia/Kolkata', 'YYYY') || '-' || "
    f"lpad(nextval('{TICKET_SEQUENCE}')::text, 5, '0')"
)
"""``CMP-2026-00042``.

Computed by PostgreSQL, in IST, so the year in the ticket matches the day the
resident remembers raising it rather than the server's UTC date.
"""


# --------------------------------------------------------------------------- #
# Complaints
# --------------------------------------------------------------------------- #


class Complaint(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A resident's problem, from raised to closed.

    ``flat_id`` is nullable: a guard reporting a burst pipe in the basement is
    reporting a real complaint that belongs to no flat. Owner scoping treats a
    NULL flat as society-wide, which is correct — it is nobody's private issue.
    """

    __tablename__ = "complaints"

    ticket_number: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, server_default=text(TICKET_DEFAULT)
    )

    flat_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="SET NULL")
    )
    raised_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    raised_by_name: Mapped[str] = mapped_column(String(150), nullable=False)
    """Denormalised so a ticket still reads correctly after the account that
    raised it is deleted. An audit trail that says "unknown" is not one."""

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[ComplaintCategory] = mapped_column(
        complaint_category_enum, nullable=False, server_default=ComplaintCategory.OTHER.value
    )
    priority: Mapped[Priority] = mapped_column(
        priority_enum, nullable=False, server_default=Priority.MEDIUM.value
    )
    status: Mapped[ComplaintStatus] = mapped_column(
        complaint_status_enum, nullable=False, server_default=ComplaintStatus.OPEN.value
    )
    location: Mapped[str | None] = mapped_column(String(200))

    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_department: Mapped[Department | None] = mapped_column(department_enum)

    due_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When the society promised a fix. Set from the category SLA at creation,
    and left alone afterwards — a target that moves is not a target."""

    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[str | None] = mapped_column(Text)

    reopen_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    """A ticket resolved three times and reopened three times is a different
    story from three separate tickets, and the reports should say so."""

    rating: Mapped[int | None] = mapped_column(SmallInteger)
    rating_comment: Mapped[str | None] = mapped_column(Text)

    flat: Mapped["object"] = relationship("Flat", lazy="selectin")
    assignee: Mapped["object"] = relationship(
        "TenantUser", lazy="selectin", foreign_keys=[assigned_to]
    )
    comments: Mapped[list[ComplaintComment]] = relationship(
        back_populates="complaint",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="ComplaintComment.created_at",
    )

    __table_args__ = (
        CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5", name="rating_range"),
        CheckConstraint("reopen_count >= 0", name="reopen_count_non_negative"),
        CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= created_at", name="resolved_after_raised"
        ),
        Index("ix_complaints_status", "status", "created_at"),
        Index("ix_complaints_flat", "flat_id", postgresql_where="flat_id IS NOT NULL"),
        Index(
            "ix_complaints_assignee",
            "assigned_to",
            postgresql_where="assigned_to IS NOT NULL",
        ),
        # The overdue banner is the hottest query on the operations dashboard
        # and only ever looks at tickets nobody has finished.
        Index(
            "ix_complaints_open_due",
            "due_by",
            postgresql_where=(
                "status IN ('OPEN', 'ACKNOWLEDGED', 'IN_PROGRESS', 'REOPENED')"
            ),
        ),
        Index("ix_complaints_category", "category", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Complaint {self.ticket_number} {self.status}>"


class ComplaintComment(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """One entry on a ticket's timeline — a human note or a status change.

    Status changes are written here as ``is_system`` rows rather than being
    reconstructed from an audit log, because the resident sees this timeline
    and "Assigned to Maintenance" belongs in the same list as the reply.
    """

    __tablename__ = "complaint_comments"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    author_name: Mapped[str] = mapped_column(String(150), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    """Staff-only. Filtered out for a principal whose complaint access is
    owner-scoped, so a note about a difficult resident is not shown to them."""

    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    complaint: Mapped[Complaint] = relationship(back_populates="comments", lazy="noload")

    __table_args__ = (
        Index("ix_complaint_comments_complaint", "complaint_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ComplaintComment {self.complaint_id}>"


# --------------------------------------------------------------------------- #
# Work: schedules and tasks
# --------------------------------------------------------------------------- #


class WorkSchedule(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A recurring intention: "the lift is serviced on the 5th of every month".

    ``next_due_on`` is stored rather than computed on read. The scheduler polls
    "what is due today" across every society every morning, and a stored date
    turns that into an index scan instead of a recurrence calculation per row.
    """

    __tablename__ = "work_schedules"

    department: Mapped[Department] = mapped_column(department_enum, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    area: Mapped[str | None] = mapped_column(String(200))
    """"Tower A lobby", "Basement 2", "Terrace" — free text, because a society's
    own words for its own places are better than any enum we could invent."""

    building_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buildings.id", ondelete="SET NULL")
    )
    recurrence: Mapped[Recurrence] = mapped_column(recurrence_enum, nullable=False)
    priority: Mapped[Priority] = mapped_column(
        priority_enum, nullable=False, server_default=Priority.MEDIUM.value
    )

    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    vendor_name: Mapped[str | None] = mapped_column(String(150))
    vendor_phone: Mapped[str | None] = mapped_column(String(10))

    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    next_due_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date | None] = mapped_column(Date)
    lead_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="3")
    """How far ahead the task is raised, so a worker sees it before it is due."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    building: Mapped["object"] = relationship("Building", lazy="selectin")
    assignee: Mapped["object"] = relationship(
        "TenantUser", lazy="selectin", foreign_keys=[assigned_to]
    )

    __table_args__ = (
        CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0", name="cost_non_negative"
        ),
        CheckConstraint("lead_days BETWEEN 0 AND 90", name="lead_days_range"),
        CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="date_order"),
        CheckConstraint(
            r"vendor_phone IS NULL OR vendor_phone ~ '^[6-9][0-9]{9}$'", name="phone_format"
        ),
        Index("ix_work_schedules_department", "department", "next_due_on"),
        # The scheduler's only query: due schedules, cheapest possible.
        Index("ix_work_schedules_due", "next_due_on", postgresql_where="is_active"),
    )

    def __repr__(self) -> str:
        return f"<WorkSchedule {self.department} {self.title}>"


class WorkTask(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """One piece of work on one date.

    Created either from a schedule (the monthly lift service for June) or
    ad hoc (a complaint escalated into a job). ``complaint_id`` links the two
    worlds so closing the job can close the ticket.
    """

    __tablename__ = "work_tasks"

    department: Mapped[Department] = mapped_column(department_enum, nullable=False)
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("work_schedules.id", ondelete="SET NULL")
    )
    complaint_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("complaints.id", ondelete="SET NULL")
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    area: Mapped[str | None] = mapped_column(String(200))
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buildings.id", ondelete="SET NULL")
    )

    status: Mapped[TaskStatus] = mapped_column(
        task_status_enum, nullable=False, server_default=TaskStatus.PENDING.value
    )
    priority: Mapped[Priority] = mapped_column(
        priority_enum, nullable=False, server_default=Priority.MEDIUM.value
    )

    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    due_on: Mapped[date] = mapped_column(Date, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    completion_notes: Mapped[str | None] = mapped_column(Text)
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    vendor_name: Mapped[str | None] = mapped_column(String(150))

    schedule: Mapped[WorkSchedule | None] = relationship(lazy="selectin")
    building: Mapped["object"] = relationship("Building", lazy="selectin")
    assignee: Mapped["object"] = relationship(
        "TenantUser", lazy="selectin", foreign_keys=[assigned_to]
    )

    __table_args__ = (
        CheckConstraint("actual_cost IS NULL OR actual_cost >= 0", name="cost_non_negative"),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="completed_after_started",
        ),
        # A task cannot be verified without having been completed. Sign-off is
        # the one thing on this table an auditor will actually check.
        CheckConstraint(
            "verified_at IS NULL OR completed_at IS NOT NULL", name="verified_implies_completed"
        ),
        # One occurrence per schedule per due date. Re-running the generator
        # after a crash tops the day up instead of duplicating it.
        Index(
            "ux_work_tasks_occurrence",
            "schedule_id",
            "due_on",
            unique=True,
            postgresql_where="schedule_id IS NOT NULL",
        ),
        Index("ix_work_tasks_department", "department", "due_on"),
        Index(
            "ix_work_tasks_assignee",
            "assigned_to",
            "status",
            postgresql_where="assigned_to IS NOT NULL",
        ),
        Index(
            "ix_work_tasks_open",
            "due_on",
            postgresql_where="status IN ('PENDING', 'IN_PROGRESS')",
        ),
        Index(
            "ix_work_tasks_complaint",
            "complaint_id",
            postgresql_where="complaint_id IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return f"<WorkTask {self.department} {self.title} {self.status}>"


# --------------------------------------------------------------------------- #
# Visitors
# --------------------------------------------------------------------------- #


class Visitor(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """A gate log entry, and the approval that let it happen.

    Pre-approval and walk-up are the same row at different points in its life,
    not two tables: the guard's screen has to show both in one list, and a
    resident's "who came to my flat" history has to include both.
    """

    __tablename__ = "visitors"

    pass_code: Mapped[str | None] = mapped_column(String(8))
    """Shown to the visitor, read out at the gate. Unique among passes that
    could still be used — reusing a code once its visit is over is fine and
    keeps the codes short enough to say over a phone."""

    flat_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="CASCADE"), nullable=False
    )
    visitor_name: Mapped[str] = mapped_column(String(150), nullable=False)
    visitor_phone: Mapped[str | None] = mapped_column(String(10))
    visitor_type: Mapped[VisitorType] = mapped_column(
        visitor_type_enum, nullable=False, server_default=VisitorType.GUEST.value
    )
    company: Mapped[str | None] = mapped_column(String(120))
    purpose: Mapped[str | None] = mapped_column(String(300))
    accompanying_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    vehicle_number: Mapped[str | None] = mapped_column(String(20))

    status: Mapped[VisitorStatus] = mapped_column(
        visitor_status_enum, nullable=False, server_default=VisitorStatus.AWAITING_APPROVAL.value
    )

    expected_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """The pre-approval window. Outside it the pass does not open the gate, and
    the nightly sweep marks the row EXPIRED."""

    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    denial_reason: Mapped[str | None] = mapped_column(String(300))
    approved_via: Mapped[str | None] = mapped_column(String(20))
    """How the decision was made: ``APP`` (the resident in the app), ``PHONE``
    (the guard called the flat and recorded the answer) or ``GUARD`` (the guard
    turned someone away on their own judgement). A guard can never *admit* on
    their own judgement — that is the check constraint below."""
    confirmed_with: Mapped[str | None] = mapped_column(String(150))
    """For ``PHONE`` decisions, the resident the guard spoke to."""

    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_out_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    notes: Mapped[str | None] = mapped_column(Text)

    flat: Mapped["object"] = relationship("Flat", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            r"visitor_phone IS NULL OR visitor_phone ~ '^[6-9][0-9]{9}$'", name="phone_format"
        ),
        CheckConstraint(
            "accompanying_count BETWEEN 0 AND 50", name="accompanying_count_range"
        ),
        CheckConstraint(
            "expected_to IS NULL OR expected_from IS NULL OR expected_to >= expected_from",
            name="window_order",
        ),
        CheckConstraint(
            "checked_out_at IS NULL OR checked_in_at IS NOT NULL",
            name="checkout_implies_checkin",
        ),
        CheckConstraint(
            "approved_via IS NULL OR approved_via IN ('APP', 'PHONE', 'GUARD')",
            name="approved_via_values",
        ),
        CheckConstraint(
            "approved_via IS DISTINCT FROM 'PHONE' OR confirmed_with IS NOT NULL",
            name="phone_needs_resident",
        ),
        CheckConstraint(
            "approved_via IS DISTINCT FROM 'GUARD' OR status <> 'APPROVED'",
            name="guard_cannot_self_admit",
        ),
        CheckConstraint(
            "checked_out_at IS NULL OR checked_out_at >= checked_in_at",
            name="checkout_after_checkin",
        ),
        # A code identifies exactly one live pass. Once the visit is over the
        # code is free again, which is why the index is partial.
        Index(
            "ux_visitors_pass_code",
            "pass_code",
            unique=True,
            postgresql_where=(
                "pass_code IS NOT NULL AND status IN "
                "('EXPECTED', 'AWAITING_APPROVAL', 'APPROVED', 'CHECKED_IN')"
            ),
        ),
        Index("ix_visitors_flat", "flat_id", "created_at"),
        Index("ix_visitors_status", "status", "created_at"),
        # The guard's board: who is inside right now.
        Index(
            "ix_visitors_on_premises",
            "checked_in_at",
            postgresql_where="status = 'CHECKED_IN'",
        ),
        Index(
            "ix_visitors_expected",
            "expected_from",
            postgresql_where="status IN ('EXPECTED', 'APPROVED')",
        ),
    )

    def __repr__(self) -> str:
        return f"<Visitor {self.visitor_name} {self.status}>"


# --------------------------------------------------------------------------- #
# Security incidents
# --------------------------------------------------------------------------- #


class SecurityIncident(UUIDPrimaryKeyMixin, TimestampMixin, TenantBase):
    """Something a guard needs on record: a break-in attempt, a fire alarm, a
    car scraped in the basement.

    ``occurred_at`` is separate from ``created_at`` on purpose — a night guard
    writes up the 2 a.m. incident when the shift ends, and a report of
    incidents by hour that used the entry time would be wrong.
    """

    __tablename__ = "security_incidents"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[IncidentSeverity] = mapped_column(
        incident_severity_enum, nullable=False, server_default=IncidentSeverity.MINOR.value
    )
    status: Mapped[IncidentStatus] = mapped_column(
        incident_status_enum, nullable=False, server_default=IncidentStatus.REPORTED.value
    )

    location: Mapped[str | None] = mapped_column(String(200))
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buildings.id", ondelete="SET NULL")
    )
    flat_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("flats.id", ondelete="SET NULL")
    )

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reported_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reported_by_name: Mapped[str] = mapped_column(String(150), nullable=False)

    action_taken: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    police_reference: Mapped[str | None] = mapped_column(String(60))
    people_involved: Mapped[int | None] = mapped_column(Integer)

    building: Mapped["object"] = relationship("Building", lazy="selectin")
    flat: Mapped["object"] = relationship("Flat", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "people_involved IS NULL OR people_involved >= 0", name="people_non_negative"
        ),
        CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= occurred_at", name="resolved_after_occurred"
        ),
        Index("ix_incidents_occurred", "occurred_at"),
        Index("ix_incidents_status", "status", "occurred_at"),
        Index(
            "ix_incidents_open",
            "severity",
            postgresql_where="status IN ('REPORTED', 'INVESTIGATING')",
        ),
    )

    def __repr__(self) -> str:
        return f"<SecurityIncident {self.title} {self.severity}>"


__all__ = [
    "TICKET_DEFAULT",
    "TICKET_SEQUENCE",
    "Complaint",
    "ComplaintComment",
    "SecurityIncident",
    "Visitor",
    "WorkSchedule",
    "WorkTask",
]
