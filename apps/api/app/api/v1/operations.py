"""Complaints, maintenance, housekeeping, visitors and security incidents.

Maintenance and housekeeping are the same resource shape twice over Ã¢â‚¬â€ the same
trick the utility routes use Ã¢â‚¬â€ so their routes are generated from one factory
and mounted under two prefixes with two permission sets. Writing them out twice
would mean fixing every bug twice.

As everywhere else in the tenant API: no society parameter appears in any
signature. The tenant is the session.
"""

# No ``from __future__ import annotations`` here, deliberately. The work routes
# are built by a factory, so their annotations reference closure variables
# (``read``, ``manage``, ``progress``); stringified annotations are resolved
# against module globals, where those names do not exist.

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import TenantSession, require_any_permission, require_permission
from app.auth.principal import Principal
from app.core.permissions import Permission
from app.models.tenant import Department, VisitorStatus
from app.schemas.common import Envelope, Page, PageParams, ok
from app.schemas.operations import (
    ComplaintAssign,
    ComplaintCommentCreate,
    ComplaintCommentRead,
    ComplaintCreate,
    ComplaintDetail,
    ComplaintRating,
    ComplaintRead,
    ComplaintSummary,
    ComplaintTransition,
    ComplaintUpdate,
    IncidentCreate,
    IncidentRead,
    IncidentUpdate,
    ScheduleRunResult,
    SecurityDashboard,
    VisitorCheckIn,
    VisitorDecision,
    VisitorGuardDecision,
    VisitorGateEntry,
    VisitorPreApprove,
    VisitorRead,
    VisitorSummary,
    WorkScheduleCreate,
    WorkScheduleRead,
    WorkScheduleUpdate,
    WorkSummary,
    WorkTaskCreate,
    WorkTaskProgress,
    WorkTaskRead,
    WorkTaskUpdate,
)
from app.services.operations import (
    ComplaintService,
    IncidentService,
    ScheduleGenerator,
    SecurityDashboardService,
    VisitorService,
    WorkService,
)

router = APIRouter(tags=["operations"])

PageDep = Annotated[PageParams, Depends()]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# --------------------------------------------------------------------------- #
# Complaints
# --------------------------------------------------------------------------- #

complaints = APIRouter(prefix="/complaints", tags=["complaints"])


@complaints.get("", response_model=Envelope[Page[ComplaintRead]], summary="List complaints")
async def list_complaints(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.COMPLAINT_READ))],
    params: PageDep,
    status_filter: Annotated[str | None, Query(alias="status", max_length=30)] = None,
    category: Annotated[str | None, Query(max_length=30)] = None,
    priority: Annotated[str | None, Query(max_length=20)] = None,
    assigned_to: uuid.UUID | None = None,
    flat_id: uuid.UUID | None = None,
    open_only: bool = False,
    overdue_only: bool = False,
    unassigned_only: bool = False,
    mine_only: bool = False,
) -> dict[str, Any]:
    items, total = await ComplaintService(tenant).list(
        principal,
        page=params.page,
        limit=params.limit,
        q=params.q,
        status=status_filter,
        category=category,
        priority=priority,
        assigned_to=assigned_to,
        flat_id=flat_id,
        open_only=open_only,
        overdue_only=overdue_only,
        unassigned_only=unassigned_only,
        mine_only=mine_only,
    )
    return ok(Page.build(items, page=params.page, limit=params.limit, total=total))


@complaints.get(
    "/summary",
    response_model=Envelope[ComplaintSummary],
    summary="Complaint counts, SLA performance and satisfaction",
)
async def complaint_summary(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.COMPLAINT_MANAGE))],
) -> dict[str, Any]:
    return ok(await ComplaintService(tenant).summary(principal))


@complaints.get(
    "/{complaint_id}",
    response_model=Envelope[ComplaintDetail],
    summary="Get a complaint with its timeline",
)
async def get_complaint(
    complaint_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.COMPLAINT_READ))],
) -> dict[str, Any]:
    return ok(await ComplaintService(tenant).get(complaint_id, principal))


@complaints.post(
    "",
    response_model=Envelope[ComplaintRead],
    status_code=status.HTTP_201_CREATED,
    summary="Raise a complaint",
)
async def create_complaint(
    payload: ComplaintCreate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.COMPLAINT_CREATE))],
    request: Request,
) -> dict[str, Any]:
    complaint = await ComplaintService(tenant).create(
        payload, principal, request_id=_rid(request)
    )
    return ok(complaint, f"Complaint {complaint['ticket_number']} raised.")


@complaints.patch(
    "/{complaint_id}", response_model=Envelope[ComplaintRead], summary="Edit a complaint"
)
async def update_complaint(
    complaint_id: uuid.UUID,
    payload: ComplaintUpdate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.COMPLAINT_READ))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await ComplaintService(tenant).update(
            complaint_id, payload, principal, request_id=_rid(request)
        ),
        "Complaint updated.",
    )


@complaints.post(
    "/{complaint_id}/assignment",
    response_model=Envelope[ComplaintRead],
    summary="Assign or unassign a complaint",
)
async def assign_complaint(
    complaint_id: uuid.UUID,
    payload: ComplaintAssign,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.COMPLAINT_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    complaint = await ComplaintService(tenant).assign(
        complaint_id, payload, principal, request_id=_rid(request)
    )
    return ok(complaint, "Assignment updated.")


@complaints.post(
    "/{complaint_id}/transition",
    response_model=Envelope[ComplaintRead],
    summary="Move a complaint through its workflow",
)
async def transition_complaint(
    complaint_id: uuid.UUID,
    payload: ComplaintTransition,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.COMPLAINT_READ))],
    request: Request,
) -> dict[str, Any]:
    complaint = await ComplaintService(tenant).transition(
        complaint_id, payload, principal, request_id=_rid(request)
    )
    return ok(complaint, f"Complaint is now {complaint['status'].value.lower()}.")


@complaints.post(
    "/{complaint_id}/rating",
    response_model=Envelope[ComplaintRead],
    summary="Rate a resolved complaint",
)
async def rate_complaint(
    complaint_id: uuid.UUID,
    payload: ComplaintRating,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.COMPLAINT_READ))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await ComplaintService(tenant).rate(
            complaint_id, payload, principal, request_id=_rid(request)
        ),
        "Thanks for the feedback.",
    )


@complaints.post(
    "/{complaint_id}/comments",
    response_model=Envelope[ComplaintCommentRead],
    status_code=status.HTTP_201_CREATED,
    summary="Add a comment to a complaint",
)
async def comment_on_complaint(
    complaint_id: uuid.UUID,
    payload: ComplaintCommentCreate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.COMPLAINT_READ))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await ComplaintService(tenant).comment(
            complaint_id, payload, principal, request_id=_rid(request)
        ),
        "Comment added.",
    )


router.include_router(complaints)


# --------------------------------------------------------------------------- #
# Work Ã¢â‚¬â€ maintenance and housekeeping from one factory
# --------------------------------------------------------------------------- #


def _work_routes(
    department: Department,
    *,
    read: Permission,
    manage: Permission,
    progress: Permission,
) -> APIRouter:
    route = "maintenance" if department is Department.MAINTENANCE else "housekeeping"
    label = route.capitalize()
    sub = APIRouter(prefix=f"/{route}", tags=[route])

    # -- schedules ---------------------------------------------------------- #

    @sub.get(
        "/schedules",
        response_model=Envelope[Page[WorkScheduleRead]],
        summary=f"List {route} schedules",
    )
    async def list_schedules(
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(read))],
        params: PageDep,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        items, total = await WorkService(tenant, department=department).list_schedules(
            page=params.page,
            limit=params.limit,
            q=params.q,
            active_only=not include_inactive,
        )
        return ok(Page.build(items, page=params.page, limit=params.limit, total=total))

    @sub.post(
        "/schedules",
        response_model=Envelope[WorkScheduleRead],
        status_code=status.HTTP_201_CREATED,
        summary=f"Create a recurring {route} schedule",
    )
    async def create_schedule(
        payload: WorkScheduleCreate,
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(manage))],
        request: Request,
    ) -> dict[str, Any]:
        return ok(
            await WorkService(tenant, department=department).create_schedule(
                payload, principal, request_id=_rid(request)
            ),
            "Schedule created.",
        )

    @sub.patch(
        "/schedules/{schedule_id}",
        response_model=Envelope[WorkScheduleRead],
        summary=f"Update a {route} schedule",
    )
    async def update_schedule(
        schedule_id: uuid.UUID,
        payload: WorkScheduleUpdate,
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(manage))],
        request: Request,
    ) -> dict[str, Any]:
        return ok(
            await WorkService(tenant, department=department).update_schedule(
                schedule_id, payload, principal, request_id=_rid(request)
            ),
            "Schedule updated.",
        )

    # -- tasks -------------------------------------------------------------- #

    @sub.get(
        "/tasks", response_model=Envelope[Page[WorkTaskRead]], summary=f"List {route} tasks"
    )
    async def list_tasks(
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(read))],
        params: PageDep,
        status_filter: Annotated[str | None, Query(alias="status", max_length=30)] = None,
        priority: Annotated[str | None, Query(max_length=20)] = None,
        assigned_to: uuid.UUID | None = None,
        schedule_id: uuid.UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        open_only: bool = False,
        overdue_only: bool = False,
        mine_only: bool = False,
    ) -> dict[str, Any]:
        items, total = await WorkService(tenant, department=department).list_tasks(
            principal,
            page=params.page,
            limit=params.limit,
            q=params.q,
            status=status_filter,
            priority=priority,
            assigned_to=assigned_to,
            schedule_id=schedule_id,
            from_date=from_date,
            to_date=to_date,
            open_only=open_only,
            overdue_only=overdue_only,
            mine_only=mine_only,
        )
        return ok(Page.build(items, page=params.page, limit=params.limit, total=total))

    @sub.get(
        "/summary", response_model=Envelope[WorkSummary], summary=f"{label} workload"
    )
    async def summary(
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(read))],
    ) -> dict[str, Any]:
        return ok(await WorkService(tenant, department=department).summary())

    @sub.get(
        "/tasks/{task_id}", response_model=Envelope[WorkTaskRead], summary=f"Get a {route} task"
    )
    async def get_task(
        task_id: uuid.UUID,
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(read))],
    ) -> dict[str, Any]:
        return ok(await WorkService(tenant, department=department).get_task(task_id, principal))

    @sub.post(
        "/tasks",
        response_model=Envelope[WorkTaskRead],
        status_code=status.HTTP_201_CREATED,
        summary=f"Create a {route} task",
    )
    async def create_task(
        payload: WorkTaskCreate,
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(manage))],
        request: Request,
    ) -> dict[str, Any]:
        return ok(
            await WorkService(tenant, department=department).create_task(
                payload, principal, request_id=_rid(request)
            ),
            "Task created.",
        )

    @sub.patch(
        "/tasks/{task_id}",
        response_model=Envelope[WorkTaskRead],
        summary=f"Update a {route} task",
    )
    async def update_task(
        task_id: uuid.UUID,
        payload: WorkTaskUpdate,
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(manage))],
        request: Request,
    ) -> dict[str, Any]:
        return ok(
            await WorkService(tenant, department=department).update_task(
                task_id, payload, principal, request_id=_rid(request)
            ),
            "Task updated.",
        )

    @sub.post(
        "/tasks/{task_id}/progress",
        response_model=Envelope[WorkTaskRead],
        summary=f"Record progress on a {route} task",
        description=(
            "The move is checked against the task workflow. A worker holding "
            "only the progress permission can start and complete a task; "
            "signing it off as verified, or cancelling it, needs the manage "
            "permission."
        ),
    )
    async def progress_task(
        task_id: uuid.UUID,
        payload: WorkTaskProgress,
        tenant: TenantSession,
        # Either grant opens the door; which *moves* each one allows is decided
        # in the service. A Society Admin deliberately does not hold the
        # progress permission Ã¢â‚¬â€ completing a worker's task on their behalf
        # would make "who did this" a lie Ã¢â‚¬â€ but must still be able to verify.
        principal: Annotated[
            Principal, Depends(require_any_permission(progress, manage))
        ],
        request: Request,
    ) -> dict[str, Any]:
        task = await WorkService(tenant, department=department).progress(
            task_id, payload, principal, request_id=_rid(request)
        )
        return ok(task, f"Task is now {task['status'].value.lower()}.")

    @sub.post(
        "/schedules/generate",
        response_model=Envelope[ScheduleRunResult],
        summary=f"Generate due {route} tasks now",
        description=(
            "The nightly worker does this automatically. The endpoint exists so "
            "an admin can pull the next round forward, and it is idempotent Ã¢â‚¬â€ "
            "running it twice creates nothing the second time."
        ),
    )
    async def generate(
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(manage))],
    ) -> dict[str, Any]:
        result = await ScheduleGenerator(tenant).run(principal=principal)
        return ok(result, f"{result['tasks_created']} task(s) created.")

    return sub


router.include_router(
    _work_routes(
        Department.MAINTENANCE,
        read=Permission.MAINTENANCE_READ,
        manage=Permission.MAINTENANCE_MANAGE,
        progress=Permission.MAINTENANCE_TASK_PROGRESS,
    )
)
router.include_router(
    _work_routes(
        Department.HOUSEKEEPING,
        read=Permission.HOUSEKEEPING_READ,
        manage=Permission.HOUSEKEEPING_MANAGE,
        progress=Permission.HOUSEKEEPING_TASK_PROGRESS,
    )
)


# --------------------------------------------------------------------------- #
# Visitors
# --------------------------------------------------------------------------- #

visitors = APIRouter(prefix="/visitors", tags=["visitors"])


@visitors.get("", response_model=Envelope[Page[VisitorRead]], summary="List visitors")
async def list_visitors(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.VISITOR_READ))],
    params: PageDep,
    status_filter: Annotated[str | None, Query(alias="status", max_length=30)] = None,
    visitor_type: Annotated[str | None, Query(max_length=30)] = None,
    flat_id: uuid.UUID | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    on_premises_only: bool = False,
) -> dict[str, Any]:
    items, total = await VisitorService(tenant).list(
        principal,
        page=params.page,
        limit=params.limit,
        q=params.q,
        status=status_filter,
        visitor_type=visitor_type,
        flat_id=flat_id,
        from_date=from_date,
        to_date=to_date,
        on_premises_only=on_premises_only,
    )
    return ok(Page.build(items, page=params.page, limit=params.limit, total=total))


@visitors.get(
    "/summary", response_model=Envelope[VisitorSummary], summary="Gate activity today"
)
async def visitor_summary(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.SECURITY_READ))],
) -> dict[str, Any]:
    return ok(await VisitorService(tenant).summary())


@visitors.get("/{visitor_id}", response_model=Envelope[VisitorRead], summary="Get a visitor")
async def get_visitor(
    visitor_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.VISITOR_READ))],
) -> dict[str, Any]:
    return ok(await VisitorService(tenant).get(visitor_id, principal))


@visitors.post(
    "/pre-approvals",
    response_model=Envelope[VisitorRead],
    status_code=status.HTTP_201_CREATED,
    summary="Pre-approve an expected visitor",
    description="Returns a pass code the resident shares with their guest.",
)
async def pre_approve(
    payload: VisitorPreApprove,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.VISITOR_CREATE))],
    request: Request,
) -> dict[str, Any]:
    visitor = await VisitorService(tenant).pre_approve(
        payload, principal, request_id=_rid(request)
    )
    return ok(visitor, f"Pass {visitor['pass_code']} created.")


@visitors.post(
    "/gate-entries",
    response_model=Envelope[VisitorRead],
    status_code=status.HTTP_201_CREATED,
    summary="Log a walk-up visitor at the gate",
    description="The flat is notified and must approve before check-in is allowed.",
)
async def gate_entry(
    payload: VisitorGateEntry,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.VISITOR_CREATE))],
    request: Request,
) -> dict[str, Any]:
    visitor = await VisitorService(tenant).log_at_gate(
        payload, principal, request_id=_rid(request)
    )
    if visitor["status"] is VisitorStatus.APPROVED:
        return ok(visitor, "The flat pre-approved this visitor. Check them in.")
    return ok(visitor, "Visitor logged. The flat has been notified.")


@visitors.post(
    "/{visitor_id}/decision",
    response_model=Envelope[VisitorRead],
    summary="Approve or deny a visitor",
)
async def decide_visitor(
    visitor_id: uuid.UUID,
    payload: VisitorDecision,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.VISITOR_APPROVE))],
    request: Request,
) -> dict[str, Any]:
    visitor = await VisitorService(tenant).decide(
        visitor_id, payload, principal, request_id=_rid(request)
    )
    return ok(visitor, "Visitor approved." if payload.approved else "Visitor denied.")


@visitors.post(
    "/{visitor_id}/guard-decision",
    response_model=Envelope[VisitorRead],
    summary="Record the flat's answer taken by phone, or turn a visitor away",
    description=(
        "For a walk-up the flat has not answered in the app. Admitting requires "
        "the name of the resident who approved on the call; turning away "
        "requires a reason. The flat's residents are notified either way."
    ),
)
async def guard_decide_visitor(
    visitor_id: uuid.UUID,
    payload: VisitorGuardDecision,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.SECURITY_READ))],
    request: Request,
) -> dict[str, Any]:
    visitor = await VisitorService(tenant).guard_decide(
        visitor_id, payload, principal, request_id=_rid(request)
    )
    return ok(visitor, "Visitor approved." if payload.approved else "Visitor turned away.")


@visitors.post(
    "/check-in",
    response_model=Envelope[VisitorRead],
    summary="Check a visitor in by pass code",
)
async def check_in_by_code(
    payload: VisitorCheckIn,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.SECURITY_READ))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await VisitorService(tenant).check_in(payload, principal, request_id=_rid(request)),
        "Visitor checked in.",
    )


@visitors.post(
    "/{visitor_id}/check-in",
    response_model=Envelope[VisitorRead],
    summary="Check a specific visitor in",
)
async def check_in(
    visitor_id: uuid.UUID,
    payload: VisitorCheckIn,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.SECURITY_READ))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await VisitorService(tenant).check_in(
            payload, principal, visitor_id=visitor_id, request_id=_rid(request)
        ),
        "Visitor checked in.",
    )


@visitors.post(
    "/{visitor_id}/check-out",
    response_model=Envelope[VisitorRead],
    summary="Check a visitor out",
)
async def check_out(
    visitor_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.SECURITY_READ))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await VisitorService(tenant).check_out(
            visitor_id, principal, request_id=_rid(request)
        ),
        "Visitor checked out.",
    )


router.include_router(visitors)


# --------------------------------------------------------------------------- #
# Security incidents
# --------------------------------------------------------------------------- #

security = APIRouter(prefix="/security", tags=["security"])


@security.get(
    "/dashboard",
    response_model=Envelope[SecurityDashboard],
    summary="Everything the gate screen needs",
)
async def security_dashboard(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.SECURITY_READ))],
) -> dict[str, Any]:
    return ok(await SecurityDashboardService(tenant).build())


@security.get(
    "/incidents", response_model=Envelope[Page[IncidentRead]], summary="List incidents"
)
async def list_incidents(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.SECURITY_READ))],
    params: PageDep,
    status_filter: Annotated[str | None, Query(alias="status", max_length=30)] = None,
    severity: Annotated[str | None, Query(max_length=20)] = None,
    from_date: date | None = None,
    to_date: date | None = None,
    open_only: bool = False,
) -> dict[str, Any]:
    items, total = await IncidentService(tenant).list(
        page=params.page,
        limit=params.limit,
        q=params.q,
        status=status_filter,
        severity=severity,
        from_date=from_date,
        to_date=to_date,
        open_only=open_only,
    )
    return ok(Page.build(items, page=params.page, limit=params.limit, total=total))


@security.get(
    "/incidents/{incident_id}", response_model=Envelope[IncidentRead], summary="Get an incident"
)
async def get_incident(
    incident_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.SECURITY_READ))],
) -> dict[str, Any]:
    return ok(await IncidentService(tenant).get(incident_id))


@security.post(
    "/incidents",
    response_model=Envelope[IncidentRead],
    status_code=status.HTTP_201_CREATED,
    summary="Report an incident",
)
async def create_incident(
    payload: IncidentCreate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.SECURITY_READ))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await IncidentService(tenant).create(payload, principal, request_id=_rid(request)),
        "Incident recorded.",
    )


@security.patch(
    "/incidents/{incident_id}",
    response_model=Envelope[IncidentRead],
    summary="Update an incident",
)
async def update_incident(
    incident_id: uuid.UUID,
    payload: IncidentUpdate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.SECURITY_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await IncidentService(tenant).update(
            incident_id, payload, principal, request_id=_rid(request)
        ),
        "Incident updated.",
    )


router.include_router(security)
