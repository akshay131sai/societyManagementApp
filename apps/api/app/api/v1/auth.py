"""Authentication endpoints."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import CentralSession, ContextDep, PrincipalDep, TenantManager
from app.core.firebase import get_token_verifier
from app.models.central.audit import AuditAction
from app.repositories.central import PlatformUserRepository
from app.repositories.tenant import ThemeRepository
from app.schemas.auth import MeResponse, SessionResponse
from app.schemas.common import Envelope, ok
from app.services.audit import AuditService
from app.services.navigation import build_navigation

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get(
    "/me",
    response_model=Envelope[MeResponse],
    summary="Bootstrap the client",
    description=(
        "Returns the principal, society context, subscription, theme and "
        "navigation in one call so the shell renders without a request waterfall."
    ),
)
async def me(
    context: ContextDep,
    manager: TenantManager,
) -> dict[str, Any]:
    principal = context.principal

    society_ctx = None
    subscription_ctx = None
    theme = None

    if context.society is not None:
        society_ctx = {
            "id": context.society.id,
            "name": context.society.name,
            "slug": context.society.slug,
            "status": context.society.status,
            "city": context.society.city,
            "state": context.society.state,
            "timezone": context.society.timezone,
            "total_flats": context.society.total_flats,
        }

    if context.subscription is not None:
        sub = context.subscription
        subscription_ctx = {
            "status": sub.status,
            "plan_name": sub.plan.name if sub.plan else None,
            "start_date": sub.start_date,
            "end_date": sub.end_date,
            "days_remaining": max((sub.end_date - date.today()).days, 0),
            "is_trial": sub.status.value == "TRIAL",
        }

    if principal.society_id is not None:
        async with manager.session(principal.society_id) as tenant:
            theme_row = await ThemeRepository(tenant).get()
            if theme_row is not None:
                theme = {
                    "theme_mode": theme_row.theme_mode.value,
                    "primary_color": theme_row.primary_color,
                    "secondary_color": theme_row.secondary_color,
                    "accent_color": theme_row.accent_color,
                    "sidebar_color": theme_row.sidebar_color,
                    "border_radius": theme_row.border_radius,
                    "logo_url": theme_row.logo_url,
                    "society_name": context.society.name if context.society else None,
                    "updated_at": theme_row.updated_at,
                }

    return ok(
        {
            "principal": {
                "id": principal.platform_user_id,
                "firebase_uid": principal.firebase_uid,
                "email": principal.email,
                "display_name": principal.display_name,
                "is_super_admin": principal.is_super_admin,
                "society_id": principal.society_id,
                "tenant_user_id": principal.tenant_user_id,
                "roles": sorted(r.value for r in principal.roles),
                "permissions": sorted(p.value for p in principal.permissions),
                "flat_ids": sorted(principal.flat_ids),
            },
            "society": society_ctx,
            "subscription": subscription_ctx,
            "theme": theme,
            "navigation": build_navigation(principal),
            "auth_provider": get_token_verifier().name,
            "server_time": datetime.now(timezone.utc),
        }
    )


@router.post(
    "/session",
    response_model=Envelope[SessionResponse],
    summary="Record a sign-in",
)
async def record_session(
    request: Request,
    principal: PrincipalDep,
    central: CentralSession,
    manager: TenantManager,
) -> dict[str, Any]:
    repo = PlatformUserRepository(central)
    await repo.touch_login(principal.platform_user_id)

    if principal.society_id is not None and principal.tenant_user_id is not None:
        from app.repositories.tenant import TenantUserRepository

        async with manager.session(principal.society_id) as tenant:
            await TenantUserRepository(tenant).touch_login(principal.tenant_user_id)

    await AuditService.platform(
        central,
        action=AuditAction.LOGIN_SUCCESS,
        principal=principal,
        society_id=principal.society_id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return ok({"recorded": True, "last_login_at": datetime.now(timezone.utc)})


@router.get(
    "/permissions",
    response_model=Envelope[list[str]],
    summary="Effective permissions",
)
async def permissions(principal: PrincipalDep) -> dict[str, Any]:
    return ok(sorted(p.value for p in principal.permissions))
