"""Family member logins — who may grant them, and what they can reach.

The point of these tests is the *second* edge into a flat. A resident reaches
their flat through ``residents.user_id``; a family member reaches it through
the resident who registered them. Every owner-scoped service filters on
``principal.flat_ids``, so if that second edge is resolved correctly the whole
of the existing scoping applies to the household for free — and if it is
resolved too generously, it leaks the entire society at once.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio


async def _flat(client: AsyncClient, society: SocietyFixture) -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:4].upper()
    building = (
        await client.post(
            "/buildings",
            headers=auth(society.admin_token),
            json={"name": f"Tower {suffix}", "code": suffix, "total_floors": 10},
        )
    ).json()["data"]
    block = (
        await client.get(
            "/blocks", headers=auth(society.admin_token), params={"building_id": building["id"]}
        )
    ).json()["data"][0]
    floor = (
        await client.post(
            "/floors",
            headers=auth(society.admin_token),
            json={"block_id": block["id"], "number": 3},
        )
    ).json()["data"]
    return (
        await client.post(
            "/flats",
            headers=auth(society.admin_token),
            json={
                "floor_id": floor["id"],
                "flat_number": f"F-{uuid.uuid4().hex[:6]}",
                "area_sqft": 1100,
                "flat_type": "2BHK",
            },
        )
    ).json()["data"]


async def _primary_resident(
    client: AsyncClient, society: SocietyFixture, flat: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    """A flat admin: a tenant user with FLAT_OWNER, primary on their flat."""
    email = f"owner-{uuid.uuid4().hex[:8]}@test.nestflow.in"
    created = await client.post(
        "/users",
        headers=auth(society.admin_token),
        json={"email": email, "full_name": "Flat Admin", "role_codes": ["FLAT_OWNER"]},
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["data"]["id"]

    resident = await client.post(
        "/residents",
        headers=auth(society.admin_token),
        json={
            "flat_id": flat["id"],
            "user_id": user_id,
            "full_name": "Flat Admin",
            "email": email,
            "resident_type": "OWNER",
            "is_primary": True,
        },
    )
    assert resident.status_code == 201, resident.text
    return resident.json()["data"], f"dev:{email}"


@pytest_asyncio.fixture
async def household(
    client: AsyncClient, society_a: SocietyFixture
) -> dict[str, Any]:
    flat = await _flat(client, society_a)
    resident, token = await _primary_resident(client, society_a, flat)
    return {"flat": flat, "resident": resident, "token": token}


# --------------------------------------------------------------------------- #
# The flat admin owns the roster
# --------------------------------------------------------------------------- #


async def test_flat_admin_can_add_family_to_their_own_flat(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    """The whole point: this used to require RESIDENT_MANAGE, i.e. an admin."""
    created = await client.post(
        "/family-members",
        headers=auth(household["token"]),
        json={
            "resident_id": household["resident"]["id"],
            "full_name": "Kiara",
            "relationship_to_resident": "DAUGHTER",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["access_level"] == "NONE"
    assert created.json()["data"]["has_login"] is False


async def test_a_residents_menu_shows_my_family_and_not_the_directory(
    client: AsyncClient, household: dict[str, Any], society_a: SocietyFixture
) -> None:
    """A resident's `resident.read` is narrowed to their own flat, so a
    Residents directory would list only their own household — which My Family
    already does properly. The admin, whose read is society-wide, keeps both."""
    resident_nav = (await client.get("/auth/me", headers=auth(household["token"]))).json()[
        "data"
    ]["navigation"]
    keys = {i["key"] for i in resident_nav}
    assert "family" in keys
    assert "residents" not in keys

    # And it must be a real link, not a disabled "Soon" placeholder.
    family = next(i for i in resident_nav if i["key"] == "family")
    assert family["badge"] is None, "My Family has a screen; it must not be marked coming_soon"


async def test_a_society_admins_menu_is_the_society_not_a_household(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    """The admin runs the society: they get the Residents directory, and not
    the two my-household screens, whose society-wide forms live elsewhere."""
    nav = (await client.get("/auth/me", headers=auth(society_a.admin_token))).json()["data"][
        "navigation"
    ]
    keys = {i["key"] for i in nav}

    assert "residents" in keys
    assert "family" not in keys, "My Family is a resident's screen"
    assert "pets" not in keys, "pet totals belong on the utility dashboard"

    # Everything the admin actually runs the society with is untouched.
    assert {
        "buildings", "flats", "users", "bill-builder", "bills", "payments",
        "water", "electricity", "parking", "vehicles", "complaints",
        "maintenance", "housekeeping", "security", "visitors", "notices",
        "amenities", "reports", "settings",
    } <= keys


async def test_a_flat_admin_cannot_touch_another_flats_household(
    client: AsyncClient, society_a: SocietyFixture, household: dict[str, Any]
) -> None:
    other_flat = await _flat(client, society_a)
    other_resident, _ = await _primary_resident(client, society_a, other_flat)

    response = await client.post(
        "/family-members",
        headers=auth(household["token"]),
        json={
            "resident_id": other_resident["id"],
            "full_name": "Not Mine",
            "relationship_to_resident": "SON",
        },
    )
    assert response.status_code == 403, response.text


async def test_a_non_primary_resident_is_not_the_flat_admin(
    client: AsyncClient, society_a: SocietyFixture, household: dict[str, Any]
) -> None:
    """Owner scoping alone would have let this through — both residents are on
    the same flat. Only the primary runs the household."""
    email = f"second-{uuid.uuid4().hex[:8]}@test.nestflow.in"
    user_id = (
        await client.post(
            "/users",
            headers=auth(society_a.admin_token),
            json={"email": email, "full_name": "Second Owner", "role_codes": ["FLAT_OWNER"]},
        )
    ).json()["data"]["id"]
    await client.post(
        "/residents",
        headers=auth(society_a.admin_token),
        json={
            "flat_id": household["flat"]["id"],
            "user_id": user_id,
            "full_name": "Second Owner",
            "email": email,
            "resident_type": "OWNER",
            "is_primary": False,
        },
    )

    response = await client.post(
        "/family-members",
        headers=auth(f"dev:{email}"),
        json={
            "resident_id": household["resident"]["id"],
            "full_name": "Nope",
            "relationship_to_resident": "SON",
        },
    )
    assert response.status_code == 403, response.text


# --------------------------------------------------------------------------- #
# A granted login reaches exactly one flat
# --------------------------------------------------------------------------- #


async def _add_member(
    client: AsyncClient, household: dict[str, Any], *, relationship: str = "SON"
) -> dict[str, Any]:
    return (
        await client.post(
            "/family-members",
            headers=auth(household["token"]),
            json={
                "resident_id": household["resident"]["id"],
                "full_name": "Household Member",
                "relationship_to_resident": relationship,
            },
        )
    ).json()["data"]


async def test_a_granted_family_member_inherits_exactly_one_flat(
    client: AsyncClient, society_a: SocietyFixture, household: dict[str, Any]
) -> None:
    member = await _add_member(client, household)
    email = f"kid-{uuid.uuid4().hex[:8]}@test.nestflow.in"

    granted = await client.post(
        f"/family-members/{member['id']}/access",
        headers=auth(household["token"]),
        json={"access_level": "CHILD", "email": email},
    )
    assert granted.status_code == 200, granted.text
    assert granted.json()["data"]["has_login"] is True

    token = f"dev:{email}"
    me = (await client.get("/auth/me", headers=auth(token))).json()["data"]
    assert me["principal"]["roles"] == ["FLAT_CHILD"]

    # The flat, and only the flat.
    flats = (await client.get("/flats", headers=auth(token), params={"limit": 100})).json()
    assert flats["data"]["total"] == 1
    assert flats["data"]["items"][0]["id"] == household["flat"]["id"]


async def test_a_family_member_cannot_reach_another_flat_by_id(
    client: AsyncClient, society_a: SocietyFixture, household: dict[str, Any]
) -> None:
    """List filtering is the easy half. Direct object access is the real test."""
    other_flat = await _flat(client, society_a)
    member = await _add_member(client, household)
    email = f"kid-{uuid.uuid4().hex[:8]}@test.nestflow.in"
    await client.post(
        f"/family-members/{member['id']}/access",
        headers=auth(household["token"]),
        json={"access_level": "CHILD", "email": email},
    )

    response = await client.get(f"/flats/{other_flat['id']}", headers=auth(f"dev:{email}"))
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "NOT_FOUND", "existence must not leak"


async def test_the_restricted_tier_cannot_read_the_flats_money(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    member = await _add_member(client, household)
    email = f"kid-{uuid.uuid4().hex[:8]}@test.nestflow.in"
    await client.post(
        f"/family-members/{member['id']}/access",
        headers=auth(household["token"]),
        json={"access_level": "CHILD", "email": email},
    )
    token = f"dev:{email}"

    guarded = ("/billing/bills", "/payments", "/water/readings", "/electricity/readings")
    for path in guarded:
        response = await client.get(path, headers=auth(token))
        assert response.status_code == 403, f"{path} leaked to a restricted member"

    # Upgrading the tier opens exactly those doors — and no others.
    upgraded = await client.post(
        f"/family-members/{member['id']}/access",
        headers=auth(household["token"]),
        json={"access_level": "MEMBER"},
    )
    assert upgraded.status_code == 200, upgraded.text
    for path in guarded:
        assert (await client.get(path, headers=auth(token))).status_code == 200, path


async def test_a_plain_member_cannot_manage_the_household(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    member = await _add_member(client, household)
    email = f"adult-{uuid.uuid4().hex[:8]}@test.nestflow.in"
    await client.post(
        f"/family-members/{member['id']}/access",
        headers=auth(household["token"]),
        json={"access_level": "MEMBER", "email": email},
    )

    response = await client.post(
        "/family-members",
        headers=auth(f"dev:{email}"),
        json={
            "resident_id": household["resident"]["id"],
            "full_name": "Someone Else",
            "relationship_to_resident": "SON",
        },
    )
    assert response.status_code == 403, response.text


async def test_a_co_admin_can_manage_the_household(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    member = await _add_member(client, household, relationship="SPOUSE")
    email = f"spouse-{uuid.uuid4().hex[:8]}@test.nestflow.in"
    await client.post(
        f"/family-members/{member['id']}/access",
        headers=auth(household["token"]),
        json={"access_level": "CO_ADMIN", "email": email},
    )

    response = await client.post(
        "/family-members",
        headers=auth(f"dev:{email}"),
        json={
            "resident_id": household["resident"]["id"],
            "full_name": "Added By Spouse",
            "relationship_to_resident": "DAUGHTER",
        },
    )
    assert response.status_code == 201, response.text


async def test_revoking_access_closes_the_door_but_keeps_the_person(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    member = await _add_member(client, household)
    email = f"gone-{uuid.uuid4().hex[:8]}@test.nestflow.in"
    await client.post(
        f"/family-members/{member['id']}/access",
        headers=auth(household["token"]),
        json={"access_level": "MEMBER", "email": email},
    )
    token = f"dev:{email}"
    assert (await client.get("/auth/me", headers=auth(token))).status_code == 200

    revoked = await client.delete(
        f"/family-members/{member['id']}/access", headers=auth(household["token"])
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["data"]["access_level"] == "NONE"
    assert revoked.json()["data"]["has_login"] is False
    assert revoked.json()["data"]["full_name"] == "Household Member", (
        "the person stays on the roster so audit history stays attributable"
    )

    assert (await client.get("/auth/me", headers=auth(token))).status_code >= 400


async def test_access_can_be_given_back_after_being_revoked(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    """Revoking deactivates the tenant user but leaves it holding the address,
    and ``ux_users_email_lower`` is society-wide and unconditional. Without
    adopting that dormant row, a re-invite is permanently impossible — which
    would make the revoke dialog's "you can give access back at any time" a
    lie."""
    member = await _add_member(client, household)
    email = f"back-{uuid.uuid4().hex[:8]}@test.nestflow.in"
    grant = {"access_level": "MEMBER", "email": email}

    await client.post(
        f"/family-members/{member['id']}/access", headers=auth(household["token"]), json=grant
    )
    await client.delete(
        f"/family-members/{member['id']}/access", headers=auth(household["token"])
    )

    again = await client.post(
        f"/family-members/{member['id']}/access", headers=auth(household["token"]), json=grant
    )
    assert again.status_code == 200, again.text
    assert again.json()["data"]["has_login"] is True

    me = await client.get("/auth/me", headers=auth(f"dev:{email}"))
    assert me.status_code == 200, "the reclaimed account must sign in again"
    assert me.json()["data"]["principal"]["roles"] == ["FLAT_MEMBER"]


async def test_a_live_account_is_never_adopted_by_a_re_invite(
    client: AsyncClient, society_a: SocietyFixture, household: dict[str, Any]
) -> None:
    """The flip side of reclaiming: an address belonging to somebody who is
    still active must never be absorbed into this household."""
    staff_email = f"staff-{uuid.uuid4().hex[:8]}@test.nestflow.in"
    created = await client.post(
        "/users",
        headers=auth(society_a.admin_token),
        json={"email": staff_email, "full_name": "Security Staff", "role_codes": ["SECURITY"]},
    )
    assert created.status_code == 201, created.text

    member = await _add_member(client, household)
    response = await client.post(
        f"/family-members/{member['id']}/access",
        headers=auth(household["token"]),
        json={"access_level": "CO_ADMIN", "email": staff_email},
    )
    assert response.status_code == 409, response.text

    # The staff account keeps its own role and is untouched.
    me = await client.get("/auth/me", headers=auth(f"dev:{staff_email}"))
    assert me.json()["data"]["principal"]["roles"] == ["SECURITY"]


async def test_an_address_cannot_be_used_twice(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    first = await _add_member(client, household)
    second = await _add_member(client, household, relationship="DAUGHTER")
    email = f"dup-{uuid.uuid4().hex[:8]}@test.nestflow.in"

    await client.post(
        f"/family-members/{first['id']}/access",
        headers=auth(household["token"]),
        json={"access_level": "MEMBER", "email": email},
    )
    clash = await client.post(
        f"/family-members/{second['id']}/access",
        headers=auth(household["token"]),
        json={"access_level": "MEMBER", "email": email},
    )
    assert clash.status_code == 409, clash.text


async def test_a_tier_cannot_be_granted_without_an_address(
    client: AsyncClient, household: dict[str, Any]
) -> None:
    member = await _add_member(client, household)
    response = await client.post(
        f"/family-members/{member['id']}/access",
        headers=auth(household["token"]),
        json={"access_level": "MEMBER"},
    )
    assert response.status_code == 422, response.text
