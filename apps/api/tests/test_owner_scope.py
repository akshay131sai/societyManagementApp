"""Owner scoping and Phase 2 tenant isolation.

Phase 2 introduces the first records a resident may see *some* of. Two distinct
properties are tested here:

* **Tenant isolation** — Society A cannot see Society B's structure at all.
* **Owner scoping** — inside one society, a FLAT_OWNER sees only their own
  flats, even though they hold ``flat.read``.

Getting the second wrong leaks a neighbour's data to every resident, so it is
tested as carefully as the first.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio


class ScopedSociety:
    """A society with two flats: one owned by a resident, one by a neighbour."""

    def __init__(self) -> None:
        self.building: dict[str, Any] = {}
        self.block: dict[str, Any] = {}
        self.own_flat: dict[str, Any] = {}
        self.other_flat: dict[str, Any] = {}
        self.resident_token: str = ""
        self.own_resident: dict[str, Any] = {}
        self.other_resident: dict[str, Any] = {}


@pytest_asyncio.fixture(scope="module")
async def scoped(client: AsyncClient, society_a: SocietyFixture) -> ScopedSociety:
    admin = auth(society_a.admin_token)
    fixture = ScopedSociety()
    tag = uuid.uuid4().hex[:5].upper()

    fixture.building = (
        await client.post(
            "/buildings", headers=admin, json={"name": f"Scope {tag}", "code": tag}
        )
    ).json()["data"]

    fixture.block = (
        await client.get(
            "/blocks", headers=admin, params={"building_id": fixture.building["id"]}
        )
    ).json()["data"][0]

    floor = (
        await client.post(
            "/floors", headers=admin, json={"block_id": fixture.block["id"], "number": 1}
        )
    ).json()["data"]

    for label in ("own", "other"):
        flat = (
            await client.post(
                "/flats",
                headers=admin,
                json={
                    "floor_id": floor["id"],
                    "flat_number": f"{tag}-{label}",
                    "area_sqft": 1000,
                },
            )
        ).json()["data"]
        setattr(fixture, f"{label}_flat", flat)

    # A society login that will be linked to one flat only.
    email = f"scoped-{tag.lower()}@test.nestflow.in"
    user = (
        await client.post(
            "/users",
            headers=admin,
            json={"email": email, "full_name": "Scoped Resident", "role_codes": ["FLAT_OWNER"]},
        )
    ).json()["data"]
    fixture.resident_token = f"dev:{email}"

    fixture.own_resident = (
        await client.post(
            "/residents",
            headers=admin,
            json={
                "flat_id": fixture.own_flat["id"],
                "full_name": "Scoped Resident",
                "resident_type": "OWNER",
                "is_primary": True,
                "user_id": user["id"],
            },
        )
    ).json()["data"]

    fixture.other_resident = (
        await client.post(
            "/residents",
            headers=admin,
            json={
                "flat_id": fixture.other_flat["id"],
                "full_name": "Neighbour Resident",
                "resident_type": "OWNER",
                "is_primary": True,
            },
        )
    ).json()["data"]

    return fixture


# --------------------------------------------------------------------------- #
# flat_ids resolution
# --------------------------------------------------------------------------- #


async def test_principal_flat_ids_come_from_the_residents_table(
    client: AsyncClient, scoped: ScopedSociety
) -> None:
    me = await client.get("/auth/me", headers=auth(scoped.resident_token))
    assert me.status_code == 200
    principal = me.json()["data"]["principal"]

    assert principal["roles"] == ["FLAT_OWNER"]
    assert principal["flat_ids"] == [scoped.own_flat["id"]]


async def test_flat_ids_update_when_a_resident_is_deactivated(
    client: AsyncClient, society_a: SocietyFixture, scoped: ScopedSociety
) -> None:
    """Authorization is re-resolved per request, so a move-out takes effect at once."""
    admin = auth(society_a.admin_token)

    await client.patch(
        f"/residents/{scoped.own_resident['id']}", headers=admin, json={"is_active": False}
    )
    me = await client.get("/auth/me", headers=auth(scoped.resident_token))
    assert me.json()["data"]["principal"]["flat_ids"] == []

    flats = await client.get("/flats", headers=auth(scoped.resident_token))
    assert flats.json()["data"]["total"] == 0

    await client.patch(
        f"/residents/{scoped.own_resident['id']}", headers=admin, json={"is_active": True}
    )
    me = await client.get("/auth/me", headers=auth(scoped.resident_token))
    assert me.json()["data"]["principal"]["flat_ids"] == [scoped.own_flat["id"]]


# --------------------------------------------------------------------------- #
# Flats
# --------------------------------------------------------------------------- #


async def test_resident_sees_only_their_own_flat(
    client: AsyncClient, society_a: SocietyFixture, scoped: ScopedSociety
) -> None:
    admin_view = await client.get(
        "/flats", headers=auth(society_a.admin_token), params={"limit": 1}
    )
    resident_view = await client.get(
        "/flats", headers=auth(scoped.resident_token), params={"limit": 100}
    )

    assert admin_view.json()["data"]["total"] > 1
    assert resident_view.json()["data"]["total"] == 1
    assert resident_view.json()["data"]["items"][0]["id"] == scoped.own_flat["id"]


async def test_resident_reading_a_neighbours_flat_gets_404_not_403(
    client: AsyncClient, scoped: ScopedSociety
) -> None:
    """404, so a scoped principal cannot confirm the record exists."""
    response = await client.get(
        f"/flats/{scoped.other_flat['id']}", headers=auth(scoped.resident_token)
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_resident_can_read_their_own_flat(
    client: AsyncClient, scoped: ScopedSociety
) -> None:
    response = await client.get(
        f"/flats/{scoped.own_flat['id']}", headers=auth(scoped.resident_token)
    )
    assert response.status_code == 200
    assert response.json()["data"]["id"] == scoped.own_flat["id"]


async def test_filters_cannot_widen_the_owner_scope(
    client: AsyncClient, scoped: ScopedSociety
) -> None:
    """A filter narrows; it must never be able to broaden."""
    for params in (
        {"building_id": scoped.building["id"]},
        {"block_id": scoped.block["id"]},
        {"floor_id": scoped.own_flat["floor_id"]},
        {"q": ""},
        {"limit": 100},
    ):
        response = await client.get(
            "/flats", headers=auth(scoped.resident_token), params={**params, "limit": 100}
        )
        ids = {f["id"] for f in response.json()["data"]["items"]}
        assert ids <= {scoped.own_flat["id"]}, params


# --------------------------------------------------------------------------- #
# Residents
# --------------------------------------------------------------------------- #


async def test_resident_sees_only_their_own_flats_residents(
    client: AsyncClient, society_a: SocietyFixture, scoped: ScopedSociety
) -> None:
    admin_view = await client.get(
        "/residents", headers=auth(society_a.admin_token), params={"limit": 1}
    )
    resident_view = await client.get(
        "/residents", headers=auth(scoped.resident_token), params={"limit": 100}
    )

    names = {r["full_name"] for r in resident_view.json()["data"]["items"]}
    assert admin_view.json()["data"]["total"] > resident_view.json()["data"]["total"]
    assert "Neighbour Resident" not in names
    assert "Scoped Resident" in names


async def test_resident_reading_a_neighbour_record_gets_404(
    client: AsyncClient, scoped: ScopedSociety
) -> None:
    response = await client.get(
        f"/residents/{scoped.other_resident['id']}", headers=auth(scoped.resident_token)
    )
    assert response.status_code == 404


async def test_resident_cannot_see_a_neighbours_family(
    client: AsyncClient, society_a: SocietyFixture, scoped: ScopedSociety
) -> None:
    await client.post(
        "/family-members",
        headers=auth(society_a.admin_token),
        json={
            "resident_id": scoped.other_resident["id"],
            "full_name": "Neighbour Child",
            "relationship_to_resident": "Son",
        },
    )
    response = await client.get(
        f"/residents/{scoped.other_resident['id']}/family",
        headers=auth(scoped.resident_token),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "RESOURCE_FORBIDDEN"


# --------------------------------------------------------------------------- #
# Write permissions
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/buildings", {"name": "Rogue", "code": "RG"}),
        ("post", "/blocks", {"building_id": str(uuid.uuid4()), "name": "R", "code": "R"}),
        ("post", "/floors", {"block_id": str(uuid.uuid4()), "number": 1}),
        ("post", "/flats", {"floor_id": str(uuid.uuid4()), "flat_number": "X", "area_sqft": 1}),
        (
            "post",
            "/residents",
            {"flat_id": str(uuid.uuid4()), "full_name": "X", "resident_type": "OWNER"},
        ),
    ],
)
async def test_resident_cannot_write_structure(
    client: AsyncClient, scoped: ScopedSociety, method: str, path: str, body: dict[str, Any]
) -> None:
    response = await getattr(client, method)(
        path, headers=auth(scoped.resident_token), json=body
    )
    assert response.status_code == 403, f"{method} {path}"
    assert response.json()["code"] == "PERMISSION_DENIED"


async def test_resident_cannot_enumerate_the_estate(
    client: AsyncClient, scoped: ScopedSociety
) -> None:
    """A resident sees where they live, not the whole society's layout."""
    for path in ("/buildings", "/blocks", "/floors", "/structure/summary", "/structure/tree"):
        response = await client.get(path, headers=auth(scoped.resident_token))
        assert response.status_code == 403, path
        assert response.json()["code"] == "PERMISSION_DENIED"


async def test_resident_still_sees_their_flats_location(
    client: AsyncClient, scoped: ScopedSociety
) -> None:
    """Denormalised names mean no building read is needed to show the address."""
    response = await client.get(
        f"/flats/{scoped.own_flat['id']}", headers=auth(scoped.resident_token)
    )
    flat = response.json()["data"]
    assert flat["building_name"]
    assert flat["block_name"]
    assert flat["floor_name"]


async def test_flats_are_ordered_by_hierarchy_not_text(
    client: AsyncClient, society_a: SocietyFixture, scoped: ScopedSociety
) -> None:
    """ORDER BY flat_number would put "A-1001" before "A-101"."""
    floor10 = (
        await client.post(
            "/floors",
            headers=auth(society_a.admin_token),
            json={"block_id": scoped.block["id"], "number": 10},
        )
    ).json()["data"]
    tag = scoped.building["code"]
    for floor_id, number in (
        (floor10["id"], f"{tag}-1001"),
        (scoped.own_flat["floor_id"], f"{tag}-101"),
    ):
        await client.post(
            "/flats",
            headers=auth(society_a.admin_token),
            json={"floor_id": floor_id, "flat_number": number, "area_sqft": 900},
        )

    listed = await client.get(
        "/flats",
        headers=auth(society_a.admin_token),
        params={"building_id": scoped.building["id"], "limit": 100},
    )
    numbers = [f["flat_number"] for f in listed.json()["data"]["items"]]
    assert numbers.index(f"{tag}-101") < numbers.index(f"{tag}-1001"), numbers


async def test_resident_cannot_delete_their_own_flat(
    client: AsyncClient, scoped: ScopedSociety
) -> None:
    """Owning a flat is not the same as being able to remove it."""
    response = await client.delete(
        f"/flats/{scoped.own_flat['id']}", headers=auth(scoped.resident_token)
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# Cross-society isolation for the new tables
# --------------------------------------------------------------------------- #


async def test_structure_does_not_leak_between_societies(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    tag = uuid.uuid4().hex[:5].upper()
    created = await client.post(
        "/buildings",
        headers=auth(society_a.admin_token),
        json={"name": f"Isolated {tag}", "code": tag},
    )
    assert created.status_code == 201

    in_b = await client.get("/buildings", headers=auth(society_b.admin_token))
    assert all(b["code"] != tag for b in in_b.json()["data"])


async def test_foreign_building_id_returns_404(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    tag = uuid.uuid4().hex[:5].upper()
    building = (
        await client.post(
            "/buildings",
            headers=auth(society_a.admin_token),
            json={"name": f"Foreign {tag}", "code": tag},
        )
    ).json()["data"]

    response = await client.get(
        f"/buildings/{building['id']}", headers=auth(society_b.admin_token)
    )
    assert response.status_code == 404


async def test_foreign_flat_cannot_be_written_to(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture, scoped: ScopedSociety
) -> None:
    """A real flat id from A must not be a valid target for a resident in B."""
    response = await client.post(
        "/residents",
        headers=auth(society_b.admin_token),
        json={
            "flat_id": scoped.own_flat["id"],
            "full_name": "Cross-tenant Insert",
            "resident_type": "OWNER",
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_flat_counts_are_independent_per_society(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    summary_a = (
        await client.get("/structure/summary", headers=auth(society_a.admin_token))
    ).json()["data"]
    summary_b = (
        await client.get("/structure/summary", headers=auth(society_b.admin_token))
    ).json()["data"]

    assert summary_a["flats"] > 0
    assert summary_b["flats"] != summary_a["flats"] or summary_b["buildings"] != summary_a["buildings"]
