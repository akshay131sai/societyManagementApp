"""Buildings, blocks, floors, flats and residents."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio


async def _create_building(
    client: AsyncClient, society: SocietyFixture, code: str | None = None
) -> dict[str, Any]:
    suffix = (code or uuid.uuid4().hex[:4]).upper()
    response = await client.post(
        "/buildings",
        headers=auth(society.admin_token),
        json={"name": f"Tower {suffix}", "code": suffix, "total_floors": 10},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest_asyncio.fixture
async def building(client: AsyncClient, society_a: SocietyFixture) -> dict[str, Any]:
    return await _create_building(client, society_a)


@pytest_asyncio.fixture
async def block(
    client: AsyncClient, society_a: SocietyFixture, building: dict[str, Any]
) -> dict[str, Any]:
    response = await client.get(
        "/blocks", headers=auth(society_a.admin_token), params={"building_id": building["id"]}
    )
    return response.json()["data"][0]


# --------------------------------------------------------------------------- #
# Buildings
# --------------------------------------------------------------------------- #


async def test_creating_a_building_seeds_a_default_block(
    client: AsyncClient, society_a: SocietyFixture, building: dict[str, Any]
) -> None:
    """A society with no wings still gets a uniform hierarchy."""
    assert building["block_count"] == 1

    blocks = await client.get(
        "/blocks", headers=auth(society_a.admin_token), params={"building_id": building["id"]}
    )
    seeded = blocks.json()["data"]
    assert len(seeded) == 1
    assert seeded[0]["code"] == "M"


async def test_duplicate_building_code_is_refused(
    client: AsyncClient, society_a: SocietyFixture, building: dict[str, Any]
) -> None:
    response = await client.post(
        "/buildings",
        headers=auth(society_a.admin_token),
        json={"name": "Clash", "code": building["code"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "ALREADY_EXISTS"


async def test_building_code_is_normalised_to_uppercase(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    code = uuid.uuid4().hex[:4]
    response = await client.post(
        "/buildings",
        headers=auth(society_a.admin_token),
        json={"name": "Lowercase", "code": code.lower()},
    )
    assert response.json()["data"]["code"] == code.upper()


async def test_building_with_flats_cannot_be_deleted(
    client: AsyncClient, society_a: SocietyFixture, building: dict[str, Any], block: dict[str, Any]
) -> None:
    """Deleting would cascade to flats, residents and eventually bills."""
    await client.post(
        "/flats/bulk",
        headers=auth(society_a.admin_token),
        json={
            "block_id": block["id"],
            "from_floor": 1,
            "to_floor": 1,
            "flats_per_floor": 1,
            "pattern": "{block}-{floor}{index:02d}",
            "area_sqft": 900,
        },
    )
    response = await client.delete(
        f"/buildings/{building['id']}", headers=auth(society_a.admin_token)
    )
    assert response.status_code == 409
    assert "flat" in response.json()["message"].lower()


async def test_empty_building_can_be_deleted(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    empty = await _create_building(client, society_a)
    response = await client.delete(
        f"/buildings/{empty['id']}", headers=auth(society_a.admin_token)
    )
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# Floors
# --------------------------------------------------------------------------- #


async def test_floor_range_creation(
    client: AsyncClient, society_a: SocietyFixture, block: dict[str, Any]
) -> None:
    response = await client.post(
        "/floors/range",
        headers=auth(society_a.admin_token),
        json={"block_id": block["id"], "from_number": 0, "to_number": 5},
    )
    assert response.status_code == 201
    assert response.json()["data"]["created"] == 6

    # Re-running must skip rather than duplicate.
    again = await client.post(
        "/floors/range",
        headers=auth(society_a.admin_token),
        json={"block_id": block["id"], "from_number": 0, "to_number": 5},
    )
    assert again.json()["data"]["created"] == 0
    assert again.json()["data"]["skipped"] == 6


async def test_ground_and_basement_floors_are_named_sensibly(
    client: AsyncClient, society_a: SocietyFixture, block: dict[str, Any]
) -> None:
    """Ground and basement floors are ordinary in Indian societies."""
    await client.post(
        "/floors/range",
        headers=auth(society_a.admin_token),
        json={"block_id": block["id"], "from_number": -2, "to_number": 2},
    )
    floors = await client.get(
        "/floors", headers=auth(society_a.admin_token), params={"block_id": block["id"]}
    )
    names = {f["number"]: f["display_name"] for f in floors.json()["data"]}
    assert names[0] == "Ground Floor"
    assert names[-1] == "Basement 1"
    assert names[-2] == "Basement 2"
    assert names[2] == "Floor 2"


async def test_duplicate_floor_number_in_a_block_is_refused(
    client: AsyncClient, society_a: SocietyFixture, block: dict[str, Any]
) -> None:
    body = {"block_id": block["id"], "number": 7}
    first = await client.post("/floors", headers=auth(society_a.admin_token), json=body)
    assert first.status_code == 201
    second = await client.post("/floors", headers=auth(society_a.admin_token), json=body)
    assert second.status_code == 409


# --------------------------------------------------------------------------- #
# Flats — bulk generation
# --------------------------------------------------------------------------- #


async def test_bulk_create_generates_the_expected_numbers(
    client: AsyncClient, society_a: SocietyFixture, block: dict[str, Any]
) -> None:
    response = await client.post(
        "/flats/bulk",
        headers=auth(society_a.admin_token),
        json={
            "block_id": block["id"],
            "from_floor": 1,
            "to_floor": 3,
            "flats_per_floor": 2,
            "pattern": "{block}-{floor}{index:02d}",
            "area_sqft": 1100,
            "flat_type": "2BHK",
        },
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["created"] == 6
    assert data["floors_created"] == 3
    assert data["preview"][0] == f"{block['code']}-101"
    assert f"{block['code']}-302" in data["preview"]


async def test_bulk_create_dry_run_writes_nothing(
    client: AsyncClient, society_a: SocietyFixture, block: dict[str, Any]
) -> None:
    body = {
        "block_id": block["id"],
        "from_floor": 1,
        "to_floor": 2,
        "flats_per_floor": 2,
        "pattern": "{block}-{floor}{index:02d}",
        "area_sqft": 1000,
        "dry_run": True,
    }
    response = await client.post("/flats/bulk", headers=auth(society_a.admin_token), json=body)
    assert response.json()["data"]["created"] == 0
    assert len(response.json()["data"]["preview"]) == 4

    flats = await client.get(
        "/flats", headers=auth(society_a.admin_token), params={"block_id": block["id"]}
    )
    assert flats.json()["data"]["total"] == 0


async def test_bulk_create_is_idempotent(
    client: AsyncClient, society_a: SocietyFixture, block: dict[str, Any]
) -> None:
    body = {
        "block_id": block["id"],
        "from_floor": 1,
        "to_floor": 2,
        "flats_per_floor": 3,
        "pattern": "{block}-{floor}{index:02d}",
        "area_sqft": 1000,
    }
    first = await client.post("/flats/bulk", headers=auth(society_a.admin_token), json=body)
    second = await client.post("/flats/bulk", headers=auth(society_a.admin_token), json=body)

    assert first.json()["data"]["created"] == 6
    assert second.json()["data"]["created"] == 0
    assert second.json()["data"]["skipped"] == 6


async def test_pattern_without_index_is_refused(
    client: AsyncClient, society_a: SocietyFixture, block: dict[str, Any]
) -> None:
    """Without {index} every flat on a floor would collide."""
    response = await client.post(
        "/flats/bulk",
        headers=auth(society_a.admin_token),
        json={
            "block_id": block["id"],
            "from_floor": 1,
            "to_floor": 2,
            "flats_per_floor": 2,
            "pattern": "{block}-{floor}",
            "area_sqft": 900,
        },
    )
    assert response.status_code == 422


async def test_pattern_rejects_unknown_placeholders(
    client: AsyncClient, society_a: SocietyFixture, block: dict[str, Any]
) -> None:
    """str.format on user input would reach attributes; only four keys are allowed."""
    response = await client.post(
        "/flats/bulk",
        headers=auth(society_a.admin_token),
        json={
            "block_id": block["id"],
            "from_floor": 1,
            "to_floor": 1,
            "flats_per_floor": 1,
            "pattern": "{block.__class__}-{index}",
            "area_sqft": 900,
        },
    )
    assert response.status_code == 422


async def test_bulk_create_respects_its_ceiling(
    client: AsyncClient, society_a: SocietyFixture, block: dict[str, Any]
) -> None:
    response = await client.post(
        "/flats/bulk",
        headers=auth(society_a.admin_token),
        json={
            "block_id": block["id"],
            "from_floor": 1,
            "to_floor": 100,
            "flats_per_floor": 50,
            "pattern": "{block}-{floor}{index:02d}",
            "area_sqft": 900,
        },
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Flats — the denormalisation trigger
# --------------------------------------------------------------------------- #


async def test_flat_parents_are_derived_from_the_floor(
    client: AsyncClient, society_a: SocietyFixture, building: dict[str, Any], block: dict[str, Any]
) -> None:
    floor = await client.post(
        "/floors", headers=auth(society_a.admin_token), json={"block_id": block["id"], "number": 4}
    )
    floor_id = floor.json()["data"]["id"]

    created = await client.post(
        "/flats",
        headers=auth(society_a.admin_token),
        json={"floor_id": floor_id, "flat_number": f"{block['code']}-401", "area_sqft": 1250},
    )
    flat = created.json()["data"]
    assert flat["block_id"] == block["id"]
    assert flat["building_id"] == building["id"]


async def test_moving_a_flat_updates_its_derived_parents(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    """A flat moved to another building must not still report the old one."""
    a = await _create_building(client, society_a)
    b = await _create_building(client, society_a)

    blocks_a = (
        await client.get(
            "/blocks", headers=auth(society_a.admin_token), params={"building_id": a["id"]}
        )
    ).json()["data"]
    blocks_b = (
        await client.get(
            "/blocks", headers=auth(society_a.admin_token), params={"building_id": b["id"]}
        )
    ).json()["data"]

    floor_a = (
        await client.post(
            "/floors",
            headers=auth(society_a.admin_token),
            json={"block_id": blocks_a[0]["id"], "number": 1},
        )
    ).json()["data"]
    floor_b = (
        await client.post(
            "/floors",
            headers=auth(society_a.admin_token),
            json={"block_id": blocks_b[0]["id"], "number": 1},
        )
    ).json()["data"]

    flat = (
        await client.post(
            "/flats",
            headers=auth(society_a.admin_token),
            json={
                "floor_id": floor_a["id"],
                "flat_number": f"MOVE-{uuid.uuid4().hex[:6]}",
                "area_sqft": 800,
            },
        )
    ).json()["data"]
    assert flat["building_id"] == a["id"]

    moved = await client.patch(
        f"/flats/{flat['id']}",
        headers=auth(society_a.admin_token),
        json={"floor_id": floor_b["id"]},
    )
    assert moved.json()["data"]["building_id"] == b["id"]
    assert moved.json()["data"]["block_id"] == blocks_b[0]["id"]


async def test_duplicate_flat_number_is_refused(
    client: AsyncClient, society_a: SocietyFixture, block: dict[str, Any]
) -> None:
    floor = (
        await client.post(
            "/floors",
            headers=auth(society_a.admin_token),
            json={"block_id": block["id"], "number": 9},
        )
    ).json()["data"]
    number = f"DUP-{uuid.uuid4().hex[:6]}"
    body = {"floor_id": floor["id"], "flat_number": number, "area_sqft": 1000}

    assert (
        await client.post("/flats", headers=auth(society_a.admin_token), json=body)
    ).status_code == 201
    assert (
        await client.post("/flats", headers=auth(society_a.admin_token), json=body)
    ).status_code == 409


@pytest.mark.parametrize(
    "payload,reason",
    [
        ({"area_sqft": 0}, "zero area"),
        ({"area_sqft": -5}, "negative area"),
        ({"area_sqft": 900, "carpet_area_sqft": 1200}, "carpet larger than built-up"),
    ],
)
async def test_flat_area_validation(
    client: AsyncClient,
    society_a: SocietyFixture,
    block: dict[str, Any],
    payload: dict[str, Any],
    reason: str,
) -> None:
    floor = (
        await client.post(
            "/floors",
            headers=auth(society_a.admin_token),
            json={"block_id": block["id"], "number": 11},
        )
    ).json()["data"]
    response = await client.post(
        "/flats",
        headers=auth(society_a.admin_token),
        json={"floor_id": floor["id"], "flat_number": f"BAD-{uuid.uuid4().hex[:6]}", **payload},
    )
    assert response.status_code == 422, reason


# --------------------------------------------------------------------------- #
# Residents
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def flat(
    client: AsyncClient, society_a: SocietyFixture, block: dict[str, Any]
) -> dict[str, Any]:
    floor = (
        await client.post(
            "/floors",
            headers=auth(society_a.admin_token),
            json={"block_id": block["id"], "number": 6},
        )
    ).json()["data"]
    created = await client.post(
        "/flats",
        headers=auth(society_a.admin_token),
        json={
            "floor_id": floor["id"],
            "flat_number": f"R-{uuid.uuid4().hex[:6]}",
            "area_sqft": 1150,
            "flat_type": "2BHK",
        },
    )
    return created.json()["data"]


async def test_occupancy_is_derived_from_who_lives_there(
    client: AsyncClient, society_a: SocietyFixture, flat: dict[str, Any]
) -> None:
    """A billing formula branches on occupancy, so it must not be a stale field."""
    assert flat["occupancy_status"] == "VACANT"

    owner = await client.post(
        "/residents",
        headers=auth(society_a.admin_token),
        json={
            "flat_id": flat["id"],
            "full_name": "Owner Person",
            "resident_type": "OWNER",
            "is_primary": True,
        },
    )
    assert owner.status_code == 201
    detail = await client.get(f"/flats/{flat['id']}", headers=auth(society_a.admin_token))
    assert detail.json()["data"]["occupancy_status"] == "OWNER_OCCUPIED"

    await client.post(
        "/residents",
        headers=auth(society_a.admin_token),
        json={"flat_id": flat["id"], "full_name": "Tenant Person", "resident_type": "TENANT"},
    )
    detail = await client.get(f"/flats/{flat['id']}", headers=auth(society_a.admin_token))
    assert detail.json()["data"]["occupancy_status"] == "RENTED"

    residents = await client.get(
        "/residents", headers=auth(society_a.admin_token), params={"flat_id": flat["id"]}
    )
    for resident in residents.json()["data"]["items"]:
        await client.delete(f"/residents/{resident['id']}", headers=auth(society_a.admin_token))

    detail = await client.get(f"/flats/{flat['id']}", headers=auth(society_a.admin_token))
    assert detail.json()["data"]["occupancy_status"] == "VACANT"


async def test_only_one_primary_resident_per_flat(
    client: AsyncClient, society_a: SocietyFixture, flat: dict[str, Any]
) -> None:
    """Enforced by a partial unique index, not by convention."""
    for name in ("First Primary", "Second Primary", "Third Primary"):
        response = await client.post(
            "/residents",
            headers=auth(society_a.admin_token),
            json={
                "flat_id": flat["id"],
                "full_name": name,
                "resident_type": "OWNER",
                "is_primary": True,
            },
        )
        assert response.status_code == 201, response.text

    residents = await client.get(
        "/residents", headers=auth(society_a.admin_token), params={"flat_id": flat["id"]}
    )
    items = residents.json()["data"]["items"]
    assert sum(1 for r in items if r["is_primary"]) == 1
    assert next(r for r in items if r["is_primary"])["full_name"] == "Third Primary"


async def test_flat_with_residents_cannot_be_deleted(
    client: AsyncClient, society_a: SocietyFixture, flat: dict[str, Any]
) -> None:
    await client.post(
        "/residents",
        headers=auth(society_a.admin_token),
        json={"flat_id": flat["id"], "full_name": "Someone", "resident_type": "OWNER"},
    )
    response = await client.delete(f"/flats/{flat['id']}", headers=auth(society_a.admin_token))
    assert response.status_code == 409


async def test_move_out_date_cannot_precede_move_in(
    client: AsyncClient, society_a: SocietyFixture, flat: dict[str, Any]
) -> None:
    response = await client.post(
        "/residents",
        headers=auth(society_a.admin_token),
        json={
            "flat_id": flat["id"],
            "full_name": "Time Traveller",
            "resident_type": "TENANT",
            "move_in_date": "2025-06-01",
            "move_out_date": "2024-01-01",
        },
    )
    assert response.status_code == 422


async def test_family_members(
    client: AsyncClient, society_a: SocietyFixture, flat: dict[str, Any]
) -> None:
    resident = (
        await client.post(
            "/residents",
            headers=auth(society_a.admin_token),
            json={"flat_id": flat["id"], "full_name": "Parent", "resident_type": "OWNER"},
        )
    ).json()["data"]

    created = await client.post(
        "/family-members",
        headers=auth(society_a.admin_token),
        json={
            "resident_id": resident["id"],
            "full_name": "Child One",
            "relationship_to_resident": "DAUGHTER",
            "date_of_birth": "2015-04-12",
        },
    )
    assert created.status_code == 201
    assert created.json()["data"]["access_level"] == "NONE"
    assert created.json()["data"]["has_login"] is False

    # Free text is no longer a relationship.
    rejected = await client.post(
        "/family-members",
        headers=auth(society_a.admin_token),
        json={
            "resident_id": resident["id"],
            "full_name": "Child Two",
            "relationship_to_resident": "second cousin",
        },
    )
    assert rejected.status_code == 422

    listed = await client.get(
        f"/residents/{resident['id']}/family", headers=auth(society_a.admin_token)
    )
    assert len(listed.json()["data"]) == 1

    detail = await client.get(
        f"/residents/{resident['id']}", headers=auth(society_a.admin_token)
    )
    assert detail.json()["data"]["family_members"][0]["full_name"] == "Child One"


# --------------------------------------------------------------------------- #
# Structure overview
# --------------------------------------------------------------------------- #


async def test_summary_and_tree(
    client: AsyncClient, society_a: SocietyFixture, building: dict[str, Any], block: dict[str, Any]
) -> None:
    await client.post(
        "/flats/bulk",
        headers=auth(society_a.admin_token),
        json={
            "block_id": block["id"],
            "from_floor": 1,
            "to_floor": 2,
            "flats_per_floor": 2,
            "pattern": "{block}-{floor}{index:02d}",
            "area_sqft": 1000,
        },
    )

    summary = (
        await client.get("/structure/summary", headers=auth(society_a.admin_token))
    ).json()["data"]
    assert summary["flats"] >= 4
    assert summary["total_area_sqft"] > 0
    assert "VACANT" in summary["occupancy"]

    tree = (await client.get("/structure/tree", headers=auth(society_a.admin_token))).json()["data"]
    node = next(n for n in tree if n["id"] == building["id"])
    assert node["kind"] == "building"
    assert node["children"][0]["kind"] == "block"
    assert node["children"][0]["children"][0]["kind"] == "floor"
    assert node["flat_count"] >= 4
