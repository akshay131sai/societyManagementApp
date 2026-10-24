"""Society-scoped (tenant) services: settings, theme, users, notifications.

Every method takes a tenant ``AsyncSession`` that is already bound to the
caller's own database — there is no society parameter to get wrong.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AlreadyExistsError, ConflictError, NotFoundError, ValidationError
from app.core.permissions import Role
from app.models.central.audit import AuditAction
from app.models.tenant import RoleRow, TenantUser, UserRole
from app.models.tenant.settings import DEFAULT_THEME, SocietySettings, ThemeSettings
from app.repositories.tenant import (
    NotificationRepository,
    PermissionRepository,
    RoleRepository,
    SocietySettingsRepository,
    TenantUserRepository,
    ThemeRepository,
)
from app.schemas.society import (
    SocietySettingsUpdate,
    TenantUserCreate,
    TenantUserUpdate,
)
from app.schemas.theme import ThemeUpdate
from app.services.audit import AuditService, diff

log = structlog.get_logger(__name__)


class ThemeService:
    """Per-society appearance.

    Isolation is structural: the write targets the caller's tenant session, so
    there is no code path that could reach another society's theme row.
    """

    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = ThemeRepository(tenant)

    async def get(self) -> ThemeSettings:
        theme = await self.repo.get()
        if theme is None:
            theme = await self.repo.upsert(**DEFAULT_THEME)
        return theme

    async def update(
        self, payload: ThemeUpdate, principal: Principal, *, request_id: str | None = None
    ) -> ThemeSettings:
        theme = await self.get()
        before = _snapshot(theme)

        values = payload.model_dump(exclude_unset=True, exclude_none=True)
        if not values:
            raise ValidationError("No theme changes were supplied.")
        values["updated_by"] = principal.tenant_user_id
        theme = await self.repo.upsert(**values)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.THEME_UPDATED,
            principal=principal,
            target_type="theme_settings",
            target_id=1,
            changes=diff(before, _snapshot(theme)),
            request_id=request_id,
        )
        log.info("theme.updated", society_id=str(principal.society_id), fields=list(values))
        return theme

    async def reset(
        self, principal: Principal, *, request_id: str | None = None
    ) -> ThemeSettings:
        before = _snapshot(await self.get())
        theme = await self.repo.upsert(**DEFAULT_THEME, updated_by=principal.tenant_user_id)
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.THEME_UPDATED,
            principal=principal,
            target_type="theme_settings",
            target_id=1,
            changes=diff(before, _snapshot(theme)),
            request_id=request_id,
        )
        return theme


class SocietySettingsService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = SocietySettingsRepository(tenant)

    async def get(self) -> SocietySettings:
        settings = await self.repo.get()
        if settings is None:
            raise NotFoundError("Society settings")
        return settings

    async def update(
        self,
        payload: SocietySettingsUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> SocietySettings:
        settings = await self.get()
        before = _snapshot(settings)

        values = payload.model_dump(exclude_unset=True, exclude_none=True)
        if "contact_email" in values:
            values["contact_email"] = str(values["contact_email"])
        for field, value in values.items():
            setattr(settings, field, value)
        await self.tenant.flush()
        await self.tenant.refresh(settings)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.SETTINGS_UPDATED,
            principal=principal,
            target_type="society_settings",
            target_id=1,
            changes=diff(before, _snapshot(settings)),
            request_id=request_id,
        )
        return settings


class TenantUserService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.users = TenantUserRepository(tenant)
        self.roles = RoleRepository(tenant)

    async def list(
        self,
        *,
        page: int,
        limit: int,
        q: str | None = None,
        role_code: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.users.list(
            page=page, limit=limit, q=q, role_code=role_code, is_active=is_active
        )
        return [_user_dict(u) for u in rows], total

    async def get(self, user_id: uuid.UUID) -> dict[str, Any]:
        from sqlalchemy.orm import selectinload

        user = await self.tenant.scalar(
            select(TenantUser)
            .where(TenantUser.id == user_id)
            .options(selectinload(TenantUser.user_roles).selectinload(UserRole.role))
        )
        if user is None:
            raise NotFoundError("User")
        return _user_dict(user)

    async def create(
        self, payload: TenantUserCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        """Create a society user.

        The tenant row is created here; the matching central ``platform_users``
        row is created by the caller (the router), because it lives in a
        different database and therefore a different session.
        """
        if await self.users.get_by_email(str(payload.email)):
            raise AlreadyExistsError(
                f"A user with the email {payload.email} already exists in this society."
            )

        role_rows = await self._resolve_roles(payload.role_codes)

        user = TenantUser(
            firebase_uid=payload.firebase_uid or f"pending:{str(payload.email).lower()}",
            email=str(payload.email).lower(),
            phone=payload.phone,
            full_name=payload.full_name,
            is_active=True,
        )
        await self.users.create(user)
        await self.roles.assign(
            user.id, [r.id for r in role_rows], principal.tenant_user_id
        )

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.USER_CREATED,
            principal=principal,
            target_type="user",
            target_id=user.id,
            changes={"after": {"email": user.email, "roles": payload.role_codes}},
            request_id=request_id,
        )
        return await self.get(user.id)

    async def update(
        self,
        user_id: uuid.UUID,
        payload: TenantUserUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User")

        before = _snapshot(user)
        values = payload.model_dump(exclude_unset=True, exclude_none=True)

        if values.get("is_active") is False and user.id == principal.tenant_user_id:
            raise ConflictError("You cannot deactivate your own account.")

        for field, value in values.items():
            setattr(user, field, value)
        await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.USER_UPDATED,
            principal=principal,
            target_type="user",
            target_id=user.id,
            changes=diff(before, _snapshot(user)),
            request_id=request_id,
        )
        return await self.get(user.id)

    async def set_roles(
        self,
        user_id: uuid.UUID,
        role_codes: list[str],
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User")

        role_rows = await self._resolve_roles(role_codes)

        # Guard against the society locking itself out of its own admin role.
        if user.id == principal.tenant_user_id and Role.SOCIETY_ADMIN.value not in role_codes:
            if await self._count_other_admins(user.id) == 0:
                raise ConflictError(
                    "You are the only Society Admin. Assign the role to another user "
                    "before removing it from yourself."
                )

        current = await self.get(user_id)
        await self.roles.assign(user.id, [r.id for r in role_rows], principal.tenant_user_id)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.ROLE_CHANGED,
            principal=principal,
            target_type="user",
            target_id=user.id,
            changes={"before": {"roles": current["roles"]}, "after": {"roles": role_codes}},
            request_id=request_id,
        )
        return await self.get(user_id)

    async def deactivate(
        self, user_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User")
        if user.id == principal.tenant_user_id:
            raise ConflictError("You cannot deactivate your own account.")

        user.is_active = False
        await self.tenant.flush()
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.USER_DISABLED,
            principal=principal,
            target_type="user",
            target_id=user.id,
            request_id=request_id,
        )

    async def _resolve_roles(self, codes: list[str]) -> list[RoleRow]:
        # Checked first so a privilege-escalation attempt reports the real
        # reason rather than the generic "unknown role" (SUPER_ADMIN is
        # deliberately absent from every tenant database).
        if Role.SUPER_ADMIN.value in codes:
            raise ValidationError(
                "SUPER_ADMIN is a platform role and cannot be assigned within a society."
            )
        rows = list(await self.tenant.scalars(select(RoleRow).where(RoleRow.code.in_(codes))))
        found = {r.code for r in rows}
        if missing := set(codes) - found:
            raise ValidationError(f"Unknown role(s): {', '.join(sorted(missing))}")
        return rows

    async def _count_other_admins(self, exclude_user_id: uuid.UUID) -> int:
        return int(
            await self.tenant.scalar(
                select(func.count())
                .select_from(UserRole)
                .join(RoleRow, RoleRow.id == UserRole.role_id)
                .join(TenantUser, TenantUser.id == UserRole.user_id)
                .where(
                    RoleRow.code == Role.SOCIETY_ADMIN.value,
                    UserRole.user_id != exclude_user_id,
                    TenantUser.is_active.is_(True),
                )
            )
            or 0
        )


class RoleService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.roles = RoleRepository(tenant)
        self.permissions = PermissionRepository(tenant)

    async def list_with_permissions(self) -> list[dict[str, Any]]:
        rows = await self.roles.list_with_permissions()
        return [
            {
                "id": r.id,
                "code": r.code,
                "name": r.name,
                "description": r.description,
                "is_system": r.is_system,
                "permissions": sorted(rp.permission.code for rp in r.role_permissions),
            }
            for r in rows
        ]


class SocietyDashboardService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant

    async def build(self, principal: Principal) -> dict[str, Any]:
        settings = await SocietySettingsRepository(self.tenant).get()
        total_users = int(
            await self.tenant.scalar(select(func.count()).select_from(TenantUser)) or 0
        )
        active_users = int(
            await self.tenant.scalar(
                select(func.count())
                .select_from(TenantUser)
                .where(TenantUser.is_active.is_(True))
            )
            or 0
        )
        role_rows = await self.tenant.execute(
            select(RoleRow.code, func.count(UserRole.user_id))
            .join(UserRole, UserRole.role_id == RoleRow.id, isouter=True)
            .group_by(RoleRow.code)
        )
        unread = 0
        if principal.tenant_user_id is not None:
            unread = await NotificationRepository(self.tenant).unread_count(
                principal.tenant_user_id
            )

        from app.repositories.structure import (
            BuildingRepository,
            FlatRepository,
            ResidentRepository,
        )

        return {
            "society_name": settings.society_name if settings else "",
            "total_users": total_users,
            "active_users": active_users,
            "total_flats": await FlatRepository(self.tenant).count(),
            "total_buildings": len(await BuildingRepository(self.tenant).list()),
            "total_residents": await ResidentRepository(self.tenant).count(),
            "occupancy": await FlatRepository(self.tenant).counts_by_occupancy(),
            "unread_notifications": unread,
            "roles_summary": {code: int(count) for code, count in role_rows},
        }


# --------------------------------------------------------------------------- #


def _user_dict(user: TenantUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "avatar_url": user.avatar_url,
        "is_active": user.is_active,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
        "roles": sorted(ur.role.code for ur in user.user_roles),
    }


def _snapshot(obj: Any) -> dict[str, Any]:
    from datetime import date, datetime

    from sqlalchemy import inspect

    def plain(value: Any) -> Any:
        if isinstance(value, (uuid.UUID, date, datetime)):
            return str(value)
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, (int, float, str, bool, type(None), dict, list)):
            return value
        return str(value)

    return {
        c.key: plain(getattr(obj, c.key))
        for c in inspect(obj).mapper.column_attrs
        if c.key not in {"created_at", "updated_at"}
    }
