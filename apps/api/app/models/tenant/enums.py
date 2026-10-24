"""Tenant database enum types.

Each phase adds only the enums its tables need, so a tenant database never
carries types for features it does not have yet.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum

# Re-exported, not redefined. Period semantics (Indian FY boundaries, key
# formats) live in the billing engine, and a second enum with the same
# members would compare unequal by identity — which is exactly the bug this
# import prevents.
from app.engines.billing.periods import BillingFrequency


def _pg_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class ThemeMode(StrEnum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class OccupancyStatus(StrEnum):
    OWNER_OCCUPIED = "OWNER_OCCUPIED"
    RENTED = "RENTED"
    VACANT = "VACANT"


class ResidentType(StrEnum):
    OWNER = "OWNER"
    TENANT = "TENANT"


class FamilyRelationship(StrEnum):
    """How a family member relates to the resident who registered them."""

    SPOUSE = "SPOUSE"
    FATHER = "FATHER"
    MOTHER = "MOTHER"
    SON = "SON"
    DAUGHTER = "DAUGHTER"
    BROTHER = "BROTHER"
    SISTER = "SISTER"
    GRANDPARENT = "GRANDPARENT"
    GRANDCHILD = "GRANDCHILD"
    OTHER = "OTHER"


class FamilyAccessLevel(StrEnum):
    """How much of the flat a family member may see once they can sign in.

    ``NONE`` is the default: on the household roster, but with no login. A
    level other than ``NONE`` requires an email, which is checked by
    ``ck_family_members_access_needs_email``.

    Each level maps to exactly one tenant role — see ``ACCESS_LEVEL_ROLES`` in
    ``app.core.permissions``. The level is the source of truth; the role is
    derived from it and never edited directly.
    """

    NONE = "NONE"
    CHILD = "CHILD"
    MEMBER = "MEMBER"
    CO_ADMIN = "CO_ADMIN"


class BillingRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    """Some flats failed; the rest generated. Distinct from FAILED so an admin
    can publish the good ones and fix the rest."""
    FAILED = "FAILED"
    PUBLISHED = "PUBLISHED"


class BillStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    VOID = "VOID"


class PaymentStatus(StrEnum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class PaymentMethod(StrEnum):
    CASH = "CASH"
    CHEQUE = "CHEQUE"
    NEFT = "NEFT"
    UPI = "UPI"
    CARD = "CARD"
    NETBANKING = "NETBANKING"
    ADJUSTMENT = "ADJUSTMENT"


class AssignmentScope(StrEnum):
    ALL = "ALL"
    BUILDING = "BUILDING"
    BLOCK = "BLOCK"
    FLAT_TYPE = "FLAT_TYPE"
    FLAT = "FLAT"


SCOPE_SPECIFICITY: dict[AssignmentScope, int] = {
    AssignmentScope.ALL: 0,
    AssignmentScope.BUILDING: 1,
    AssignmentScope.BLOCK: 2,
    AssignmentScope.FLAT_TYPE: 3,
    AssignmentScope.FLAT: 4,
}
"""Most specific wins when several assignments match one flat."""


class NotificationChannel(StrEnum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
    PUSH = "PUSH"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"


theme_mode_enum = _pg_enum(ThemeMode, "theme_mode")
billing_frequency_enum = _pg_enum(BillingFrequency, "billing_frequency")
notification_channel_enum = _pg_enum(NotificationChannel, "notification_channel")
occupancy_status_enum = _pg_enum(OccupancyStatus, "occupancy_status")
resident_type_enum = _pg_enum(ResidentType, "resident_type")
family_relationship_enum = _pg_enum(FamilyRelationship, "family_relationship")
family_access_level_enum = _pg_enum(FamilyAccessLevel, "family_access_level")
billing_run_status_enum = _pg_enum(BillingRunStatus, "billing_run_status")
bill_status_enum = _pg_enum(BillStatus, "bill_status")
payment_status_enum = _pg_enum(PaymentStatus, "payment_status")
payment_method_enum = _pg_enum(PaymentMethod, "payment_method")
assignment_scope_enum = _pg_enum(AssignmentScope, "assignment_scope")


# --------------------------------------------------------------------------- #
# Phase 5 — operations and community
# --------------------------------------------------------------------------- #


class Priority(StrEnum):
    """Shared by complaints, tasks and incidents.

    One enum rather than three near-identical ones: an admin filtering "show me
    everything urgent" across the operations screens compares the same values,
    and a report can group by priority without a translation table.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class ComplaintCategory(StrEnum):
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    LIFT = "LIFT"
    HOUSEKEEPING = "HOUSEKEEPING"
    SECURITY = "SECURITY"
    PARKING = "PARKING"
    NOISE = "NOISE"
    WATER_SUPPLY = "WATER_SUPPLY"
    COMMON_AREA = "COMMON_AREA"
    BILLING = "BILLING"
    OTHER = "OTHER"


class ComplaintStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    """Closed by the resident, or auto-closed after the grace window. Terminal:
    a recurrence is a new ticket, so resolution time stays honest."""
    REJECTED = "REJECTED"
    REOPENED = "REOPENED"


COMPLAINT_TRANSITIONS: dict[ComplaintStatus, frozenset[ComplaintStatus]] = {
    ComplaintStatus.OPEN: frozenset(
        {
            ComplaintStatus.ACKNOWLEDGED,
            ComplaintStatus.IN_PROGRESS,
            ComplaintStatus.RESOLVED,
            ComplaintStatus.REJECTED,
        }
    ),
    ComplaintStatus.ACKNOWLEDGED: frozenset(
        {
            ComplaintStatus.IN_PROGRESS,
            ComplaintStatus.RESOLVED,
            ComplaintStatus.REJECTED,
        }
    ),
    ComplaintStatus.IN_PROGRESS: frozenset(
        {ComplaintStatus.RESOLVED, ComplaintStatus.REJECTED}
    ),
    ComplaintStatus.RESOLVED: frozenset({ComplaintStatus.CLOSED, ComplaintStatus.REOPENED}),
    ComplaintStatus.REOPENED: frozenset(
        {
            ComplaintStatus.ACKNOWLEDGED,
            ComplaintStatus.IN_PROGRESS,
            ComplaintStatus.RESOLVED,
            ComplaintStatus.REJECTED,
        }
    ),
    ComplaintStatus.REJECTED: frozenset({ComplaintStatus.REOPENED}),
    ComplaintStatus.CLOSED: frozenset(),
}
"""The only legal moves.

A workflow expressed as data is enforced in one place and testable on its own;
the same workflow spelled out in ``if`` branches across a service is neither.
"""

OPEN_COMPLAINT_STATUSES: frozenset[ComplaintStatus] = frozenset(
    {
        ComplaintStatus.OPEN,
        ComplaintStatus.ACKNOWLEDGED,
        ComplaintStatus.IN_PROGRESS,
        ComplaintStatus.REOPENED,
    }
)
"""Still someone's problem. Drives the SLA clock and every "open" count."""


class Department(StrEnum):
    """Which team owns a task.

    Maintenance and housekeeping have identical workflows and separate
    permissions, so they share one table and are told apart by this column
    rather than living in two near-copies that drift.
    """

    MAINTENANCE = "MAINTENANCE"
    HOUSEKEEPING = "HOUSEKEEPING"


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    """Signed off by a supervisor. A worker marks COMPLETED and only an admin
    VERIFIES, so "done" and "checked" remain different facts."""
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset(
        {
            TaskStatus.IN_PROGRESS,
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
        }
    ),
    TaskStatus.IN_PROGRESS: frozenset(
        {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}
    ),
    # COMPLETED -> IN_PROGRESS is deliberate: a supervisor who inspects the
    # work and finds it unfinished sends it back rather than opening a second
    # task for the same job.
    TaskStatus.COMPLETED: frozenset({TaskStatus.VERIFIED, TaskStatus.IN_PROGRESS}),
    TaskStatus.VERIFIED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.SKIPPED: frozenset(),
}

OPEN_TASK_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}
)


class Recurrence(StrEnum):
    """How often a schedule spawns its next task.

    Deliberately not ``BillingFrequency``: a lift service runs weekly and a
    bill never does, and sharing the enum would put FORTNIGHTLY into a billing
    period parser that cannot express it.
    """

    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    FORTNIGHTLY = "FORTNIGHTLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    HALF_YEARLY = "HALF_YEARLY"
    YEARLY = "YEARLY"


RECURRENCE_MONTHS: dict[Recurrence, int] = {
    Recurrence.MONTHLY: 1,
    Recurrence.QUARTERLY: 3,
    Recurrence.HALF_YEARLY: 6,
    Recurrence.YEARLY: 12,
}
"""Calendar-month recurrences.

A monthly lift service due on the 31st has to land on the 30th in April, and
day arithmetic cannot express that. The rest advance by whole days.
"""

RECURRENCE_DAYS: dict[Recurrence, int] = {
    Recurrence.DAILY: 1,
    Recurrence.WEEKLY: 7,
    Recurrence.FORTNIGHTLY: 14,
}


class VisitorType(StrEnum):
    GUEST = "GUEST"
    DELIVERY = "DELIVERY"
    CAB = "CAB"
    SERVICE = "SERVICE"
    """Plumber, electrician, carpenter — invited by a resident."""
    DOMESTIC_HELP = "DOMESTIC_HELP"
    VENDOR = "VENDOR"
    OTHER = "OTHER"


class VisitorStatus(StrEnum):
    EXPECTED = "EXPECTED"
    """Pre-approved by the resident before arrival."""
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    """Standing at the gate; the resident has not answered yet."""
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    EXPIRED = "EXPIRED"
    """A pre-approval whose window passed with no arrival."""


VISITOR_TRANSITIONS: dict[VisitorStatus, frozenset[VisitorStatus]] = {
    # EXPECTED -> APPROVED is a code-less pre-approval (a delivery, a cab)
    # being claimed by the rider who actually turned up; it then cannot be
    # claimed a second time.
    VisitorStatus.EXPECTED: frozenset(
        {
            VisitorStatus.APPROVED,
            VisitorStatus.CHECKED_IN,
            VisitorStatus.DENIED,
            VisitorStatus.EXPIRED,
        }
    ),
    VisitorStatus.AWAITING_APPROVAL: frozenset(
        {VisitorStatus.APPROVED, VisitorStatus.DENIED, VisitorStatus.EXPIRED}
    ),
    VisitorStatus.APPROVED: frozenset({VisitorStatus.CHECKED_IN, VisitorStatus.EXPIRED}),
    VisitorStatus.CHECKED_IN: frozenset({VisitorStatus.CHECKED_OUT}),
    VisitorStatus.CHECKED_OUT: frozenset(),
    VisitorStatus.DENIED: frozenset(),
    VisitorStatus.EXPIRED: frozenset(),
}
"""A gate log has to survive being read back months later, so the moves close.

Note what is absent: nothing returns to AWAITING_APPROVAL, and a DENIED visitor
cannot be walked in — that takes a fresh entry, under whoever let them in.
"""

ON_PREMISES_STATUSES: frozenset[VisitorStatus] = frozenset({VisitorStatus.CHECKED_IN})


class IncidentSeverity(StrEnum):
    INFO = "INFO"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentStatus(StrEnum):
    REPORTED = "REPORTED"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class NoticeCategory(StrEnum):
    GENERAL = "GENERAL"
    URGENT = "URGENT"
    MAINTENANCE = "MAINTENANCE"
    EVENT = "EVENT"
    MEETING = "MEETING"
    BILLING = "BILLING"
    SECURITY = "SECURITY"


class AudienceScope(StrEnum):
    """Who a notice reaches.

    Mirrors ``AssignmentScope`` in shape but not in meaning — a bill template
    resolves to exactly one flat by specificity, whereas a notice fans out to
    everyone who matches. Sharing the enum would invite sharing the resolver.
    """

    ALL = "ALL"
    BUILDING = "BUILDING"
    BLOCK = "BLOCK"
    OWNERS = "OWNERS"
    TENANTS = "TENANTS"
    STAFF = "STAFF"


class BookingStatus(StrEnum):
    PENDING = "PENDING"
    """Awaiting approval, for amenities configured to require it."""
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


ACTIVE_BOOKING_STATUSES: frozenset[BookingStatus] = frozenset(
    {BookingStatus.PENDING, BookingStatus.CONFIRMED}
)
"""Statuses that hold a slot.

The exclusion constraint that makes a double booking impossible is defined over
exactly these — a cancelled booking must not keep the clubhouse blocked.
"""


priority_enum = _pg_enum(Priority, "priority")
complaint_category_enum = _pg_enum(ComplaintCategory, "complaint_category")
complaint_status_enum = _pg_enum(ComplaintStatus, "complaint_status")
department_enum = _pg_enum(Department, "department")
task_status_enum = _pg_enum(TaskStatus, "task_status")
recurrence_enum = _pg_enum(Recurrence, "recurrence")
visitor_type_enum = _pg_enum(VisitorType, "visitor_type")
visitor_status_enum = _pg_enum(VisitorStatus, "visitor_status")
incident_severity_enum = _pg_enum(IncidentSeverity, "incident_severity")
incident_status_enum = _pg_enum(IncidentStatus, "incident_status")
notice_category_enum = _pg_enum(NoticeCategory, "notice_category")
audience_scope_enum = _pg_enum(AudienceScope, "audience_scope")
booking_status_enum = _pg_enum(BookingStatus, "booking_status")
