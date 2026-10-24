"""Who should be told.

Every notification in the product answers one of three questions: who lives in
this flat, who holds this permission, or who is this person. Answering them in
one place means a new notification never invents a fourth, subtly different,
definition of "the maintenance team".
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.models.tenant import (
    PermissionRow,
    Resident,
    RolePermission,
    RoleRow,
    TenantUser,
    UserRole,
)


class RecipientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def users_for_flat(self, flat_id: uuid.UUID | None) -> list[uuid.UUID]:
        """Active residents of one flat who have a login.

        A flat with no app user is normal — an elderly owner whose son handles
        the app — and produces an empty list rather than an error.
        """
        if flat_id is None:
            return []
        rows = await self.session.scalars(
            select(Resident.user_id)
            .join(TenantUser, TenantUser.id == Resident.user_id)
            .where(
                Resident.flat_id == flat_id,
                Resident.is_active.is_(True),
                Resident.user_id.is_not(None),
                TenantUser.is_active.is_(True),
            )
        )
        return list(dict.fromkeys(r for r in rows if r is not None))

    async def users_for_flats(self, flat_ids: Sequence[uuid.UUID]) -> list[uuid.UUID]:
        if not flat_ids:
            return []
        rows = await self.session.scalars(
            select(Resident.user_id)
            .join(TenantUser, TenantUser.id == Resident.user_id)
            .where(
                Resident.flat_id.in_(list(flat_ids)),
                Resident.is_active.is_(True),
                Resident.user_id.is_not(None),
                TenantUser.is_active.is_(True),
            )
        )
        return list(dict.fromkeys(r for r in rows if r is not None))

    async def users_with_permission(
        self, permission: Permission, *, limit: int = 200
    ) -> list[uuid.UUID]:
        """Everyone whose roles grant ``permission``.

        Read from the tenant tables rather than from ``ROLE_PERMISSIONS``,
        exactly as the authorization guard does — so a society with a custom
        role gets its custom role notified, and a society that has not been
        through ``sync-rbac`` is not told about a grant it does not have.
        """
        rows = await self.session.scalars(
            select(UserRole.user_id)
            .join(RoleRow, RoleRow.id == UserRole.role_id)
            .join(RolePermission, RolePermission.role_id == RoleRow.id)
            .join(PermissionRow, PermissionRow.id == RolePermission.permission_id)
            .join(TenantUser, TenantUser.id == UserRole.user_id)
            .where(
                PermissionRow.code == permission.value,
                TenantUser.is_active.is_(True),
            )
            .limit(limit * 4)
        )
        return list(dict.fromkeys(rows))[:limit]

    async def display_name(self, user_id: uuid.UUID | None) -> str | None:
        if user_id is None:
            return None
        return await self.session.scalar(
            select(TenantUser.full_name).where(TenantUser.id == user_id)
        )

    async def display_names(
        self, user_ids: Sequence[uuid.UUID | None]
    ) -> dict[uuid.UUID, str]:
        """Names for a page of rows, in one query rather than one per row."""
        wanted = [u for u in dict.fromkeys(user_ids) if u is not None]
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(TenantUser.id, TenantUser.full_name).where(TenantUser.id.in_(wanted))
        )
        return {uid: name for uid, name in rows}

    async def is_active_user(self, user_id: uuid.UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(TenantUser.id).where(
                    TenantUser.id == user_id, TenantUser.is_active.is_(True)
                )
            )
        )
