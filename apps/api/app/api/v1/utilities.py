"""Water, electricity, parking, vehicle, pet and dashboard endpoints.

Water and electricity are the same resource shape twice over, so the routes are
generated from one factory rather than written out and left to drift.

As everywhere else in the tenant API: no society parameter appears in any
signature. The tenant is the session.
"""

# No ``from __future__ import annotations`` here, deliberately. The reading
# routes are built by a factory, so their annotations reference closure
# variables (``read``, ``manage``); stringified annotations are resolved
# against module globals, where those names do not exist.

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import TenantSession, require_permission
from app.auth.principal import Principal
from app.core.permissions import Permission
from app.schemas.common import Envelope, Page, PageParams, ok
from app.schemas.utilities import (
    BulkReadingCreate,
    BulkReadingResult,
    ConsumptionTrend,
    ElectricityReadingCreate,
    ParkingAllotment,
    ParkingSlotCreate,
    ParkingSlotRead,
    ParkingSlotUpdate,
    ParkingSummary,
    PendingFlat,
    PetCreate,
    PetRead,
    PetUpdate,
    ReadingRead,
    ReadingUpdate,
    ResidentDashboard,
    SocietyConsumptionPoint,
    VehicleCreate,
    VehicleRead,
    VehicleUpdate,
    WaterReadingCreate,
)
from app.services.dashboard import ResidentDashboardService, SocietyUtilityDashboardService
from app.services.utilities import ParkingService, PetService, ReadingService, VehicleService

router = APIRouter(tags=["utilities"])

PageDep = Annotated[PageParams, Depends()]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# --------------------------------------------------------------------------- #
# Readings — one factory, mounted twice
# --------------------------------------------------------------------------- #


def _reading_routes(utility: str, *, read: Permission, manage: Permission) -> APIRouter:
    sub = APIRouter(prefix=f"/{utility}", tags=[utility])
    label = utility.capitalize()

    @sub.get(
        "/readings",
        response_model=Envelope[Page[ReadingRead]],
        summary=f"List {utility} readings",
    )
    async def list_readings(
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(read))],
        params: PageDep,
        flat_id: uuid.UUID | None = None,
        period_key: Annotated[str | None, Query(max_length=20)] = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> dict[str, Any]:
        items, total = await ReadingService(tenant, utility=utility).list(
            principal,
            page=params.page,
            limit=params.limit,
            flat_id=flat_id,
            period_key=period_key,
            from_date=from_date,
            to_date=to_date,
        )
        return ok(Page.build(items, page=params.page, limit=params.limit, total=total))

    @sub.get(
        "/pending",
        response_model=Envelope[list[PendingFlat]],
        summary=f"Flats awaiting a {utility} reading",
    )
    async def pending(
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(manage))],
    ) -> dict[str, Any]:
        return ok(await ReadingService(tenant, utility=utility).pending(principal))

    @sub.get(
        "/trend/{flat_id}",
        response_model=Envelope[ConsumptionTrend],
        summary=f"{label} consumption trend for a flat",
    )
    async def trend(
        flat_id: uuid.UUID,
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(read))],
        months: Annotated[int, Query(ge=3, le=36)] = 12,
    ) -> dict[str, Any]:
        return ok(
            await ReadingService(tenant, utility=utility).trend(
                flat_id, principal, limit=months
            )
        )

    @sub.get(
        "/society-trend",
        response_model=Envelope[list[SocietyConsumptionPoint]],
        summary=f"Society-wide {utility} consumption",
    )
    async def society_trend(
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(manage))],
        months: Annotated[int, Query(ge=3, le=36)] = 12,
    ) -> dict[str, Any]:
        return ok(await ReadingService(tenant, utility=utility).society_trend(months))

    @sub.get(
        "/readings/{reading_id}",
        response_model=Envelope[ReadingRead],
        summary=f"Get a {utility} reading",
    )
    async def get_reading(
        reading_id: uuid.UUID,
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(read))],
    ) -> dict[str, Any]:
        return ok(await ReadingService(tenant, utility=utility).get(reading_id, principal))

    @sub.post(
        "/readings/bulk",
        response_model=Envelope[BulkReadingResult],
        status_code=status.HTTP_201_CREATED,
        summary=f"Record a round of {utility} readings",
    )
    async def bulk_create(
        payload: BulkReadingCreate,
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(manage))],
        request: Request,
    ) -> dict[str, Any]:
        result = await ReadingService(tenant, utility=utility).bulk_create(
            payload, principal, request_id=_rid(request)
        )
        return ok(result, f"{result['created']} readings recorded.")

    @sub.patch(
        "/readings/{reading_id}",
        response_model=Envelope[ReadingRead],
        summary=f"Correct a {utility} reading",
    )
    async def update_reading(
        reading_id: uuid.UUID,
        payload: ReadingUpdate,
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(manage))],
        request: Request,
    ) -> dict[str, Any]:
        return ok(
            await ReadingService(tenant, utility=utility).update(
                reading_id, payload, principal, request_id=_rid(request)
            ),
            "Reading updated.",
        )

    @sub.delete(
        "/readings/{reading_id}",
        response_model=Envelope[None],
        summary=f"Delete a {utility} reading",
    )
    async def delete_reading(
        reading_id: uuid.UUID,
        tenant: TenantSession,
        principal: Annotated[Principal, Depends(require_permission(manage))],
        request: Request,
    ) -> dict[str, Any]:
        await ReadingService(tenant, utility=utility).delete(
            reading_id, principal, request_id=_rid(request)
        )
        return ok(message="Reading deleted.")

    return sub


router.include_router(
    _reading_routes("water", read=Permission.WATER_READ, manage=Permission.WATER_MANAGE)
)
router.include_router(
    _reading_routes(
        "electricity",
        read=Permission.ELECTRICITY_READ,
        manage=Permission.ELECTRICITY_MANAGE,
    )
)


# The two create routes are spelled out rather than generated: the request body
# differs (electricity carries a pass-through ``amount``), and a body type has
# to be a resolvable module-level name for FastAPI to build its schema.


@router.post(
    "/water/readings",
    response_model=Envelope[ReadingRead],
    status_code=status.HTTP_201_CREATED,
    tags=["water"],
    summary="Record a water reading",
)
async def create_water_reading(
    payload: WaterReadingCreate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.WATER_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await ReadingService(tenant, utility="water").create(
            payload, principal, request_id=_rid(request)
        ),
        "Water reading recorded.",
    )


@router.post(
    "/electricity/readings",
    response_model=Envelope[ReadingRead],
    status_code=status.HTTP_201_CREATED,
    tags=["electricity"],
    summary="Record an electricity reading",
)
async def create_electricity_reading(
    payload: ElectricityReadingCreate,
    tenant: TenantSession,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.ELECTRICITY_MANAGE))
    ],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await ReadingService(tenant, utility="electricity").create(
            payload, principal, request_id=_rid(request)
        ),
        "Electricity reading recorded.",
    )


# --------------------------------------------------------------------------- #
# Parking
# --------------------------------------------------------------------------- #


@router.get(
    "/parking/slots",
    response_model=Envelope[Page[ParkingSlotRead]],
    summary="List parking slots",
)
async def list_slots(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.PARKING_READ))],
    params: PageDep,
    flat_id: uuid.UUID | None = None,
    unallotted_only: bool = False,
) -> dict[str, Any]:
    items, total = await ParkingService(tenant).list(
        principal,
        page=params.page,
        limit=params.limit,
        q=params.q,
        flat_id=flat_id,
        unallotted_only=unallotted_only,
    )
    return ok(Page.build(items, page=params.page, limit=params.limit, total=total))


@router.get(
    "/parking/summary",
    response_model=Envelope[ParkingSummary],
    summary="Parking occupancy",
)
async def parking_summary(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.PARKING_MANAGE))],
) -> dict[str, Any]:
    return ok(await ParkingService(tenant).summary())


@router.post(
    "/parking/slots",
    response_model=Envelope[ParkingSlotRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create a parking slot",
)
async def create_slot(
    payload: ParkingSlotCreate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.PARKING_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await ParkingService(tenant).create(payload, principal, request_id=_rid(request)),
        "Parking slot created.",
    )


@router.patch(
    "/parking/slots/{slot_id}",
    response_model=Envelope[ParkingSlotRead],
    summary="Update a parking slot",
)
async def update_slot(
    slot_id: uuid.UUID,
    payload: ParkingSlotUpdate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.PARKING_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await ParkingService(tenant).update(
            slot_id, payload, principal, request_id=_rid(request)
        ),
        "Parking slot updated.",
    )


@router.post(
    "/parking/slots/{slot_id}/allotment",
    response_model=Envelope[ParkingSlotRead],
    summary="Allot or release a parking slot",
)
async def allot_slot(
    slot_id: uuid.UUID,
    payload: ParkingAllotment,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.PARKING_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    slot = await ParkingService(tenant).allot(
        slot_id, payload, principal, request_id=_rid(request)
    )
    return ok(slot, "Slot released." if payload.flat_id is None else "Slot allotted.")


# --------------------------------------------------------------------------- #
# Vehicles
# --------------------------------------------------------------------------- #


@router.get("/vehicles", response_model=Envelope[Page[VehicleRead]], summary="List vehicles")
async def list_vehicles(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.VEHICLE_READ))],
    params: PageDep,
    flat_id: uuid.UUID | None = None,
    vehicle_type: Annotated[str | None, Query(max_length=20)] = None,
) -> dict[str, Any]:
    items, total = await VehicleService(tenant).list(
        principal,
        page=params.page,
        limit=params.limit,
        q=params.q,
        flat_id=flat_id,
        vehicle_type=vehicle_type,
    )
    return ok(Page.build(items, page=params.page, limit=params.limit, total=total))


@router.get(
    "/vehicles/{vehicle_id}", response_model=Envelope[VehicleRead], summary="Get a vehicle"
)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.VEHICLE_READ))],
) -> dict[str, Any]:
    return ok(await VehicleService(tenant).get(vehicle_id, principal))


@router.post(
    "/vehicles",
    response_model=Envelope[VehicleRead],
    status_code=status.HTTP_201_CREATED,
    summary="Register a vehicle",
)
async def create_vehicle(
    payload: VehicleCreate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.VEHICLE_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await VehicleService(tenant).create(payload, principal, request_id=_rid(request)),
        "Vehicle registered.",
    )


@router.patch(
    "/vehicles/{vehicle_id}", response_model=Envelope[VehicleRead], summary="Update a vehicle"
)
async def update_vehicle(
    vehicle_id: uuid.UUID,
    payload: VehicleUpdate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.VEHICLE_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await VehicleService(tenant).update(
            vehicle_id, payload, principal, request_id=_rid(request)
        ),
        "Vehicle updated.",
    )


@router.delete(
    "/vehicles/{vehicle_id}", response_model=Envelope[None], summary="Remove a vehicle"
)
async def remove_vehicle(
    vehicle_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.VEHICLE_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    await VehicleService(tenant).remove(vehicle_id, principal, request_id=_rid(request))
    return ok(message="Vehicle removed.")


# --------------------------------------------------------------------------- #
# Pets
# --------------------------------------------------------------------------- #


@router.get("/pets", response_model=Envelope[Page[PetRead]], summary="List pets")
async def list_pets(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.PET_READ))],
    params: PageDep,
    flat_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    items, total = await PetService(tenant).list(
        principal, page=params.page, limit=params.limit, q=params.q, flat_id=flat_id
    )
    return ok(Page.build(items, page=params.page, limit=params.limit, total=total))


@router.post(
    "/pets",
    response_model=Envelope[PetRead],
    status_code=status.HTTP_201_CREATED,
    summary="Register a pet",
)
async def create_pet(
    payload: PetCreate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.PET_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await PetService(tenant).create(payload, principal, request_id=_rid(request)),
        "Pet registered.",
    )


@router.patch("/pets/{pet_id}", response_model=Envelope[PetRead], summary="Update a pet")
async def update_pet(
    pet_id: uuid.UUID,
    payload: PetUpdate,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.PET_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    return ok(
        await PetService(tenant).update(pet_id, payload, principal, request_id=_rid(request)),
        "Pet updated.",
    )


@router.delete("/pets/{pet_id}", response_model=Envelope[None], summary="Remove a pet")
async def remove_pet(
    pet_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.PET_MANAGE))],
    request: Request,
) -> dict[str, Any]:
    await PetService(tenant).remove(pet_id, principal, request_id=_rid(request))
    return ok(message="Pet removed.")


# --------------------------------------------------------------------------- #
# Dashboards
# --------------------------------------------------------------------------- #


@router.get(
    "/dashboard/resident",
    response_model=Envelope[ResidentDashboard],
    summary="Everything a resident's home screen needs",
)
async def resident_dashboard(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BILLING_READ))],
) -> dict[str, Any]:
    return ok(await ResidentDashboardService(tenant).build(principal))


@router.get(
    "/dashboard/utilities",
    response_model=Envelope[dict],
    summary="Society-wide utility and asset overview",
)
async def utility_dashboard(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.WATER_MANAGE))],
    months: Annotated[int, Query(ge=3, le=36)] = 12,
) -> dict[str, Any]:
    return ok(await SocietyUtilityDashboardService(tenant).build(months))
