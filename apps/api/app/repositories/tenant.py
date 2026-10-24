"""Tenant database repositories.

Note the absence of any ``society_id`` filter: the session is already bound to
exactly one society's database, so scoping is structural rather than a
``WHERE`` clause someone can forget.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tenant import (
    Notification,
    PermissionRow,
    RolePermission,
    RoleRow,
    SocietySettings,
    TenantAuditLog,
    TenantUser,
    ThemeSettings,
    UserRole,
)


async def _count(session: AsyncSession, stmt: Select) -> int:
    subq = stmt.order_by(None).subquery()
    return int(await session.scalar(select(func.count()).select_from(subq)) or 0)


class TenantUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_firebase_uid(self, firebase_uid: str) -> TenantUser | None:
        return await self.session.scalar(
            select(TenantUser)
            .where(TenantUser.firebase_uid == firebase_uid)
            .options(
                selectinload(TenantUser.user_roles)
                .selectinload(UserRole.role)
                .selectinload(RoleRow.role_permissions)
                .selectinload(RolePermission.permission)
            )
        )

    async def get_by_id(self, user_id: uuid.UUID) -> TenantUser | None:
        return await self.session.get(TenantUser, user_id)

    async def get_with_authorization(self, user_id: uuid.UUID) -> TenantUser | None:
        """Load a user with roles and permissions eagerly, for principal build."""
        return await self.session.scalar(
            select(TenantUser)
            .where(TenantUser.id == user_id)
            .options(
                selectinload(TenantUser.user_roles)
                .selectinload(UserRole.role)
                .selectinload(RoleRow.role_permissions)
                .selectinload(RolePermission.permission)
            )
        )

    async def get_by_email(self, email: str) -> TenantUser | None:
        return await self.session.scalar(
            select(TenantUser).where(func.lower(TenantUser.email) == email.lower())
        )

    async def create(self, user: TenantUser) -> TenantUser:
        self.session.add(user)
        await self.session.flush()
        return user

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        role_code: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[Sequence[TenantUser], int]:
        stmt = select(TenantUser)
        if q:
            pattern = f"%{q.lower()}%"
            stmt = stmt.where(
                func.lower(TenantUser.full_name).like(pattern)
                | func.lower(TenantUser.email).like(pattern)
            )
        if is_active is not None:
            stmt = stmt.where(TenantUser.is_active.is_(is_active))
        if role_code:
            stmt = stmt.where(
                TenantUser.id.in_(
                    select(UserRole.user_id)
                    .join(RoleRow, RoleRow.id == UserRole.role_id)
                    .where(RoleRow.code == role_code)
                )
            )
        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(TenantUser.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .options(selectinload(TenantUser.user_roles).selectinload(UserRole.role))
        )
        return list(rows), total

    async def count(self) -> int:
        return int(await self.session.scalar(select(func.count()).select_from(TenantUser)) or 0)

    async def touch_login(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(TenantUser)
            .where(TenantUser.id == user_id)
            .values(last_login_at=datetime.now(timezone.utc))
        )


class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_code(self, code: str) -> RoleRow | None:
        return await self.session.scalar(select(RoleRow).where(RoleRow.code == code))

    async def list(self) -> Sequence[RoleRow]:
        rows = await self.session.scalars(select(RoleRow).order_by(RoleRow.code))
        return list(rows)

    async def list_with_permissions(self) -> Sequence[RoleRow]:
        rows = await self.session.scalars(
            select(RoleRow)
            .order_by(RoleRow.code)
            .options(
                selectinload(RoleRow.role_permissions).selectinload(RolePermission.permission)
            )
        )
        return list(rows)

    async def assign(
        self, user_id: uuid.UUID, role_ids: Sequence[uuid.UUID], assigned_by: uuid.UUID | None
    ) -> None:
        """Replace a user's roles wholesale.

        Delete-then-insert rather than a diff: the set is tiny, and it keeps the
        result independent of the prior state.
        """
        await self.session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        for role_id in role_ids:
            self.session.add(
                UserRole(user_id=user_id, role_id=role_id, assigned_by=assigned_by)
            )
        await self.session.flush()

    async def permission_codes_for_user(self, user_id: uuid.UUID) -> set[str]:
        rows = await self.session.scalars(
            select(PermissionRow.code)
            .join(RolePermission, RolePermission.permission_id == PermissionRow.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        return set(rows)


class PermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> Sequence[PermissionRow]:
        rows = await self.session.scalars(select(PermissionRow).order_by(PermissionRow.code))
        return list(rows)

    async def get_by_code(self, code: str) -> PermissionRow | None:
        return await self.session.scalar(
            select(PermissionRow).where(PermissionRow.code == code)
        )


class SocietySettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> SocietySettings | None:
        return await self.session.get(SocietySettings, 1)

    async def upsert(self, **values: object) -> SocietySettings:
        settings = await self.get()
        if settings is None:
            settings = SocietySettings(id=1, **values)  # type: ignore[arg-type]
            self.session.add(settings)
        else:
            for key, value in values.items():
                setattr(settings, key, value)
        await self.session.flush()
        # updated_at uses a server-side onupdate, so it is expired by the flush.
        # Refresh while the session is alive — the response is serialised after
        # the request dependency has already closed it.
        await self.session.refresh(settings)
        return settings


class ThemeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> ThemeSettings | None:
        return await self.session.get(ThemeSettings, 1)

    async def upsert(self, **values: object) -> ThemeSettings:
        theme = await self.get()
        if theme is None:
            theme = ThemeSettings(id=1, **values)  # type: ignore[arg-type]
            self.session.add(theme)
        else:
            for key, value in values.items():
                setattr(theme, key, value)
        await self.session.flush()
        # See SocietySettingsRepository.upsert: server-side onupdate expires
        # updated_at at flush time.
        await self.session.refresh(theme)
        return theme


class TenantAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(self, entry: TenantAuditLog) -> None:
        self.session.add(entry)

    async def list(
        self, *, page: int = 1, limit: int = 25, action: str | None = None
    ) -> tuple[Sequence[TenantAuditLog], int]:
        stmt = select(TenantAuditLog)
        if action:
            stmt = stmt.where(TenantAuditLog.action == action)
        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(TenantAuditLog.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, notification: Notification) -> Notification:
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def list_for_user(
        self, user_id: uuid.UUID, *, page: int = 1, limit: int = 25, unread_only: bool = False
    ) -> tuple[Sequence[Notification], int]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(Notification.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total

    async def unread_count(self, user_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            )
            or 0
        )

    async def mark_read(self, user_id: uuid.UUID, notification_ids: Sequence[uuid.UUID]) -> int:
        result = await self.session.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.id.in_(notification_ids),
                Notification.is_read.is_(False),
            )
            .values(is_read=True, read_at=datetime.now(timezone.utc))
        )
        return int(result.rowcount or 0)
