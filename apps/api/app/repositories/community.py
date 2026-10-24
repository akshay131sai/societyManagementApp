"""Notice and amenity-booking repositories."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, false, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import (
    ACTIVE_BOOKING_STATUSES,
    Amenity,
    AmenityBooking,
    AudienceScope,
    BookingStatus,
    Notice,
    NoticeRead,
)


async def _count(session: AsyncSession, stmt: Select) -> int:
    subq = stmt.order_by(None).subquery()
    return int(await session.scalar(select(func.count()).select_from(subq)) or 0)


# --------------------------------------------------------------------------- #
# Notices
# --------------------------------------------------------------------------- #


class NoticeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, notice_id: uuid.UUID) -> Notice | None:
        return await self.session.get(Notice, notice_id)

    def _visible_now(self) -> Any:
        """Published, past its publish time, not yet expired.

        Built once and reused by the list query and the unread count, so a
        resident's badge can never disagree with their list.
        """
        return and_(
            Notice.is_published.is_(True),
            or_(Notice.publish_at.is_(None), Notice.publish_at <= func.now()),
            or_(Notice.expires_at.is_(None), Notice.expires_at > func.now()),
        )

    def _audience_filter(
        self,
        *,
        building_ids: Sequence[uuid.UUID],
        block_ids: Sequence[uuid.UUID],
        is_owner: bool,
        is_tenant: bool,
        is_staff: bool,
    ) -> Any:
        """Whether a notice is addressed to this reader.

        The clauses are additive: a notice reaches someone if *any* of them
        matches. An owner in Tower A therefore sees society-wide notices, Tower
        A notices, their own block's notices and owner-only notices, and never
        the staff roster change.
        """
        clauses = [Notice.audience == AudienceScope.ALL]
        if building_ids:
            clauses.append(
                and_(
                    Notice.audience == AudienceScope.BUILDING,
                    Notice.building_id.in_(list(building_ids)),
                )
            )
        if block_ids:
            clauses.append(
                and_(
                    Notice.audience == AudienceScope.BLOCK,
                    Notice.block_id.in_(list(block_ids)),
                )
            )
        if is_owner:
            clauses.append(Notice.audience == AudienceScope.OWNERS)
        if is_tenant:
            clauses.append(Notice.audience == AudienceScope.TENANTS)
        if is_staff:
            clauses.append(Notice.audience == AudienceScope.STAFF)
        return or_(*clauses)

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        category: str | None = None,
        pinned_first: bool = True,
        include_unpublished: bool = False,
        audience: Any | None = None,
    ) -> tuple[Sequence[Notice], int]:
        stmt = select(Notice)
        if not include_unpublished:
            stmt = stmt.where(self._visible_now())
        if audience is not None:
            stmt = stmt.where(audience)
        if q:
            needle = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Notice.title).like(needle),
                    func.lower(Notice.body).like(needle),
                )
            )
        if category:
            stmt = stmt.where(Notice.category == category)

        total = await _count(self.session, stmt)
        order = [Notice.is_pinned.desc()] if pinned_first else []
        order += [
            func.coalesce(Notice.publish_at, Notice.created_at).desc(),
        ]
        rows = await self.session.scalars(
            stmt.order_by(*order).offset((page - 1) * limit).limit(limit)
        )
        return list(rows), total

    async def create(self, notice: Notice) -> Notice:
        self.session.add(notice)
        await self.session.flush()
        return notice

    async def mark_read(self, notice_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Idempotent. Returns whether this call was the first read.

        ``ON CONFLICT DO NOTHING`` rather than a SELECT-then-INSERT: a resident
        on a train tunnel connection taps twice, and the read count a committee
        looks at has to stay honest.
        """
        result = await self.session.execute(
            pg_insert(NoticeRead)
            .values(notice_id=notice_id, user_id=user_id)
            .on_conflict_do_nothing(index_elements=["notice_id", "user_id"])
        )
        return bool(result.rowcount)

    async def read_ids_for(
        self, user_id: uuid.UUID, notice_ids: Sequence[uuid.UUID]
    ) -> set[uuid.UUID]:
        if not notice_ids:
            return set()
        rows = await self.session.scalars(
            select(NoticeRead.notice_id).where(
                NoticeRead.user_id == user_id,
                NoticeRead.notice_id.in_(list(notice_ids)),
            )
        )
        return set(rows)

    async def read_counts(self, notice_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not notice_ids:
            return {}
        rows = await self.session.execute(
            select(NoticeRead.notice_id, func.count())
            .where(NoticeRead.notice_id.in_(list(notice_ids)))
            .group_by(NoticeRead.notice_id)
        )
        return {nid: int(n) for nid, n in rows}

    async def unread_count(self, user_id: uuid.UUID, audience: Any | None = None) -> int:
        read = select(NoticeRead.notice_id).where(NoticeRead.user_id == user_id)
        stmt = select(func.count()).select_from(Notice).where(
            self._visible_now(), Notice.id.not_in(read)
        )
        if audience is not None:
            stmt = stmt.where(audience)
        return int(await self.session.scalar(stmt) or 0)

    async def summary(self, user_id: uuid.UUID | None) -> dict[str, int]:
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.count().filter(self._visible_now()),
                    func.count().filter(
                        and_(
                            Notice.is_published.is_(True),
                            Notice.publish_at.is_not(None),
                            Notice.publish_at > func.now(),
                        )
                    ),
                    func.count().filter(
                        and_(
                            Notice.expires_at.is_not(None),
                            Notice.expires_at <= func.now(),
                        )
                    ),
                ).select_from(Notice)
            )
        ).first()
        total, published, scheduled, expired = row or (0, 0, 0, 0)
        unread = await self.unread_count(user_id) if user_id else 0
        return {
            "total": int(total or 0),
            "published": int(published or 0),
            "scheduled": int(scheduled or 0),
            "expired": int(expired or 0),
            "unread": unread,
        }

    async def due_for_publication(self, limit: int = 200) -> Sequence[Notice]:
        """Scheduled notices whose moment has come. The worker's input."""
        rows = await self.session.scalars(
            select(Notice)
            .where(
                Notice.is_published.is_(False),
                Notice.publish_at.is_not(None),
                Notice.publish_at <= func.now(),
            )
            .limit(limit)
        )
        return list(rows)


# --------------------------------------------------------------------------- #
# Amenities
# --------------------------------------------------------------------------- #


class AmenityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, amenity_id: uuid.UUID) -> Amenity | None:
        return await self.session.get(Amenity, amenity_id)

    async def get_by_name(self, name: str) -> Amenity | None:
        return await self.session.scalar(
            select(Amenity).where(func.lower(Amenity.name) == name.lower())
        )

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        q: str | None = None,
        active_only: bool = True,
    ) -> tuple[Sequence[Amenity], int]:
        stmt = select(Amenity)
        if active_only:
            stmt = stmt.where(Amenity.is_active.is_(True))
        if q:
            stmt = stmt.where(func.lower(Amenity.name).like(f"%{q.lower()}%"))

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(Amenity.name).offset((page - 1) * limit).limit(limit)
        )
        return list(rows), total

    async def create(self, amenity: Amenity) -> Amenity:
        self.session.add(amenity)
        await self.session.flush()
        return amenity

    async def upcoming_counts(
        self, amenity_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        if not amenity_ids:
            return {}
        rows = await self.session.execute(
            select(AmenityBooking.amenity_id, func.count())
            .where(
                AmenityBooking.amenity_id.in_(list(amenity_ids)),
                AmenityBooking.status.in_(list(ACTIVE_BOOKING_STATUSES)),
                AmenityBooking.starts_at >= func.now(),
            )
            .group_by(AmenityBooking.amenity_id)
        )
        return {aid: int(n) for aid, n in rows}

    async def count_active(self) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).select_from(Amenity).where(Amenity.is_active.is_(True))
            )
            or 0
        )


class BookingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, booking_id: uuid.UUID) -> AmenityBooking | None:
        return await self.session.get(AmenityBooking, booking_id)

    async def list(
        self,
        *,
        page: int = 1,
        limit: int = 25,
        amenity_id: uuid.UUID | None = None,
        flat_id: uuid.UUID | None = None,
        status: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        upcoming_only: bool = False,
        pending_only: bool = False,
        only_flat_ids: Sequence[uuid.UUID] | None = None,
    ) -> tuple[Sequence[AmenityBooking], int]:
        stmt = select(AmenityBooking)
        if amenity_id is not None:
            stmt = stmt.where(AmenityBooking.amenity_id == amenity_id)
        if flat_id is not None:
            stmt = stmt.where(AmenityBooking.flat_id == flat_id)
        if status:
            stmt = stmt.where(AmenityBooking.status == status)
        if from_date:
            stmt = stmt.where(AmenityBooking.booking_date >= from_date)
        if to_date:
            stmt = stmt.where(AmenityBooking.booking_date <= to_date)
        if upcoming_only:
            stmt = stmt.where(
                AmenityBooking.starts_at >= func.now(),
                AmenityBooking.status.in_(list(ACTIVE_BOOKING_STATUSES)),
            )
        if pending_only:
            stmt = stmt.where(AmenityBooking.status == BookingStatus.PENDING)
        if only_flat_ids is not None:
            stmt = stmt.where(
                AmenityBooking.flat_id.in_(list(only_flat_ids))
                if only_flat_ids
                else false()
            )

        total = await _count(self.session, stmt)
        rows = await self.session.scalars(
            stmt.order_by(AmenityBooking.starts_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(rows), total

    async def create(self, booking: AmenityBooking) -> AmenityBooking:
        self.session.add(booking)
        await self.session.flush()
        return booking

    async def for_day(
        self, amenity_id: uuid.UUID, on: date
    ) -> Sequence[AmenityBooking]:
        """Everything that holds a slot on one day — the availability grid.

        Filtered on the same statuses as the exclusion constraint, so the grid
        and the database agree on what "taken" means.
        """
        rows = await self.session.scalars(
            select(AmenityBooking)
            .where(
                AmenityBooking.amenity_id == amenity_id,
                AmenityBooking.booking_date == on,
                AmenityBooking.status.in_(list(ACTIVE_BOOKING_STATUSES)),
            )
            .order_by(AmenityBooking.starts_at)
        )
        return list(rows)

    async def active_count_for_flat(self, amenity_id: uuid.UUID, flat_id: uuid.UUID) -> int:
        """Live future bookings one flat holds on one amenity."""
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(AmenityBooking)
                .where(
                    AmenityBooking.amenity_id == amenity_id,
                    AmenityBooking.flat_id == flat_id,
                    AmenityBooking.status.in_(list(ACTIVE_BOOKING_STATUSES)),
                    AmenityBooking.ends_at >= func.now(),
                )
            )
            or 0
        )

    async def summary(self, *, today: date, month_start: date) -> dict[str, Any]:
        row = (
            await self.session.execute(
                select(
                    func.count().filter(
                        and_(
                            AmenityBooking.booking_date == today,
                            AmenityBooking.status.in_(list(ACTIVE_BOOKING_STATUSES)),
                        )
                    ),
                    func.count().filter(
                        and_(
                            AmenityBooking.starts_at >= func.now(),
                            AmenityBooking.status.in_(list(ACTIVE_BOOKING_STATUSES)),
                        )
                    ),
                    func.count().filter(AmenityBooking.status == BookingStatus.PENDING),
                    func.coalesce(
                        func.sum(AmenityBooking.charge).filter(
                            and_(
                                AmenityBooking.booking_date >= month_start,
                                AmenityBooking.status.in_(
                                    [BookingStatus.CONFIRMED, BookingStatus.COMPLETED]
                                ),
                            )
                        ),
                        0,
                    ),
                ).select_from(AmenityBooking)
            )
        ).first()
        today_count, upcoming, pending, revenue = row or (0, 0, 0, 0)
        return {
            "bookings_today": int(today_count or 0),
            "upcoming": int(upcoming or 0),
            "pending_approval": int(pending or 0),
            "revenue_this_month": Decimal(str(revenue or 0)),
        }

    async def starting_between(
        self, start: datetime, end: datetime, limit: int = 500
    ) -> Sequence[AmenityBooking]:
        """Confirmed bookings starting in a window — the reminder job's input."""
        rows = await self.session.scalars(
            select(AmenityBooking)
            .where(
                AmenityBooking.status == BookingStatus.CONFIRMED,
                AmenityBooking.starts_at >= start,
                AmenityBooking.starts_at < end,
            )
            .limit(limit)
        )
        return list(rows)

    async def past_confirmed(self, cutoff: datetime, limit: int = 500) -> Sequence[AmenityBooking]:
        """Bookings whose window has closed but still read as CONFIRMED."""
        rows = await self.session.scalars(
            select(AmenityBooking)
            .where(
                AmenityBooking.status == BookingStatus.CONFIRMED,
                AmenityBooking.ends_at < cutoff,
            )
            .limit(limit)
        )
        return list(rows)


class NoticeAudienceRepository:
    """Who a notice has to reach, in flats and users.

    Lives here rather than in the notice repository because the fan-out reads
    ``residents`` and ``users``, and a notice is not the owner of those tables.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def recipient_user_ids(
        self,
        *,
        audience: AudienceScope,
        building_id: uuid.UUID | None,
        block_id: uuid.UUID | None,
    ) -> list[uuid.UUID]:
        from app.models.tenant import Flat, Resident, ResidentType, TenantUser

        stmt = (
            select(Resident.user_id)
            .join(Flat, Flat.id == Resident.flat_id)
            .join(TenantUser, TenantUser.id == Resident.user_id)
            .where(
                Resident.user_id.is_not(None),
                Resident.is_active.is_(True),
                TenantUser.is_active.is_(True),
            )
        )

        if audience is AudienceScope.BUILDING and building_id is not None:
            stmt = stmt.where(Flat.building_id == building_id)
        elif audience is AudienceScope.BLOCK and block_id is not None:
            stmt = stmt.where(Flat.block_id == block_id)
        elif audience is AudienceScope.OWNERS:
            stmt = stmt.where(Resident.resident_type == ResidentType.OWNER)
        elif audience is AudienceScope.TENANTS:
            stmt = stmt.where(Resident.resident_type == ResidentType.TENANT)
        elif audience is AudienceScope.STAFF:
            # Staff are users with no resident row, so they are found from the
            # other side entirely.
            staff = await self.session.scalars(
                select(TenantUser.id).where(
                    TenantUser.is_active.is_(True),
                    TenantUser.id.not_in(
                        select(Resident.user_id).where(Resident.user_id.is_not(None))
                    ),
                )
            )
            return list(dict.fromkeys(staff))

        rows = await self.session.scalars(stmt)
        # A person owning two flats must not be notified twice.
        return list(dict.fromkeys(r for r in rows if r is not None))

    async def scope_for_user(
        self, user_id: uuid.UUID
    ) -> tuple[list[uuid.UUID], list[uuid.UUID], bool, bool]:
        """``(building_ids, block_ids, is_owner, is_tenant)`` for one reader."""
        from app.models.tenant import Flat, Resident, ResidentType

        rows = await self.session.execute(
            select(Flat.building_id, Flat.block_id, Resident.resident_type)
            .join(Resident, Resident.flat_id == Flat.id)
            .where(Resident.user_id == user_id, Resident.is_active.is_(True))
        )
        buildings: list[uuid.UUID] = []
        blocks: list[uuid.UUID] = []
        is_owner = False
        is_tenant = False
        for building_id, block_id, resident_type in rows:
            if building_id is not None and building_id not in buildings:
                buildings.append(building_id)
            if block_id is not None and block_id not in blocks:
                blocks.append(block_id)
            if resident_type == ResidentType.OWNER:
                is_owner = True
            elif resident_type == ResidentType.TENANT:
                is_tenant = True
        return buildings, blocks, is_owner, is_tenant
