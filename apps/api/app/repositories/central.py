"""Central database repositories.

All SQL for ``nestflow_platform`` lives here. Repositories never decide
*whether* something is allowed — that is the service layer's job.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timezone

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.central import (
    DatabaseRegistry,
    PlatformAuditLog,
    PlatformUser,
    Society,
    SocietyAdminAssignment,
    SocietyStatus,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.models.central.registry import society_db_seq


async def _count(session: AsyncSession, stmt: Select) -> int:
    subq = stmt.order_by(None).subquery()
    return int(await session.scalar(select(func.count()).select_from(subq)) or 0)


class PlatformUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_firebase_uid(self, firebase_uid: str) -> PlatformUser | None:
        return await self.session.scalar(
            select(PlatformUser).where(PlatformUser.firebase_uid == firebase_uid)
        )

    async def get_by_id(self, user_id: uuid.UUID) -> PlatformUser | None:
        return await self.session.get(PlatformUser, user_id)

    async def get_by_email_in_society(
        self, email: str, society_id: uuid.UUID | None
    ) -> PlatformUser | None:
        stmt = select(PlatformUser).where(func.lower(PlatformUser.email) == email.lower())
        stmt = (
            stmt.where(PlatformUser.society_id == society_id)
            if society_id is not None
            else stmt.where(PlatformUser.is_super_admin.is_(True))
        )
        return await self.session.scalar(stmt)

    async def create(self, user: PlatformUser) -> PlatformUser:
        self.session.add(user)
        await self.session.flush()
        return user

    async def list_by_society(
        self, society_id: uuid.UUID, *, page: int = 1, limit: int = 25
    ) -> tuple[Sequence[PlatformUser], int]:
        stmt = select(PlatformUser).where(PlatformUser.society_id == society_id)
        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(PlatformUser.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total

    async def list_all(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        society_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[PlatformUser], int]:
        stmt = select(PlatformUser)
        if q:
            pattern = f"%{q.lower()}%"
            stmt = stmt.where(
                func.lower(PlatformUser.email).like(pattern)
                | func.lower(PlatformUser.display_name).like(pattern)
            )
        if society_id is not None:
            stmt = stmt.where(PlatformUser.society_id == society_id)
        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(PlatformUser.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total

    async def count_in_society(self, society_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(PlatformUser)
                .where(PlatformUser.society_id == society_id)
            )
            or 0
        )

    async def touch_login(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(PlatformUser)
            .where(PlatformUser.id == user_id)
            .values(last_login_at=datetime.now(timezone.utc))
        )


class SocietyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, society_id: uuid.UUID) -> Society | None:
        return await self.session.get(Society, society_id)

    async def get_by_slug(self, slug: str) -> Society | None:
        return await self.session.scalar(select(Society).where(Society.slug == slug))

    async def slug_exists(self, slug: str) -> bool:
        return (
            await self.session.scalar(
                select(func.count()).select_from(Society).where(Society.slug == slug)
            )
        ) > 0

    async def create(self, society: Society) -> Society:
        self.session.add(society)
        await self.session.flush()
        return society

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        status: SocietyStatus | None = None,
        include_archived: bool = False,
    ) -> tuple[Sequence[Society], int]:
        stmt = select(Society)
        if not include_archived:
            stmt = stmt.where(Society.status != SocietyStatus.ARCHIVED)
        if status is not None:
            stmt = stmt.where(Society.status == status)
        if q:
            pattern = f"%{q.lower()}%"
            stmt = stmt.where(
                func.lower(Society.name).like(pattern)
                | func.lower(Society.city).like(pattern)
                | Society.slug.like(pattern)
            )
        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(Society.created_at.desc()).offset((page - 1) * limit).limit(limit)
        )
        return list(rows), total

    async def counts_by_status(self) -> dict[str, int]:
        rows = await self.session.execute(
            select(Society.status, func.count()).group_by(Society.status)
        )
        return {str(status): int(count) for status, count in rows}


class DatabaseRegistryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_society(self, society_id: uuid.UUID) -> DatabaseRegistry | None:
        return await self.session.scalar(
            select(DatabaseRegistry).where(DatabaseRegistry.society_id == society_id)
        )

    async def next_sequence_number(self) -> int:
        """Allocate the numeric suffix for a new tenant database name."""
        return int(await self.session.scalar(society_db_seq.next_value()))  # type: ignore[arg-type]

    async def create(self, registry: DatabaseRegistry) -> DatabaseRegistry:
        self.session.add(registry)
        await self.session.flush()
        return registry

    async def list_all(self) -> Sequence[DatabaseRegistry]:
        rows = await self.session.scalars(
            select(DatabaseRegistry).order_by(DatabaseRegistry.sequence_number)
        )
        return list(rows)


class SubscriptionPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, plan_id: uuid.UUID) -> SubscriptionPlan | None:
        return await self.session.get(SubscriptionPlan, plan_id)

    async def get_by_code(self, code: str) -> SubscriptionPlan | None:
        return await self.session.scalar(
            select(SubscriptionPlan).where(SubscriptionPlan.code == code)
        )

    async def create(self, plan: SubscriptionPlan) -> SubscriptionPlan:
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def list(self, *, active_only: bool = False) -> Sequence[SubscriptionPlan]:
        stmt = select(SubscriptionPlan)
        if active_only:
            stmt = stmt.where(SubscriptionPlan.is_active.is_(True))
        rows = await self.session.scalars(
            stmt.order_by(SubscriptionPlan.sort_order, SubscriptionPlan.price)
        )
        return list(rows)


class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_current(self, society_id: uuid.UUID) -> Subscription | None:
        return await self.session.scalar(
            select(Subscription).where(
                Subscription.society_id == society_id,
                Subscription.is_current.is_(True),
            )
        )

    async def get_by_id(self, subscription_id: uuid.UUID) -> Subscription | None:
        return await self.session.get(Subscription, subscription_id)

    async def create(self, subscription: Subscription) -> Subscription:
        self.session.add(subscription)
        await self.session.flush()
        return subscription

    async def clear_current(self, society_id: uuid.UUID) -> None:
        """Demote the existing current subscription before inserting a new one.

        Required by ``ux_subscriptions_current``; keeps the superseded row for
        history rather than overwriting it.
        """
        await self.session.execute(
            update(Subscription)
            .where(
                Subscription.society_id == society_id,
                Subscription.is_current.is_(True),
            )
            .values(is_current=False)
        )

    async def list_by_society(self, society_id: uuid.UUID) -> Sequence[Subscription]:
        rows = await self.session.scalars(
            select(Subscription)
            .where(Subscription.society_id == society_id)
            .order_by(Subscription.created_at.desc())
        )
        return list(rows)

    async def count_active(self, on: date | None = None) -> int:
        on = on or date.today()
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(Subscription)
                .where(
                    Subscription.is_current.is_(True),
                    Subscription.status.in_(
                        [SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE]
                    ),
                    Subscription.end_date >= on,
                )
            )
            or 0
        )

    async def list_expiring(self, before: date) -> Sequence[Subscription]:
        rows = await self.session.scalars(
            select(Subscription).where(
                Subscription.is_current.is_(True),
                Subscription.status.in_([SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE]),
                Subscription.end_date < before,
            )
        )
        return list(rows)


class SocietyAdminAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, assignment: SocietyAdminAssignment) -> SocietyAdminAssignment:
        self.session.add(assignment)
        await self.session.flush()
        return assignment

    async def list_active(self, society_id: uuid.UUID) -> Sequence[SocietyAdminAssignment]:
        rows = await self.session.scalars(
            select(SocietyAdminAssignment).where(
                SocietyAdminAssignment.society_id == society_id,
                SocietyAdminAssignment.is_active.is_(True),
            )
        )
        return list(rows)


class PlatformAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(self, entry: PlatformAuditLog) -> None:
        self.session.add(entry)

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        society_id: uuid.UUID | None = None,
        action: str | None = None,
    ) -> tuple[Sequence[PlatformAuditLog], int]:
        stmt = select(PlatformAuditLog)
        if society_id is not None:
            stmt = stmt.where(PlatformAuditLog.society_id == society_id)
        if action:
            stmt = stmt.where(PlatformAuditLog.action == action)
        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(PlatformAuditLog.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total
