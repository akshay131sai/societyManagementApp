"""Society-scoped endpoints.

Every route here operates on the caller's own tenant session. There is no
society parameter anywhere in this module — by construction.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import (
    CentralSession,
    ContextDep,
    SocietyMember,
    TenantSession,
    require_permission,
)
from app.auth.principal import Principal
from app.core.permissions import Permission
from app.schemas.common import Envelope, Page, PageParams, ok
from app.schemas.society import (
    RoleWithPermissions,
    SocietyDashboard,
    SocietySettingsRead,
    SocietySettingsUpdate,
    TenantUserCreate,
    TenantUserRead,
    TenantUserUpdate,
    UserRolesUpdate,
)
from app.schemas.theme import ThemePresets, ThemeRead, ThemeUpdate
from app.services.society import (
    RoleService,
    SocietyDashboardService,
    SocietySettingsService,
    TenantUserService,
    ThemeService,
)

router = APIRouter(tags=["society"])

PageDep = Annotated[PageParams, Depends()]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# --------------------------------------------------------------------------- #
# Society
# --------------------------------------------------------------------------- #


@router.get("/society", response_model=Envelope[dict], summary="Current society")
async def get_society(context: ContextDep) -> dict[str, Any]:
    society = context.society
    if society is None:
        return ok(None)
    return ok(
        {
            "id": society.id,
            "name": society.name,
            "slug": society.slug,
            "status": society.status,
            "city": society.city,
            "state": society.state,
            "pincode": society.pincode,
            "contact_email": society.contact_email,
            "contact_phone": society.contact_phone,
            "timezone": society.timezone,
            "total_flats": society.total_flats,
        }
    )


@router.get(
    "/society/dashboard", response_model=Envelope[SocietyDashboard], summary="Society dashboard"
)
async def society_dashboard(
    context: ContextDep,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.SOCIETY_READ))],
) -> dict[str, Any]:
    data = await SocietyDashboardService(tenant).build(principal)
    sub = context.subscription
    data["subscription_status"] = sub.status.value if sub else "NONE"
    data["subscription_days_remaining"] = (
        max((sub.end_date - date.today()).days, 0) if sub else 0
    )
    data["provisioned_at"] = context.society.created_at if context.society else None
    return ok(data)


@router.get(
    "/society/settings",
    response_model=Envelope[SocietySettingsRead],
    summary="Society settings",
)
async def get_settings(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.SOCIETY_READ))],
) -> dict[str, Any]:
    settings = await SocietySettingsService(tenant).get()
    return ok(SocietySettingsRead.model_validate(settings))


@router.put(
    "/society/settings",
    response_model=Envelope[SocietySettingsRead],
    summary="Update society settings",
)
async def update_settings(
    body: SocietySettingsUpdate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.SOCIETY_SETTINGS_MANAGE))
    ],
) -> dict[str, Any]:
    settings = await SocietySettingsService(tenant).update(
        body, principal, request_id=_rid(request)
    )
    return ok(SocietySettingsRead.model_validate(settings), message="Settings updated.")


# --------------------------------------------------------------------------- #
# Theme
# --------------------------------------------------------------------------- #


@router.get("/theme", response_model=Envelope[ThemeRead], summary="Current society theme")
async def get_theme(
    context: ContextDep,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.THEME_READ))],
) -> dict[str, Any]:
    theme = await ThemeService(tenant).get()
    payload = ThemeRead.model_validate(theme).model_dump()
    payload["society_name"] = context.society.name if context.society else None
    return ok(payload)


@router.put("/theme", response_model=Envelope[ThemeRead], summary="Update the society theme")
async def update_theme(
    body: ThemeUpdate,
    request: Request,
    context: ContextDep,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.THEME_UPDATE))],
) -> dict[str, Any]:
    theme = await ThemeService(tenant).update(body, principal, request_id=_rid(request))
    payload = ThemeRead.model_validate(theme).model_dump()
    payload["society_name"] = context.society.name if context.society else None
    return ok(payload, message="Appearance updated.")


@router.post("/theme/reset", response_model=Envelope[ThemeRead], summary="Reset to default theme")
async def reset_theme(
    request: Request,
    context: ContextDep,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.THEME_UPDATE))],
) -> dict[str, Any]:
    theme = await ThemeService(tenant).reset(principal, request_id=_rid(request))
    payload = ThemeRead.model_validate(theme).model_dump()
    payload["society_name"] = context.society.name if context.society else None
    return ok(payload, message="Appearance reset to default.")


@router.get("/theme/presets", response_model=Envelope[ThemePresets], summary="Theme presets")
async def theme_presets(principal: SocietyMember) -> dict[str, Any]:
    return ok(ThemePresets())


# --------------------------------------------------------------------------- #
# Users & roles
# --------------------------------------------------------------------------- #


@router.get("/users", response_model=Envelope[Page[TenantUserRead]], summary="List society users")
async def list_users(
    tenant: TenantSession,
    params: PageDep,
    principal: Annotated[Principal, Depends(require_permission(Permission.USER_READ))],
    role: Annotated[str | None, Query(max_length=50)] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> dict[str, Any]:
    rows, total = await TenantUserService(tenant).list(
        page=params.page, limit=params.limit, q=params.q, role_code=role, is_active=is_active
    )
    return ok(Page.build(rows, page=params.page, limit=params.limit, total=total))


@router.post(
    "/users",
    response_model=Envelope[TenantUserRead],
    status_code=201,
    summary="Create a society user",
    description=(
        "Creates the tenant user *and* the matching central platform_users row "
        "so the account can authenticate. Both writes happen before either "
        "session commits."
    ),
)
async def create_user(
    body: TenantUserCreate,
    request: Request,
    tenant: TenantSession,
    central: CentralSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.USER_CREATE))],
) -> dict[str, Any]:
    from app.models.central import PlatformUser
    from app.repositories.central import PlatformUserRepository

    service = TenantUserService(tenant)
    user = await service.create(body, principal, request_id=_rid(request))

    # The central row is what makes this account resolvable at sign-in.
    repo = PlatformUserRepository(central)
    existing = await repo.get_by_email_in_society(str(body.email), principal.society_id)
    if existing is None:
        await repo.create(
            PlatformUser(
                firebase_uid=body.firebase_uid or f"pending:{str(body.email).lower()}",
                email=str(body.email).lower(),
                phone=body.phone,
                display_name=body.full_name,
                is_super_admin=False,
                society_id=principal.society_id,
                tenant_user_id=user["id"],
                is_active=True,
            )
        )
    else:
        existing.tenant_user_id = user["id"]

    return ok(user, message="User created.")


@router.get("/users/{user_id}", response_model=Envelope[TenantUserRead], summary="User detail")
async def get_user(
    user_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.USER_READ))],
) -> dict[str, Any]:
    return ok(await TenantUserService(tenant).get(user_id))


@router.patch(
    "/users/{user_id}", response_model=Envelope[TenantUserRead], summary="Update a user"
)
async def update_user(
    user_id: uuid.UUID,
    body: TenantUserUpdate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.USER_UPDATE))],
) -> dict[str, Any]:
    user = await TenantUserService(tenant).update(
        user_id, body, principal, request_id=_rid(request)
    )
    return ok(user, message="User updated.")


@router.put(
    "/users/{user_id}/roles", response_model=Envelope[TenantUserRead], summary="Set user roles"
)
async def set_user_roles(
    user_id: uuid.UUID,
    body: UserRolesUpdate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.ROLE_ASSIGN))],
) -> dict[str, Any]:
    user = await TenantUserService(tenant).set_roles(
        user_id, body.role_codes, principal, request_id=_rid(request)
    )
    return ok(user, message="Roles updated.")


@router.delete("/users/{user_id}", response_model=Envelope[dict], summary="Deactivate a user")
async def deactivate_user(
    user_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.USER_DELETE))],
) -> dict[str, Any]:
    await TenantUserService(tenant).deactivate(user_id, principal, request_id=_rid(request))
    return ok({"deactivated": True}, message="User deactivated.")


@router.get(
    "/roles", response_model=Envelope[list[RoleWithPermissions]], summary="Roles and permissions"
)
async def list_roles(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.USER_READ))],
) -> dict[str, Any]:
    return ok(await RoleService(tenant).list_with_permissions())
