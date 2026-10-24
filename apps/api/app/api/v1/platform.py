"""Platform endpoints — SUPER_ADMIN only, central database.

``POST /platform/societies`` is the only endpoint in the API that accepts
society identity as input, because it is creating one. Everywhere else the
society is resolved from the principal.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CentralSession, SuperAdmin, TenantManager
from app.core.errors import NotFoundError
from app.models.central import SocietyStatus
from app.schemas.common import Envelope, Page, PageParams, ok
from app.schemas.platform import (
    PlanCreate,
    PlanRead,
    PlanUpdate,
    SocietyCreate,
    SocietyDetail,
    SocietyLockRequest,
    SocietyProvisionResult,
    SocietyRead,
    SocietyUpdate,
    SubscriptionAssign,
    SubscriptionExtend,
    SubscriptionRead,
)
from app.services.platform import (
    PlanService,
    PlatformAuditService,
    PlatformUserService,
    SocietyService,
    SubscriptionService,
)

router = APIRouter(prefix="/platform", tags=["platform"])

PageDep = Annotated[PageParams, Depends()]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #


@router.get("/dashboard", response_model=Envelope[dict], summary="Platform dashboard")
async def dashboard(
    principal: SuperAdmin, central: CentralSession, manager: TenantManager
) -> dict[str, Any]:
    return ok(await SocietyService(central, manager).dashboard())


# --------------------------------------------------------------------------- #
# Societies
# --------------------------------------------------------------------------- #


@router.get("/societies", response_model=Envelope[Page[SocietyRead]], summary="List societies")
async def list_societies(
    principal: SuperAdmin,
    central: CentralSession,
    manager: TenantManager,
    params: PageDep,
    status: Annotated[SocietyStatus | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    service = SocietyService(central, manager)
    rows, total = await service.societies.list(
        page=params.page,
        limit=params.limit,
        q=params.q,
        status=status,
        include_archived=include_archived,
    )
    return ok(
        Page.build(
            [SocietyRead.model_validate(r) for r in rows],
            page=params.page,
            limit=params.limit,
            total=total,
        )
    )


@router.post(
    "/societies",
    response_model=Envelope[SocietyProvisionResult],
    status_code=201,
    summary="Create and provision a society",
    description=(
        "Creates the central record, allocates and creates the tenant "
        "PostgreSQL database, runs tenant migrations, seeds roles, permissions, "
        "settings and theme, creates the society admin and assigns a "
        "subscription. Idempotent and resumable via the retry endpoint."
    ),
)
async def create_society(
    body: SocietyCreate,
    request: Request,
    principal: SuperAdmin,
    central: CentralSession,
    manager: TenantManager,
) -> dict[str, Any]:
    result = await SocietyService(central, manager).create(
        body, principal, request_id=_rid(request)
    )
    return ok(
        {
            "society": SocietyRead.model_validate(result.society),
            "database_name": result.database_name,
            "alembic_revision": result.alembic_revision,
            "admin_email": result.admin.email,
            "admin_firebase_uid": result.admin.firebase_uid,
            "subscription": {
                "id": result.subscription.id,
                "plan_name": result.subscription.plan.name if result.subscription.plan else None,
                "status": result.subscription.status,
                "start_date": result.subscription.start_date,
                "end_date": result.subscription.end_date,
            },
            "resumed": result.resumed,
        },
        message=f"Society '{result.society.name}' provisioned successfully.",
    )


@router.get(
    "/societies/{society_id}",
    response_model=Envelope[SocietyDetail],
    summary="Society detail",
)
async def get_society(
    society_id: uuid.UUID,
    principal: SuperAdmin,
    central: CentralSession,
    manager: TenantManager,
) -> dict[str, Any]:
    detail = await SocietyService(central, manager).detail(society_id)
    payload = SocietyDetail.model_validate(detail["society"]).model_dump()
    payload["registry"] = detail["registry"]
    payload["user_count"] = detail["user_count"]
    payload["admin_count"] = detail["admin_count"]
    if (sub := detail["subscription"]) is not None:
        from datetime import date

        payload["subscription"] = {
            "id": sub.id,
            "plan_name": sub.plan.name if sub.plan else None,
            "status": sub.status,
            "start_date": sub.start_date,
            "end_date": sub.end_date,
            "days_remaining": max((sub.end_date - date.today()).days, 0),
        }
    return ok(payload)


@router.patch(
    "/societies/{society_id}", response_model=Envelope[SocietyRead], summary="Update a society"
)
async def update_society(
    society_id: uuid.UUID,
    body: SocietyUpdate,
    request: Request,
    principal: SuperAdmin,
    central: CentralSession,
    manager: TenantManager,
) -> dict[str, Any]:
    society = await SocietyService(central, manager).update(
        society_id, body, principal, request_id=_rid(request)
    )
    return ok(SocietyRead.model_validate(society), message="Society updated.")


@router.post(
    "/societies/{society_id}/lock",
    response_model=Envelope[SocietyRead],
    summary="Lock a society",
)
async def lock_society(
    society_id: uuid.UUID,
    body: SocietyLockRequest,
    request: Request,
    principal: SuperAdmin,
    central: CentralSession,
    manager: TenantManager,
) -> dict[str, Any]:
    society = await SocietyService(central, manager).lock(
        society_id, body.reason, principal, request_id=_rid(request)
    )
    return ok(SocietyRead.model_validate(society), message="Society locked.")


@router.post(
    "/societies/{society_id}/unlock",
    response_model=Envelope[SocietyRead],
    summary="Unlock a society",
)
async def unlock_society(
    society_id: uuid.UUID,
    request: Request,
    principal: SuperAdmin,
    central: CentralSession,
    manager: TenantManager,
) -> dict[str, Any]:
    society = await SocietyService(central, manager).unlock(
        society_id, principal, request_id=_rid(request)
    )
    return ok(SocietyRead.model_validate(society), message="Society unlocked.")


@router.post(
    "/societies/{society_id}/archive",
    response_model=Envelope[SocietyRead],
    summary="Archive a society",
)
async def archive_society(
    society_id: uuid.UUID,
    request: Request,
    principal: SuperAdmin,
    central: CentralSession,
    manager: TenantManager,
) -> dict[str, Any]:
    society = await SocietyService(central, manager).archive(
        society_id, principal, request_id=_rid(request)
    )
    return ok(SocietyRead.model_validate(society), message="Society archived.")


@router.post(
    "/societies/{society_id}/retry-provisioning",
    response_model=Envelope[SocietyProvisionResult],
    summary="Resume failed provisioning",
)
async def retry_provisioning(
    society_id: uuid.UUID,
    request: Request,
    principal: SuperAdmin,
    central: CentralSession,
    manager: TenantManager,
) -> dict[str, Any]:
    result = await SocietyService(central, manager).retry_provisioning(
        society_id, principal, request_id=_rid(request)
    )
    return ok(
        {
            "society": SocietyRead.model_validate(result.society),
            "database_name": result.database_name,
            "alembic_revision": result.alembic_revision,
            "admin_email": result.admin.email,
            "admin_firebase_uid": result.admin.firebase_uid,
            "subscription": {
                "id": result.subscription.id,
                "plan_name": result.subscription.plan.name if result.subscription.plan else None,
                "status": result.subscription.status,
                "start_date": result.subscription.start_date,
                "end_date": result.subscription.end_date,
            },
            "resumed": True,
        },
        message="Provisioning resumed successfully.",
    )


@router.get(
    "/societies/{society_id}/verify",
    response_model=Envelope[dict],
    summary="Verify tenant database contents",
    description="Diagnostic: reports the tables, roles and seeded data actually "
    "present in the society's own database.",
)
async def verify_society(
    society_id: uuid.UUID,
    principal: SuperAdmin,
    central: CentralSession,
    manager: TenantManager,
) -> dict[str, Any]:
    from app.repositories.central import DatabaseRegistryRepository
    from app.services.provisioning import ProvisioningService

    registry = await DatabaseRegistryRepository(central).get_by_society(society_id)
    if registry is None:
        raise NotFoundError("Database registration")
    await manager.register(society_id, registry.database_name)
    return ok(await ProvisioningService(central, manager).verify_tenant(society_id))


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #


@router.get("/plans", response_model=Envelope[list[PlanRead]], summary="List plans")
async def list_plans(
    principal: SuperAdmin,
    central: CentralSession,
    active_only: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    plans = await PlanService(central).list(active_only=active_only)
    return ok([PlanRead.model_validate(p) for p in plans])


@router.post(
    "/plans", response_model=Envelope[PlanRead], status_code=201, summary="Create a plan"
)
async def create_plan(
    body: PlanCreate, request: Request, principal: SuperAdmin, central: CentralSession
) -> dict[str, Any]:
    plan = await PlanService(central).create(body, principal, request_id=_rid(request))
    return ok(PlanRead.model_validate(plan), message="Plan created.")


@router.patch("/plans/{plan_id}", response_model=Envelope[PlanRead], summary="Update a plan")
async def update_plan(
    plan_id: uuid.UUID,
    body: PlanUpdate,
    request: Request,
    principal: SuperAdmin,
    central: CentralSession,
) -> dict[str, Any]:
    plan = await PlanService(central).update(plan_id, body, principal, request_id=_rid(request))
    return ok(PlanRead.model_validate(plan), message="Plan updated.")


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #


@router.get(
    "/subscriptions",
    response_model=Envelope[list[SubscriptionRead]],
    summary="Subscriptions for a society",
)
async def list_subscriptions(
    principal: SuperAdmin,
    central: CentralSession,
    society_id: Annotated[uuid.UUID, Query()],
) -> dict[str, Any]:
    from app.repositories.central import SubscriptionRepository

    rows = await SubscriptionRepository(central).list_by_society(society_id)
    return ok(
        [
            SubscriptionRead.model_validate(r).model_copy(
                update={"plan_name": r.plan.name if r.plan else None}
            )
            for r in rows
        ]
    )


@router.post(
    "/subscriptions",
    response_model=Envelope[SubscriptionRead],
    status_code=201,
    summary="Assign a subscription",
)
async def assign_subscription(
    body: SubscriptionAssign,
    request: Request,
    principal: SuperAdmin,
    central: CentralSession,
    manager: TenantManager,
) -> dict[str, Any]:
    sub = await SubscriptionService(central, manager).assign(
        body, principal, request_id=_rid(request)
    )
    return ok(SubscriptionRead.model_validate(sub), message="Subscription assigned.")


@router.post(
    "/subscriptions/{subscription_id}/extend",
    response_model=Envelope[SubscriptionRead],
    summary="Extend a subscription",
)
async def extend_subscription(
    subscription_id: uuid.UUID,
    body: SubscriptionExtend,
    request: Request,
    principal: SuperAdmin,
    central: CentralSession,
    manager: TenantManager,
) -> dict[str, Any]:
    sub = await SubscriptionService(central, manager).extend(
        subscription_id, body, principal, request_id=_rid(request)
    )
    return ok(SubscriptionRead.model_validate(sub), message="Subscription extended.")


@router.post(
    "/subscriptions/{subscription_id}/suspend",
    response_model=Envelope[SubscriptionRead],
    summary="Suspend a subscription",
)
async def suspend_subscription(
    subscription_id: uuid.UUID,
    request: Request,
    principal: SuperAdmin,
    central: CentralSession,
    manager: TenantManager,
    reason: Annotated[str | None, Query(max_length=500)] = None,
) -> dict[str, Any]:
    sub = await SubscriptionService(central, manager).suspend(
        subscription_id, reason, principal, request_id=_rid(request)
    )
    return ok(SubscriptionRead.model_validate(sub), message="Subscription suspended.")


# --------------------------------------------------------------------------- #
# Users & audit
# --------------------------------------------------------------------------- #


@router.get("/users", response_model=Envelope[Page[dict]], summary="List platform users")
async def list_platform_users(
    principal: SuperAdmin,
    central: CentralSession,
    params: PageDep,
    society_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    from app.schemas.platform import PlatformUserRead

    rows, total = await PlatformUserService(central).list(
        page=params.page, limit=params.limit, q=params.q, society_id=society_id
    )
    return ok(
        Page.build(
            [PlatformUserRead.model_validate(r).model_dump() for r in rows],
            page=params.page,
            limit=params.limit,
            total=total,
        )
    )


@router.get("/audit-logs", response_model=Envelope[Page[dict]], summary="Platform audit log")
async def list_audit_logs(
    principal: SuperAdmin,
    central: CentralSession,
    params: PageDep,
    society_id: Annotated[uuid.UUID | None, Query()] = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
) -> dict[str, Any]:
    from app.schemas.platform import AuditLogRead

    rows, total = await PlatformAuditService(central).list(
        page=params.page, limit=params.limit, society_id=society_id, action=action
    )
    return ok(
        Page.build(
            [AuditLogRead.model_validate(r).model_dump() for r in rows],
            page=params.page,
            limit=params.limit,
            total=total,
        )
    )
