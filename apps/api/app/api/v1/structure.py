"""Structure and resident endpoints.

Every route operates on the caller's own tenant session. There is no society
parameter anywhere in this module — by construction.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CentralSession, TenantSession, require_permission
from app.auth.principal import Principal
from app.core.permissions import Permission
from app.models.tenant import OccupancyStatus
from app.repositories.structure import FlatRepository
from app.schemas.common import Envelope, Page, PageParams, ok
from app.schemas.structure import (
    BlockCreate,
    BlockRead,
    BlockUpdate,
    BuildingCreate,
    BuildingRead,
    BuildingUpdate,
    FamilyAccessGrant,
    FamilyMemberCreate,
    FamilyMemberRead,
    FamilyMemberUpdate,
    FlatBulkCreate,
    FlatBulkResult,
    FlatCreate,
    FlatDetail,
    FlatRead,
    FlatUpdate,
    FloorCreate,
    FloorRangeCreate,
    FloorRead,
    FloorUpdate,
    ResidentCreate,
    ResidentDetail,
    ResidentRead,
    ResidentUpdate,
    StructureSummary,
    StructureTreeNode,
)
from app.services.structure import (
    BlockService,
    BuildingService,
    FamilyMemberService,
    FlatService,
    FloorService,
    ResidentService,
    StructureOverviewService,
    sync_flat_count,
)

router = APIRouter(tags=["structure"])

PageDep = Annotated[PageParams, Depends()]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def _refresh_flat_count(tenant: TenantSession, principal: Principal) -> None:
    """Keep the central display counter in step with the tenant's real count."""
    if principal.society_id is not None:
        await sync_flat_count(principal.society_id, await FlatRepository(tenant).count())


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #


@router.get(
    "/structure/summary",
    response_model=Envelope[StructureSummary],
    summary="Structure totals",
)
async def structure_summary(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BUILDING_READ))],
) -> dict[str, Any]:
    return ok(await StructureOverviewService(tenant).summary())


@router.get(
    "/structure/tree",
    response_model=Envelope[list[StructureTreeNode]],
    summary="Building → block → floor hierarchy",
)
async def structure_tree(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BUILDING_READ))],
) -> dict[str, Any]:
    return ok(await StructureOverviewService(tenant).tree())


# --------------------------------------------------------------------------- #
# Buildings
# --------------------------------------------------------------------------- #


@router.get("/buildings", response_model=Envelope[list[BuildingRead]], summary="List buildings")
async def list_buildings(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BUILDING_READ))],
    include_inactive: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    return ok(await BuildingService(tenant).list(include_inactive=include_inactive))


@router.post(
    "/buildings",
    response_model=Envelope[BuildingRead],
    status_code=201,
    summary="Create a building",
    description="Also seeds a default 'Main' block so the flat hierarchy is uniform.",
)
async def create_building(
    body: BuildingCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BUILDING_MANAGE))],
) -> dict[str, Any]:
    building = await BuildingService(tenant).create(body, principal, request_id=_rid(request))
    return ok(building, message="Building created.")


@router.get(
    "/buildings/{building_id}", response_model=Envelope[BuildingRead], summary="Building detail"
)
async def get_building(
    building_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BUILDING_READ))],
) -> dict[str, Any]:
    return ok(await BuildingService(tenant).get(building_id))


@router.patch(
    "/buildings/{building_id}", response_model=Envelope[BuildingRead], summary="Update a building"
)
async def update_building(
    building_id: uuid.UUID,
    body: BuildingUpdate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BUILDING_MANAGE))],
) -> dict[str, Any]:
    building = await BuildingService(tenant).update(
        building_id, body, principal, request_id=_rid(request)
    )
    return ok(building, message="Building updated.")


@router.delete(
    "/buildings/{building_id}", response_model=Envelope[dict], summary="Delete a building"
)
async def delete_building(
    building_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BUILDING_MANAGE))],
) -> dict[str, Any]:
    await BuildingService(tenant).delete(building_id, principal, request_id=_rid(request))
    return ok({"deleted": True}, message="Building deleted.")


# --------------------------------------------------------------------------- #
# Blocks
# --------------------------------------------------------------------------- #


@router.get("/blocks", response_model=Envelope[list[BlockRead]], summary="List blocks")
async def list_blocks(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BLOCK_READ))],
    building_id: Annotated[uuid.UUID | None, Query()] = None,
    include_inactive: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    return ok(
        await BlockService(tenant).list(
            building_id=building_id, include_inactive=include_inactive
        )
    )


@router.post(
    "/blocks", response_model=Envelope[BlockRead], status_code=201, summary="Create a block"
)
async def create_block(
    body: BlockCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BLOCK_MANAGE))],
) -> dict[str, Any]:
    return ok(
        await BlockService(tenant).create(body, principal, request_id=_rid(request)),
        message="Block created.",
    )


@router.get("/blocks/{block_id}", response_model=Envelope[BlockRead], summary="Block detail")
async def get_block(
    block_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BLOCK_READ))],
) -> dict[str, Any]:
    return ok(await BlockService(tenant).get(block_id))


@router.patch("/blocks/{block_id}", response_model=Envelope[BlockRead], summary="Update a block")
async def update_block(
    block_id: uuid.UUID,
    body: BlockUpdate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BLOCK_MANAGE))],
) -> dict[str, Any]:
    return ok(
        await BlockService(tenant).update(block_id, body, principal, request_id=_rid(request)),
        message="Block updated.",
    )


@router.delete("/blocks/{block_id}", response_model=Envelope[dict], summary="Delete a block")
async def delete_block(
    block_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.BLOCK_MANAGE))],
) -> dict[str, Any]:
    await BlockService(tenant).delete(block_id, principal, request_id=_rid(request))
    return ok({"deleted": True}, message="Block deleted.")


# --------------------------------------------------------------------------- #
# Floors
# --------------------------------------------------------------------------- #


@router.get("/floors", response_model=Envelope[list[FloorRead]], summary="List floors")
async def list_floors(
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FLOOR_READ))],
    block_id: Annotated[uuid.UUID | None, Query()] = None,
    building_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    return ok(await FloorService(tenant).list(block_id=block_id, building_id=building_id))


@router.post(
    "/floors", response_model=Envelope[FloorRead], status_code=201, summary="Create a floor"
)
async def create_floor(
    body: FloorCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FLOOR_MANAGE))],
) -> dict[str, Any]:
    return ok(
        await FloorService(tenant).create(body, principal, request_id=_rid(request)),
        message="Floor created.",
    )


@router.post(
    "/floors/range",
    response_model=Envelope[dict],
    status_code=201,
    summary="Create a range of floors",
    description="Creates every floor between from_number and to_number, skipping any that exist.",
)
async def create_floor_range(
    body: FloorRangeCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FLOOR_MANAGE))],
) -> dict[str, Any]:
    result = await FloorService(tenant).create_range(body, principal, request_id=_rid(request))
    return ok(result, message=f"{result['created']} floor(s) created.")


@router.get("/floors/{floor_id}", response_model=Envelope[FloorRead], summary="Floor detail")
async def get_floor(
    floor_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FLOOR_READ))],
) -> dict[str, Any]:
    return ok(await FloorService(tenant).get(floor_id))


@router.patch("/floors/{floor_id}", response_model=Envelope[FloorRead], summary="Update a floor")
async def update_floor(
    floor_id: uuid.UUID,
    body: FloorUpdate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FLOOR_MANAGE))],
) -> dict[str, Any]:
    return ok(
        await FloorService(tenant).update(floor_id, body, principal, request_id=_rid(request)),
        message="Floor updated.",
    )


@router.delete("/floors/{floor_id}", response_model=Envelope[dict], summary="Delete a floor")
async def delete_floor(
    floor_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FLOOR_MANAGE))],
) -> dict[str, Any]:
    await FloorService(tenant).delete(floor_id, principal, request_id=_rid(request))
    return ok({"deleted": True}, message="Floor deleted.")


# --------------------------------------------------------------------------- #
# Flats
# --------------------------------------------------------------------------- #


@router.get(
    "/flats",
    response_model=Envelope[Page[FlatRead]],
    summary="List flats",
    description=(
        "A principal whose flat.read is owner-scoped sees only their own flats. "
        "The narrowing happens in the service, not the router."
    ),
)
async def list_flats(
    tenant: TenantSession,
    params: PageDep,
    principal: Annotated[Principal, Depends(require_permission(Permission.FLAT_READ))],
    building_id: Annotated[uuid.UUID | None, Query()] = None,
    block_id: Annotated[uuid.UUID | None, Query()] = None,
    floor_id: Annotated[uuid.UUID | None, Query()] = None,
    occupancy_status: Annotated[OccupancyStatus | None, Query()] = None,
    flat_type: Annotated[str | None, Query(max_length=20)] = None,
) -> dict[str, Any]:
    rows, total = await FlatService(tenant).list(
        principal,
        page=params.page,
        limit=params.limit,
        q=params.q,
        building_id=building_id,
        block_id=block_id,
        floor_id=floor_id,
        occupancy_status=occupancy_status,
        flat_type=flat_type,
    )
    return ok(Page.build(rows, page=params.page, limit=params.limit, total=total))


@router.post(
    "/flats", response_model=Envelope[FlatDetail], status_code=201, summary="Create a flat"
)
async def create_flat(
    body: FlatCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FLAT_MANAGE))],
) -> dict[str, Any]:
    flat = await FlatService(tenant).create(body, principal, request_id=_rid(request))
    await _refresh_flat_count(tenant, principal)
    return ok(flat, message="Flat created.")


@router.post(
    "/flats/bulk",
    response_model=Envelope[FlatBulkResult],
    status_code=201,
    summary="Generate flats from a numbering pattern",
    description=(
        "Creates a block's flats in one call — the alternative is hundreds of "
        "individual POSTs when onboarding a society. Pass dry_run to preview "
        "the generated numbers and any conflicts without writing."
    ),
)
async def bulk_create_flats(
    body: FlatBulkCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FLAT_MANAGE))],
) -> dict[str, Any]:
    result = await FlatService(tenant).bulk_create(body, principal, request_id=_rid(request))
    if not result["dry_run"]:
        await _refresh_flat_count(tenant, principal)
    message = (
        f"Preview: {len(result['preview'])} flat number(s) generated."
        if result["dry_run"]
        else f"{result['created']} flat(s) created."
    )
    return ok(result, message=message)


@router.get("/flats/{flat_id}", response_model=Envelope[FlatDetail], summary="Flat detail")
async def get_flat(
    flat_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FLAT_READ))],
) -> dict[str, Any]:
    return ok(await FlatService(tenant).get(flat_id, principal))


@router.patch("/flats/{flat_id}", response_model=Envelope[FlatDetail], summary="Update a flat")
async def update_flat(
    flat_id: uuid.UUID,
    body: FlatUpdate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FLAT_MANAGE))],
) -> dict[str, Any]:
    flat = await FlatService(tenant).update(flat_id, body, principal, request_id=_rid(request))
    await _refresh_flat_count(tenant, principal)
    return ok(flat, message="Flat updated.")


@router.delete("/flats/{flat_id}", response_model=Envelope[dict], summary="Delete a flat")
async def delete_flat(
    flat_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FLAT_MANAGE))],
) -> dict[str, Any]:
    await FlatService(tenant).delete(flat_id, principal, request_id=_rid(request))
    await _refresh_flat_count(tenant, principal)
    return ok({"deleted": True}, message="Flat deleted.")


# --------------------------------------------------------------------------- #
# Residents
# --------------------------------------------------------------------------- #


@router.get("/residents", response_model=Envelope[Page[ResidentRead]], summary="List residents")
async def list_residents(
    tenant: TenantSession,
    params: PageDep,
    principal: Annotated[Principal, Depends(require_permission(Permission.RESIDENT_READ))],
    flat_id: Annotated[uuid.UUID | None, Query()] = None,
    building_id: Annotated[uuid.UUID | None, Query()] = None,
    resident_type: Annotated[str | None, Query(pattern=r"^(OWNER|TENANT)$")] = None,
) -> dict[str, Any]:
    rows, total = await ResidentService(tenant).list(
        principal,
        page=params.page,
        limit=params.limit,
        q=params.q,
        flat_id=flat_id,
        building_id=building_id,
        resident_type=resident_type,
    )
    return ok(Page.build(rows, page=params.page, limit=params.limit, total=total))


@router.post(
    "/residents",
    response_model=Envelope[ResidentDetail],
    status_code=201,
    summary="Add a resident",
)
async def create_resident(
    body: ResidentCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.RESIDENT_MANAGE))],
) -> dict[str, Any]:
    return ok(
        await ResidentService(tenant).create(body, principal, request_id=_rid(request)),
        message="Resident added.",
    )


@router.get(
    "/residents/{resident_id}", response_model=Envelope[ResidentDetail], summary="Resident detail"
)
async def get_resident(
    resident_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.RESIDENT_READ))],
) -> dict[str, Any]:
    return ok(await ResidentService(tenant).get(resident_id, principal))


@router.patch(
    "/residents/{resident_id}",
    response_model=Envelope[ResidentDetail],
    summary="Update a resident",
)
async def update_resident(
    resident_id: uuid.UUID,
    body: ResidentUpdate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.RESIDENT_MANAGE))],
) -> dict[str, Any]:
    return ok(
        await ResidentService(tenant).update(
            resident_id, body, principal, request_id=_rid(request)
        ),
        message="Resident updated.",
    )


@router.delete(
    "/residents/{resident_id}", response_model=Envelope[dict], summary="Remove a resident"
)
async def delete_resident(
    resident_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.RESIDENT_MANAGE))],
) -> dict[str, Any]:
    await ResidentService(tenant).delete(resident_id, principal, request_id=_rid(request))
    return ok({"deleted": True}, message="Resident removed.")


# --------------------------------------------------------------------------- #
# Family members
# --------------------------------------------------------------------------- #


@router.get(
    "/residents/{resident_id}/family",
    response_model=Envelope[list[FamilyMemberRead]],
    summary="A resident's family members",
)
async def list_family(
    resident_id: uuid.UUID,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.RESIDENT_READ))],
) -> dict[str, Any]:
    return ok(await FamilyMemberService(tenant).list(resident_id, principal))


@router.post(
    "/family-members",
    response_model=Envelope[FamilyMemberRead],
    status_code=201,
    summary="Add a family member",
)
async def create_family_member(
    body: FamilyMemberCreate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FAMILY_MANAGE))],
) -> dict[str, Any]:
    return ok(
        await FamilyMemberService(tenant).create(body, principal, request_id=_rid(request)),
        message="Family member added.",
    )


@router.patch(
    "/family-members/{member_id}",
    response_model=Envelope[FamilyMemberRead],
    summary="Update a family member",
)
async def update_family_member(
    member_id: uuid.UUID,
    body: FamilyMemberUpdate,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FAMILY_MANAGE))],
) -> dict[str, Any]:
    return ok(
        await FamilyMemberService(tenant).update(
            member_id, body, principal, request_id=_rid(request)
        ),
        message="Family member updated.",
    )


@router.delete(
    "/family-members/{member_id}",
    response_model=Envelope[dict],
    summary="Remove a family member",
)
async def delete_family_member(
    member_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FAMILY_MANAGE))],
) -> dict[str, Any]:
    await FamilyMemberService(tenant).delete(member_id, principal, request_id=_rid(request))
    return ok({"deleted": True}, message="Family member removed.")


@router.post(
    "/family-members/{member_id}/access",
    response_model=Envelope[FamilyMemberRead],
    summary="Grant a family member app access",
    description=(
        "Creates the tenant user *and* the matching central platform_users row "
        "so the account can authenticate, then assigns the role for the chosen "
        "tier. Re-posting with a different tier moves an existing login.\n\n"
        "No password is handled here. The account is created with a `pending:` "
        "placeholder that is bound to a real identity on first sign-in."
    ),
)
async def grant_family_access(
    member_id: uuid.UUID,
    body: FamilyAccessGrant,
    request: Request,
    tenant: TenantSession,
    central: CentralSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FAMILY_MANAGE))],
) -> dict[str, Any]:
    from app.models.central import PlatformUser
    from app.repositories.central import PlatformUserRepository

    member = await FamilyMemberService(tenant).grant_access(
        member_id,
        body.access_level,
        principal,
        email=str(body.email) if body.email else None,
        request_id=_rid(request),
    )

    # The central row is what makes this account resolvable at sign-in. Same
    # split as create_user in society.py: different database, different session.
    repo = PlatformUserRepository(central)
    existing = await repo.get_by_email_in_society(member["email"], principal.society_id)
    if existing is None:
        await repo.create(
            PlatformUser(
                firebase_uid=f"pending:{member['email']}",
                email=member["email"],
                phone=member.get("phone"),
                display_name=member["full_name"],
                is_super_admin=False,
                society_id=principal.society_id,
                tenant_user_id=member["user_id"],
                is_active=True,
            )
        )
    else:
        existing.tenant_user_id = member["user_id"]
        existing.is_active = True

    return ok(member, message="App access granted.")


@router.delete(
    "/family-members/{member_id}/access",
    response_model=Envelope[FamilyMemberRead],
    summary="Revoke a family member's app access",
    description=(
        "Deactivates the login and clears the tier, but keeps the person on the "
        "household roster so audit history stays attributable."
    ),
)
async def revoke_family_access(
    member_id: uuid.UUID,
    request: Request,
    tenant: TenantSession,
    central: CentralSession,
    principal: Annotated[Principal, Depends(require_permission(Permission.FAMILY_MANAGE))],
) -> dict[str, Any]:
    from app.repositories.central import PlatformUserRepository

    # revoke_access keeps the address on the roster row, so it is still there
    # to locate the central account that has to be deactivated with it.
    member = await FamilyMemberService(tenant).revoke_access(
        member_id, principal, request_id=_rid(request)
    )
    email = member.get("email")

    if email:
        existing = await PlatformUserRepository(central).get_by_email_in_society(
            email, principal.society_id
        )
        if existing is not None:
            existing.is_active = False

    return ok(member, message="App access revoked.")
