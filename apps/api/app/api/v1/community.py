"""Notices and amenity bookings."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import TenantSession, require_permission
from app.auth.principal import Principal
from app.core.permissions import Permission
from app.schemas.common import Envelope, Page, PageParams, ok
from app.schemas.community import (
    AmenityCreate,
    AmenityRead,
    AmenitySummary,
    AmenityUpdate,
    AvailabilityRead,
    BookingCancel,
    BookingCreate,
    BookingDecision,
    BookingRead,
    NoticeCreate,
    NoticeRead,
    NoticeSummary,
    NoticeUpdate,
)
from app.services.community import AmenityService, NoticeService

router = APIRouter(tags=["community"])

PageDep = Annotated[PageParams, Depends()]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# --------------------------------------------------------------------------- #
# Notices
# --------------------------------------------------------------------------- #

notices = APIRouter(prefix="/notices", tags=["notices"])


@notices.get(
    "",
    response_model=Envelope[Page[NoticeRead]],
    summary="List notices",
    description=(
        "A reader sees only notices addressed to them: society-wide, their own "
        "building or block, and their own owner/tenant group. Someone who can "
        "manage notices sees every notice, including scheduled drafts."
    ),
)
async def list_notices(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.NOTICE_READ))],
    params: PageDep,
    category: Annotated[str | None, Query(max_length=30)] = None,
    include_unpublished: bool = False,
) -> dict[str, Any]:
    items, total = await NoticeService(tenant).list(
        principal,
        page=params.page,
        limit=params.limit,
        q=params.q,
        category=category,
        include_unpublished=include_unpublished,
    )
    return ok(Page.build(items, page=params.page, limit=params.limit, total=total))


@notices.get("/summary", response_model=Envelope[NoticeSummary], summary="Notice counts")
async def notice_summary(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.NOTICE_READ))],
) -> dict[str, Any]:
    return ok(await NoticeService(tenant).summary(principal))


@notices.get(
    "/{notice_id}",
    response_model=Envelope[NoticeRead],
    summary="Read a notice",
    description="Opening a notice marks it read for the caller.",
)
async def get_notice(
    notice_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.NOTICE_READ))],
) -> dict[str, Any]:
    return ok(await NoticeService(tenant).get(notice_id, principal))


@notices.post(
    "",
    response_model=Envelope[NoticeRead],
    status_code=status.HTTP_201_CREATED,
    summary="Post a notice",
)
async def create_notice(
    payload: NoticeCreate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.NOTICE_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    notice = await NoticeService(tenant).create(payload, principal, request_id=_rid(request))
    return ok(notice, "Notice published." if notice["is_published"] else "Notice saved.")


@notices.patch(
    "/{notice_id}", response_model=Envelope[NoticeRead], summary="Edit a notice"
)
async def update_notice(
    notice_id: uuid.UUID,
    payload: NoticeUpdate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.NOTICE_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await NoticeService(tenant).update(
            notice_id, payload, principal, request_id=_rid(request)
        ),
        "Notice updated.",
    )


@notices.post(
    "/{notice_id}/publication",
    response_model=Envelope[NoticeRead],
    summary="Publish a draft notice now",
)
async def publish_notice(
    notice_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.NOTICE_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await NoticeService(tenant).publish(notice_id, principal, request_id=_rid(request)),
        "Notice published.",
    )


@notices.post(
    "/{notice_id}/read", response_model=Envelope[None], summary="Mark a notice read"
)
async def mark_notice_read(
    notice_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.NOTICE_READ))],
) -> dict[str, Any]:
    first = await NoticeService(tenant).mark_read(notice_id, principal)
    return ok(message="Marked read." if first else "Already read.")


@notices.delete("/{notice_id}", response_model=Envelope[None], summary="Delete a notice")
async def delete_notice(
    notice_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.NOTICE_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    await NoticeService(tenant).delete(notice_id, principal, request_id=_rid(request))
    return ok(message="Notice deleted.")


router.include_router(notices)


# --------------------------------------------------------------------------- #
# Amenities
# --------------------------------------------------------------------------- #

amenities = APIRouter(prefix="/amenities", tags=["amenities"])


@amenities.get("", response_model=Envelope[Page[AmenityRead]], summary="List amenities")
async def list_amenities(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.AMENITY_READ))],
    params: PageDep,
    include_inactive: bool = False,
) -> dict[str, Any]:
    items, total = await AmenityService(tenant).list(
        page=params.page,
        limit=params.limit,
        q=params.q,
        active_only=not include_inactive,
    )
    return ok(Page.build(items, page=params.page, limit=params.limit, total=total))


@amenities.get(
    "/summary", response_model=Envelope[AmenitySummary], summary="Booking activity"
)
async def amenity_summary(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.AMENITY_MANAGE))],
) -> dict[str, Any]:
    return ok(await AmenityService(tenant).summary())


@amenities.get(
    "/bookings",
    response_model=Envelope[Page[BookingRead]],
    summary="List bookings",
    description="A resident sees their own flat's bookings and nobody else's.",
)
async def list_bookings(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.AMENITY_READ))],
    params: PageDep,
    amenity_id: uuid.UUID | None = None,
    flat_id: uuid.UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=30)] = None,
    from_date: date | None = None,
    to_date: date | None = None,
    upcoming_only: bool = False,
    pending_only: bool = False,
) -> dict[str, Any]:
    items, total = await AmenityService(tenant).list_bookings(
        principal,
        page=params.page,
        limit=params.limit,
        amenity_id=amenity_id,
        flat_id=flat_id,
        status=status_filter,
        from_date=from_date,
        to_date=to_date,
        upcoming_only=upcoming_only,
        pending_only=pending_only,
    )
    return ok(Page.build(items, page=params.page, limit=params.limit, total=total))


@amenities.post(
    "/bookings",
    response_model=Envelope[BookingRead],
    status_code=status.HTTP_201_CREATED,
    summary="Book a slot",
)
async def create_booking(
    payload: BookingCreate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.AMENITY_BOOK))],
    request: Request,
) -> dict[str, Any]:
    booking = await AmenityService(tenant).book(payload, principal, request_id=_rid(request))
    return ok(
        booking,
        "Booking confirmed."
        if booking["status"].value == "CONFIRMED"
        else "Booking requested. You will be told once it is approved.",
    )


@amenities.post(
    "/bookings/{booking_id}/decision",
    response_model=Envelope[BookingRead],
    summary="Approve or reject a booking request",
)
async def decide_booking(
    booking_id: uuid.UUID,
    payload: BookingDecision,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.AMENITY_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    booking = await AmenityService(tenant).decide(
        booking_id, payload, principal, request_id=_rid(request)
    )
    return ok(booking, "Booking confirmed." if payload.approved else "Booking rejected.")


@amenities.post(
    "/bookings/{booking_id}/cancellation",
    response_model=Envelope[BookingRead],
    summary="Cancel a booking",
)
async def cancel_booking(
    booking_id: uuid.UUID,
    payload: BookingCancel,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.AMENITY_BOOK))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await AmenityService(tenant).cancel(
            booking_id, payload, principal, request_id=_rid(request)
        ),
        "Booking cancelled.",
    )


@amenities.get(
    "/{amenity_id}", response_model=Envelope[AmenityRead], summary="Get an amenity"
)
async def get_amenity(
    amenity_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.AMENITY_READ))],
) -> dict[str, Any]:
    return ok(await AmenityService(tenant).get(amenity_id))


@amenities.get(
    "/{amenity_id}/availability",
    response_model=Envelope[AvailabilityRead],
    summary="One day's slot grid",
)
async def availability(
    amenity_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.AMENITY_READ))],
    on: date | None = None,
) -> dict[str, Any]:
    return ok(
        await AmenityService(tenant).availability(amenity_id, on or date.today(), principal)
    )


@amenities.post(
    "",
    response_model=Envelope[AmenityRead],
    status_code=status.HTTP_201_CREATED,
    summary="Add an amenity",
)
async def create_amenity(
    payload: AmenityCreate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.AMENITY_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await AmenityService(tenant).create(payload, principal, request_id=_rid(request)),
        "Amenity added.",
    )


@amenities.patch(
    "/{amenity_id}", response_model=Envelope[AmenityRead], summary="Update an amenity"
)
async def update_amenity(
    amenity_id: uuid.UUID,
    payload: AmenityUpdate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.AMENITY_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await AmenityService(tenant).update(
            amenity_id, payload, principal, request_id=_rid(request)
        ),
        "Amenity updated.",
    )


router.include_router(amenities)
