"""Notice and amenity services.

The interesting part of this module is the booking path, and it is short on
purpose: the *rules* (advance limit, slots per booking, quota per flat, slot
alignment) are checked here so the resident gets a sentence they can act on,
and the *race* is left entirely to PostgreSQL's exclusion constraint. Checking
availability in Python and inserting afterwards would pass every test and lose
every Sunday morning.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AlreadyExistsError, ConflictError, NotFoundError, ValidationError
from app.core.permissions import Permission
from app.models.tenant import (
    ACTIVE_BOOKING_STATUSES,
    Amenity,
    AmenityBooking,
    AudienceScope,
    BookingStatus,
    Notice,
)
from app.repositories.community import (
    AmenityRepository,
    BookingRepository,
    NoticeAudienceRepository,
    NoticeRepository,
)
from app.repositories.recipients import RecipientRepository
from app.repositories.structure import FlatRepository
from app.schemas.community import (
    AmenityCreate,
    AmenityUpdate,
    BookingCancel,
    BookingCreate,
    BookingDecision,
    NoticeCreate,
    NoticeUpdate,
)
from app.services.audit import AuditService, diff
from app.services.notifications import Category, NotificationService

log = structlog.get_logger(__name__)

CANCELLATION_CUTOFF_HOURS = 2
"""How close to the start a resident may still cancel.

Later than this and the slot cannot realistically be re-let, so a cancellation
is an admin action — which is also what stops "book everything, cancel at the
door" from being free.
"""


class AuditAction:
    NOTICE_CREATED = "NOTICE_CREATED"
    NOTICE_UPDATED = "NOTICE_UPDATED"
    NOTICE_PUBLISHED = "NOTICE_PUBLISHED"
    NOTICE_DELETED = "NOTICE_DELETED"
    AMENITY_CREATED = "AMENITY_CREATED"
    AMENITY_UPDATED = "AMENITY_UPDATED"
    BOOKING_CREATED = "BOOKING_CREATED"
    BOOKING_DECIDED = "BOOKING_DECIDED"
    BOOKING_CANCELLED = "BOOKING_CANCELLED"


def _now() -> datetime:
    return datetime.now(UTC)


def _building_name(obj: Any) -> str | None:
    building = getattr(obj, "building", None)
    return getattr(building, "name", None) if building is not None else None


def _flat_number(obj: Any) -> str | None:
    flat = getattr(obj, "flat", None)
    return getattr(flat, "flat_number", None) if flat is not None else None


# --------------------------------------------------------------------------- #
# Notices
# --------------------------------------------------------------------------- #


def _notice_dict(
    n: Notice, *, is_read: bool = False, read_count: int = 0
) -> dict[str, Any]:
    block = getattr(n, "block", None)
    return {
        "id": n.id,
        "title": n.title,
        "body": n.body,
        "category": n.category,
        "priority": n.priority,
        "audience": n.audience,
        "building_id": n.building_id,
        "building_name": _building_name(n),
        "block_id": n.block_id,
        "block_name": getattr(block, "name", None),
        "is_pinned": n.is_pinned,
        "is_published": n.is_published,
        "publish_at": n.publish_at,
        "expires_at": n.expires_at,
        "is_expired": bool(n.expires_at is not None and n.expires_at <= _now()),
        "attachments": n.attachments or [],
        "author_id": n.author_id,
        "author_name": n.author_name,
        "is_read": is_read,
        "read_count": read_count,
        "created_at": n.created_at,
    }


class NoticeService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = NoticeRepository(tenant)
        self.audience = NoticeAudienceRepository(tenant)
        self.recipients = RecipientRepository(tenant)
        self.notifications = NotificationService(tenant)

    def _can_manage(self, principal: Principal) -> bool:
        return principal.has(Permission.NOTICE_MANAGE)

    async def _audience_for(self, principal: Principal) -> Any:
        """The filter that decides which notices reach this reader.

        Staff — a guard, a housekeeper — hold no flats, so they see society-wide
        and staff notices. That is the correct answer rather than a special
        case: an audience they are not in is an audience they should not read.
        """
        if principal.tenant_user_id is None:
            return None
        buildings, blocks, is_owner, is_tenant = await self.audience.scope_for_user(
            principal.tenant_user_id
        )
        is_staff = not buildings and not blocks
        return self.repo._audience_filter(
            building_ids=buildings,
            block_ids=blocks,
            is_owner=is_owner,
            is_tenant=is_tenant,
            is_staff=is_staff,
        )

    async def list(
        self,
        principal: Principal,
        *,
        page: int,
        limit: int,
        q: str | None = None,
        category: str | None = None,
        include_unpublished: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        manage = self._can_manage(principal)
        rows, total = await self.repo.list(
            page=page,
            limit=limit,
            q=q,
            category=category,
            include_unpublished=include_unpublished and manage,
            audience=None if manage else await self._audience_for(principal),
        )
        ids = [n.id for n in rows]
        read = (
            await self.repo.read_ids_for(principal.tenant_user_id, ids)
            if principal.tenant_user_id
            else set()
        )
        counts = await self.repo.read_counts(ids) if manage else {}
        return [
            _notice_dict(n, is_read=n.id in read, read_count=counts.get(n.id, 0))
            for n in rows
        ], total

    async def get(self, notice_id: uuid.UUID, principal: Principal) -> dict[str, Any]:
        notice = await self.repo.get(notice_id)
        if notice is None:
            raise NotFoundError("Notice")
        manage = self._can_manage(principal)
        if not manage and not notice.is_published:
            # An unpublished draft does not exist as far as a resident is
            # concerned, and saying "forbidden" would confirm it is being written.
            raise NotFoundError("Notice")

        read = False
        if principal.tenant_user_id is not None:
            # Opening a notice is reading it.
            await self.repo.mark_read(notice.id, principal.tenant_user_id)
            read = True
        counts = await self.repo.read_counts([notice.id]) if manage else {}
        return _notice_dict(notice, is_read=read, read_count=counts.get(notice.id, 0))

    async def summary(self, principal: Principal) -> dict[str, int]:
        return await self.repo.summary(principal.tenant_user_id)

    async def unread_count(self, principal: Principal) -> int:
        if principal.tenant_user_id is None:
            return 0
        return await self.repo.unread_count(
            principal.tenant_user_id,
            None if self._can_manage(principal) else await self._audience_for(principal),
        )

    async def create(
        self, payload: NoticeCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        if payload.building_id is not None:
            from app.repositories.structure import BuildingRepository

            if await BuildingRepository(self.tenant).get(payload.building_id) is None:
                raise NotFoundError("Building")
        if payload.block_id is not None:
            from app.repositories.structure import BlockRepository

            if await BlockRepository(self.tenant).get(payload.block_id) is None:
                raise NotFoundError("Block")

        now = _now()
        publish_at = payload.publish_at or (now if payload.publish_now else None)
        notice = Notice(
            title=payload.title,
            body=payload.body,
            category=payload.category,
            priority=payload.priority,
            audience=payload.audience,
            building_id=payload.building_id,
            block_id=payload.block_id,
            is_pinned=payload.is_pinned,
            is_published=payload.publish_now or publish_at is not None,
            publish_at=publish_at,
            expires_at=payload.expires_at,
            attachments=[a.model_dump() for a in payload.attachments] or None,
            author_id=principal.tenant_user_id,
            author_name=principal.display_name or principal.email,
        )
        await self.repo.create(notice)
        await self.tenant.refresh(notice)

        if notice.is_published and (publish_at is None or publish_at <= now):
            await self.announce(notice, actor=principal.tenant_user_id)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.NOTICE_CREATED,
            principal=principal,
            target_type="notices",
            target_id=notice.id,
            changes={"after": {"title": notice.title, "audience": notice.audience.value}},
            request_id=request_id,
        )
        return _notice_dict(notice)

    async def announce(self, notice: Notice, *, actor: uuid.UUID | None = None) -> int:
        """Push a published notice to the people it is addressed to.

        A society-wide notice is broadcast rather than fanned out into 300
        notification rows — the notice list is already its durable record, and
        writing a row per resident to say "there is a notice" duplicates it.
        """
        if notice.audience is AudienceScope.ALL:
            await self.notifications.broadcast(
                category=Category.NOTICE_PUBLISHED,
                title=notice.title,
                body=notice.category.value.replace("_", " ").title(),
                link=f"/app/notices?id={notice.id}",
                payload={"notice_id": str(notice.id), "priority": notice.priority.value},
            )
            return 0

        recipients = await self.audience.recipient_user_ids(
            audience=notice.audience,
            building_id=notice.building_id,
            block_id=notice.block_id,
        )
        return await self.notifications.notify(
            recipients,
            category=Category.NOTICE_PUBLISHED,
            title=notice.title,
            body=notice.category.value.replace("_", " ").title(),
            link=f"/app/notices?id={notice.id}",
            payload={"notice_id": str(notice.id)},
            exclude=actor,
        )

    async def update(
        self,
        notice_id: uuid.UUID,
        payload: NoticeUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        notice = await self.repo.get(notice_id)
        if notice is None:
            raise NotFoundError("Notice")

        before = _notice_dict(notice)
        changes = payload.model_dump(exclude_unset=True)
        if "attachments" in changes and changes["attachments"] is not None:
            changes["attachments"] = [dict(a) for a in changes["attachments"]] or None
        for key, value in changes.items():
            setattr(notice, key, value)
        await self.tenant.flush()
        await self.tenant.refresh(notice)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.NOTICE_UPDATED,
            principal=principal,
            target_type="notices",
            target_id=notice.id,
            changes=diff(
                {k: str(v) for k, v in before.items()},
                {k: str(v) for k, v in _notice_dict(notice).items()},
            ),
            request_id=request_id,
        )
        return _notice_dict(notice)

    async def publish(
        self, notice_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        notice = await self.repo.get(notice_id)
        if notice is None:
            raise NotFoundError("Notice")
        if notice.is_published and (
            notice.publish_at is None or notice.publish_at <= _now()
        ):
            raise ConflictError("This notice is already published.")

        notice.is_published = True
        notice.publish_at = _now()
        await self.tenant.flush()
        await self.announce(notice, actor=principal.tenant_user_id)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.NOTICE_PUBLISHED,
            principal=principal,
            target_type="notices",
            target_id=notice.id,
            request_id=request_id,
        )
        await self.tenant.refresh(notice)
        return _notice_dict(notice)

    async def mark_read(self, notice_id: uuid.UUID, principal: Principal) -> bool:
        if principal.tenant_user_id is None:
            raise NotFoundError("Notice")
        if await self.repo.get(notice_id) is None:
            raise NotFoundError("Notice")
        return await self.repo.mark_read(notice_id, principal.tenant_user_id)

    async def delete(
        self, notice_id: uuid.UUID, principal: Principal, *, request_id: str | None = None
    ) -> None:
        notice = await self.repo.get(notice_id)
        if notice is None:
            raise NotFoundError("Notice")
        snapshot = {"title": notice.title, "audience": notice.audience.value}
        await self.tenant.delete(notice)
        await self.tenant.flush()
        await AuditService.tenant(
            self.tenant,
            action=AuditAction.NOTICE_DELETED,
            principal=principal,
            target_type="notices",
            target_id=notice_id,
            changes={"before": snapshot},
            request_id=request_id,
        )

    async def publish_scheduled(self) -> int:
        """Publish notices whose scheduled moment has arrived."""
        due = await self.repo.due_for_publication()
        for notice in due:
            notice.is_published = True
            await self.announce(notice)
        if due:
            await self.tenant.flush()
        return len(due)


# --------------------------------------------------------------------------- #
# Amenities
# --------------------------------------------------------------------------- #


def _amenity_dict(a: Amenity, *, upcoming: int = 0) -> dict[str, Any]:
    return {
        "id": a.id,
        "name": a.name,
        "description": a.description,
        "location": a.location,
        "building_id": a.building_id,
        "building_name": _building_name(a),
        "capacity": a.capacity,
        "opens_at": a.opens_at,
        "closes_at": a.closes_at,
        "slot_minutes": a.slot_minutes,
        "booking_charge": a.booking_charge,
        "max_advance_days": a.max_advance_days,
        "max_slots_per_booking": a.max_slots_per_booking,
        "max_active_per_flat": a.max_active_per_flat,
        "requires_approval": a.requires_approval,
        "rules": a.rules,
        "is_active": a.is_active,
        "upcoming_bookings": upcoming,
        "created_at": a.created_at,
    }


def _booking_dict(b: AmenityBooking, *, can_cancel: bool = False) -> dict[str, Any]:
    amenity = b.amenity if "amenity" in b.__dict__ else None
    return {
        "id": b.id,
        "amenity_id": b.amenity_id,
        "amenity_name": getattr(amenity, "name", None),
        "flat_id": b.flat_id,
        "flat_number": _flat_number(b),
        "booked_by": b.booked_by,
        "booked_by_name": b.booked_by_name,
        "booking_date": b.booking_date,
        "starts_at": b.starts_at,
        "ends_at": b.ends_at,
        "slots": b.slots,
        "guests": b.guests,
        "purpose": b.purpose,
        "status": b.status,
        "charge": b.charge,
        "approved_at": b.approved_at,
        "cancelled_at": b.cancelled_at,
        "cancellation_reason": b.cancellation_reason,
        "can_cancel": can_cancel,
        "created_at": b.created_at,
    }


def _slot_starts(opens: time, closes: time, minutes: int) -> list[tuple[time, time]]:
    """The grid, as (start, end) pairs.

    Computed from the amenity rather than stored, so changing opening hours does
    not require rewriting a slot table — and a booking already made keeps its
    own timestamps regardless.
    """
    step = timedelta(minutes=minutes)
    cursor = timedelta(hours=opens.hour, minutes=opens.minute)
    limit = timedelta(hours=closes.hour, minutes=closes.minute)
    grid: list[tuple[time, time]] = []
    while cursor + step <= limit:
        end = cursor + step
        grid.append(
            (
                time(cursor.seconds // 3600, (cursor.seconds // 60) % 60),
                time((end.seconds // 3600) % 24, (end.seconds // 60) % 60),
            )
        )
        cursor = end
    return grid


class AmenityService:
    def __init__(self, tenant: AsyncSession) -> None:
        self.tenant = tenant
        self.repo = AmenityRepository(tenant)
        self.bookings = BookingRepository(tenant)
        self.recipients = RecipientRepository(tenant)
        self.notifications = NotificationService(tenant)

    def _can_manage(self, principal: Principal) -> bool:
        return principal.has(Permission.AMENITY_MANAGE)

    async def list(
        self, *, page: int, limit: int, q: str | None = None, active_only: bool = True
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.repo.list(
            page=page, limit=limit, q=q, active_only=active_only
        )
        counts = await self.repo.upcoming_counts([a.id for a in rows])
        return [_amenity_dict(a, upcoming=counts.get(a.id, 0)) for a in rows], total

    async def get(self, amenity_id: uuid.UUID) -> dict[str, Any]:
        amenity = await self.repo.get(amenity_id)
        if amenity is None:
            raise NotFoundError("Amenity")
        return _amenity_dict(amenity)

    async def create(
        self, payload: AmenityCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        if await self.repo.get_by_name(payload.name):
            raise AlreadyExistsError(f"An amenity called '{payload.name}' already exists.")

        amenity = Amenity(**payload.model_dump())
        await self.repo.create(amenity)
        await self.tenant.refresh(amenity)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.AMENITY_CREATED,
            principal=principal,
            target_type="amenities",
            target_id=amenity.id,
            changes={"after": {"name": amenity.name}},
            request_id=request_id,
        )
        return _amenity_dict(amenity)

    async def update(
        self,
        amenity_id: uuid.UUID,
        payload: AmenityUpdate,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        amenity = await self.repo.get(amenity_id)
        if amenity is None:
            raise NotFoundError("Amenity")

        before = _amenity_dict(amenity)
        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(amenity, key, value)
        if amenity.closes_at <= amenity.opens_at:
            raise ValidationError("Closing time must be after opening time.")
        await self.tenant.flush()
        await self.tenant.refresh(amenity)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.AMENITY_UPDATED,
            principal=principal,
            target_type="amenities",
            target_id=amenity.id,
            changes=diff(
                {k: str(v) for k, v in before.items()},
                {k: str(v) for k, v in _amenity_dict(amenity).items()},
            ),
            request_id=request_id,
        )
        return _amenity_dict(amenity)

    # -- availability ------------------------------------------------------- #

    async def availability(
        self, amenity_id: uuid.UUID, on: date, principal: Principal
    ) -> dict[str, Any]:
        amenity = await self.repo.get(amenity_id)
        if amenity is None:
            raise NotFoundError("Amenity")

        taken = await self.bookings.for_day(amenity_id, on)
        own_flats = set(principal.flat_ids)
        manage = self._can_manage(principal)

        slots: list[dict[str, Any]] = []
        for start, end in _slot_starts(amenity.opens_at, amenity.closes_at, amenity.slot_minutes):
            starts_at = datetime.combine(on, start, tzinfo=UTC)
            ends_at = datetime.combine(on, end, tzinfo=UTC)
            booking = next(
                (
                    b
                    for b in taken
                    if b.starts_at < ends_at and b.ends_at > starts_at
                ),
                None,
            )
            is_own = booking is not None and booking.flat_id in own_flats
            slots.append(
                {
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "label": f"{start:%H:%M}–{end:%H:%M}",
                    "available": booking is None,
                    # Who is having a party is not public information; an admin
                    # needs it to answer the phone, a neighbour does not.
                    "booked_by_flat": (
                        _flat_number(booking)
                        if booking is not None and (manage or is_own)
                        else None
                    ),
                    "is_own": is_own,
                    "booking_id": booking.id if booking is not None and (manage or is_own) else None,
                }
            )

        return {
            "amenity_id": amenity.id,
            "amenity_name": amenity.name,
            "booking_date": on,
            "slot_minutes": amenity.slot_minutes,
            "booking_charge": amenity.booking_charge,
            "slots": slots,
        }

    # -- bookings ----------------------------------------------------------- #

    def _owner_scope(self, principal: Principal) -> list[uuid.UUID] | None:
        if principal.is_scoped_to_own(Permission.AMENITY_BOOK):
            return sorted(principal.flat_ids)
        return None

    def _can_cancel(self, booking: AmenityBooking, principal: Principal) -> bool:
        if booking.status not in ACTIVE_BOOKING_STATUSES:
            return False
        if self._can_manage(principal):
            return True
        return (
            booking.flat_id in principal.flat_ids
            and booking.starts_at - _now() >= timedelta(hours=CANCELLATION_CUTOFF_HOURS)
        )

    async def list_bookings(
        self,
        principal: Principal,
        *,
        page: int,
        limit: int,
        amenity_id: uuid.UUID | None = None,
        flat_id: uuid.UUID | None = None,
        status: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        upcoming_only: bool = False,
        pending_only: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.bookings.list(
            page=page,
            limit=limit,
            amenity_id=amenity_id,
            flat_id=flat_id,
            status=status,
            from_date=from_date,
            to_date=to_date,
            upcoming_only=upcoming_only,
            pending_only=pending_only,
            only_flat_ids=self._owner_scope(principal),
        )
        return [
            _booking_dict(b, can_cancel=self._can_cancel(b, principal)) for b in rows
        ], total

    async def book(
        self, payload: BookingCreate, principal: Principal, *, request_id: str | None = None
    ) -> dict[str, Any]:
        amenity = await self.repo.get(payload.amenity_id)
        if amenity is None or not amenity.is_active:
            raise NotFoundError("Amenity")

        flat_id = await self._resolve_flat(payload.flat_id, principal)
        starts_at, ends_at = self._window(amenity, payload)

        if payload.slots > amenity.max_slots_per_booking:
            raise ValidationError(
                f"{amenity.name} can be booked for at most "
                f"{amenity.max_slots_per_booking} slot(s) at a time."
            )
        latest = _now() + timedelta(days=amenity.max_advance_days)
        if starts_at > latest:
            raise ValidationError(
                f"{amenity.name} can be booked up to {amenity.max_advance_days} days "
                f"ahead — that is {latest:%d %b %Y}."
            )
        if starts_at < _now():
            raise ValidationError("That slot is in the past.")

        held = await self.bookings.active_count_for_flat(amenity.id, flat_id)
        if held >= amenity.max_active_per_flat:
            raise ConflictError(
                f"This flat already holds {held} upcoming booking(s) for "
                f"{amenity.name}, which is the limit. Cancel one to make another."
            )

        needs_approval = amenity.requires_approval and not self._can_manage(principal)
        booking = AmenityBooking(
            amenity_id=amenity.id,
            flat_id=flat_id,
            booked_by=principal.tenant_user_id,
            booked_by_name=principal.display_name or principal.email,
            booking_date=starts_at.date(),
            starts_at=starts_at,
            ends_at=ends_at,
            slots=payload.slots,
            guests=payload.guests,
            purpose=payload.purpose,
            status=BookingStatus.PENDING if needs_approval else BookingStatus.CONFIRMED,
            # Snapshotted: a rate rise next month must not change what this
            # resident agreed to pay, exactly as a published bill is frozen.
            charge=Decimal(amenity.booking_charge) * payload.slots,
        )

        try:
            # A SAVEPOINT, not the whole transaction. The exclusion constraint
            # is *expected* to fire here — that is the race it exists for — and
            # rolling the outer transaction back would take the audit entry and
            # everything else in the request down with it, leaving the session
            # unusable for the error response.
            async with self.tenant.begin_nested():
                await self.bookings.create(booking)
        except IntegrityError as exc:
            raise ConflictError(
                f"That slot at {amenity.name} was taken while you were booking. "
                "Pick another time."
            ) from exc

        await self.tenant.refresh(booking)
        await self._announce_booking(booking, amenity, needs_approval, principal)

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.BOOKING_CREATED,
            principal=principal,
            target_type="amenity_bookings",
            target_id=booking.id,
            changes={
                "after": {
                    "amenity": amenity.name,
                    "starts_at": str(starts_at),
                    "slots": payload.slots,
                }
            },
            request_id=request_id,
        )
        return _booking_dict(booking, can_cancel=self._can_cancel(booking, principal))

    async def _resolve_flat(
        self, requested: uuid.UUID | None, principal: Principal
    ) -> uuid.UUID:
        scope = self._owner_scope(principal)
        if scope is not None:
            if not scope:
                raise ValidationError(
                    "Bookings are made against a flat, and no flat is linked to "
                    "this account yet."
                )
            if requested is not None and requested not in scope:
                raise NotFoundError("Flat")
            return requested or scope[0]

        if requested is None:
            raise ValidationError("Choose which flat this booking is for.")
        if await FlatRepository(self.tenant).get(requested) is None:
            raise NotFoundError("Flat")
        return requested

    def _window(self, amenity: Amenity, payload: BookingCreate) -> tuple[datetime, datetime]:
        """Snap-check the requested start against the amenity's grid."""
        starts_at = payload.starts_at
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=UTC)

        grid = _slot_starts(amenity.opens_at, amenity.closes_at, amenity.slot_minutes)
        wanted = starts_at.timetz().replace(tzinfo=None)
        index = next((i for i, (start, _end) in enumerate(grid) if start == wanted), None)
        if index is None:
            legal = ", ".join(f"{s:%H:%M}" for s, _ in grid[:6])
            raise ValidationError(
                f"{amenity.name} is booked in {amenity.slot_minutes}-minute slots "
                f"starting at {legal}…"
            )
        if index + payload.slots > len(grid):
            raise ValidationError(
                f"{amenity.name} closes at {amenity.closes_at:%H:%M}; "
                f"{payload.slots} slots from {wanted:%H:%M} runs past that."
            )

        end_time = grid[index + payload.slots - 1][1]
        return starts_at, datetime.combine(starts_at.date(), end_time, tzinfo=UTC)

    async def _announce_booking(
        self,
        booking: AmenityBooking,
        amenity: Amenity,
        needs_approval: bool,
        principal: Principal,
    ) -> None:
        if needs_approval:
            await self.notifications.notify(
                await self.recipients.users_with_permission(Permission.AMENITY_MANAGE),
                category=Category.BOOKING_PENDING,
                title=f"Booking to approve: {amenity.name}",
                body=f"{booking.booked_by_name} · {booking.starts_at:%d %b %H:%M}",
                link="/app/amenities",
                payload={"booking_id": str(booking.id)},
                exclude=principal.tenant_user_id,
            )
        else:
            await self.notifications.notify(
                await self.recipients.users_for_flat(booking.flat_id),
                category=Category.BOOKING_CONFIRMED,
                title=f"{amenity.name} booked",
                body=f"{booking.starts_at:%d %b %Y, %H:%M}–{booking.ends_at:%H:%M}",
                link="/app/amenities",
                payload={"booking_id": str(booking.id)},
                exclude=principal.tenant_user_id,
            )

    async def decide(
        self,
        booking_id: uuid.UUID,
        payload: BookingDecision,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        booking = await self.bookings.get(booking_id)
        if booking is None:
            raise NotFoundError("Booking")
        if booking.status is not BookingStatus.PENDING:
            raise ConflictError(
                f"This booking is already {booking.status.value.lower()}."
            )

        booking.status = (
            BookingStatus.CONFIRMED if payload.approved else BookingStatus.REJECTED
        )
        booking.approved_by = principal.tenant_user_id
        booking.approved_at = _now()
        if not payload.approved:
            booking.cancellation_reason = payload.reason
        await self.tenant.flush()

        await self.notifications.notify(
            await self.recipients.users_for_flat(booking.flat_id),
            category=Category.BOOKING_DECIDED,
            title=(
                "Your booking is confirmed" if payload.approved else "Your booking was declined"
            ),
            body=payload.reason or f"{booking.starts_at:%d %b %Y, %H:%M}",
            link="/app/amenities",
            payload={"booking_id": str(booking.id)},
            exclude=principal.tenant_user_id,
        )

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.BOOKING_DECIDED,
            principal=principal,
            target_type="amenity_bookings",
            target_id=booking.id,
            changes={"after": {"status": booking.status.value}},
            request_id=request_id,
        )
        await self.tenant.refresh(booking)
        return _booking_dict(booking, can_cancel=self._can_cancel(booking, principal))

    async def cancel(
        self,
        booking_id: uuid.UUID,
        payload: BookingCancel,
        principal: Principal,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        booking = await self.bookings.get(booking_id)
        if booking is None:
            raise NotFoundError("Booking")

        scope = self._owner_scope(principal)
        if scope is not None and booking.flat_id not in scope:
            raise NotFoundError("Booking")
        if booking.status not in ACTIVE_BOOKING_STATUSES:
            raise ConflictError(f"This booking is already {booking.status.value.lower()}.")
        if not self._can_cancel(booking, principal):
            raise ConflictError(
                f"A booking can be cancelled up to {CANCELLATION_CUTOFF_HOURS} hours "
                "before it starts. Speak to the office."
            )

        booking.status = BookingStatus.CANCELLED
        booking.cancelled_at = _now()
        booking.cancellation_reason = payload.reason
        await self.tenant.flush()

        await AuditService.tenant(
            self.tenant,
            action=AuditAction.BOOKING_CANCELLED,
            principal=principal,
            target_type="amenity_bookings",
            target_id=booking.id,
            changes={"after": {"status": booking.status.value}},
            request_id=request_id,
        )
        await self.tenant.refresh(booking)
        return _booking_dict(booking)

    async def summary(self) -> dict[str, Any]:
        today = date.today()
        summary = await self.bookings.summary(
            today=today, month_start=today.replace(day=1)
        )
        summary["amenities"] = await self.repo.count_active()
        return summary

    # -- sweeps ------------------------------------------------------------- #

    async def complete_past(self) -> int:
        """Move finished bookings out of the live set.

        A booking that stays CONFIRMED forever keeps holding its slot in the
        exclusion constraint's eyes and inflates "upcoming" on every dashboard.
        """
        past = await self.bookings.past_confirmed(_now())
        for booking in past:
            booking.status = BookingStatus.COMPLETED
        if past:
            await self.tenant.flush()
        return len(past)

    async def send_reminders(self, *, within_hours: int = 24) -> int:
        """Nudge residents whose booking starts inside the window."""
        start = _now()
        upcoming = await self.bookings.starting_between(
            start, start + timedelta(hours=within_hours)
        )
        sent = 0
        for booking in upcoming:
            amenity = await self.repo.get(booking.amenity_id)
            sent += await self.notifications.notify(
                await self.recipients.users_for_flat(booking.flat_id),
                category=Category.BOOKING_REMINDER,
                title=f"Reminder: {getattr(amenity, 'name', 'amenity')} today",
                body=f"{booking.starts_at:%H:%M}–{booking.ends_at:%H:%M}",
                link="/app/amenities",
                payload={"booking_id": str(booking.id)},
            )
        return sent
