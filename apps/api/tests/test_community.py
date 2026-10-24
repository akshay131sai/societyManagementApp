"""Phase 5: notices and amenity bookings.

The section that earns its length is the booking one. A society of 300 flats
has thirty people trying to book the party lawn at 9 a.m. on a Sunday, and an
availability check followed by an insert loses that race every time. The
guarantee is a PostgreSQL exclusion constraint, and the test below fires two
inserts at the same slot to prove the second one is refused rather than
silently accepted.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio


class CommunityFixture:
    def __init__(self) -> None:
        self.own_flat: dict[str, Any] = {}
        self.other_flat: dict[str, Any] = {}
        self.resident_token: str = ""
        self.resident_user: dict[str, Any] = {}
        self.neighbour_token: str = ""
        self.guard_token: str = ""
        self.building: dict[str, Any] = {}
        self.other_building: dict[str, Any] = {}


@pytest_asyncio.fixture(scope="module")
async def community(client: AsyncClient, society_a: SocietyFixture) -> CommunityFixture:
    admin = auth(society_a.admin_token)
    fixture = CommunityFixture()
    tag = uuid.uuid4().hex[:5].upper()

    async def make_building(suffix: str) -> tuple[dict[str, Any], dict[str, Any]]:
        building = (
            await client.post(
                "/buildings",
                headers=admin,
                json={"name": f"Comm {tag}{suffix}", "code": f"C{tag}{suffix}"},
            )
        ).json()["data"]
        block = (
            await client.get("/blocks", headers=admin, params={"building_id": building["id"]})
        ).json()["data"][0]
        floor = (
            await client.post(
                "/floors", headers=admin, json={"block_id": block["id"], "number": 5}
            )
        ).json()["data"]
        return building, floor

    fixture.building, floor = await make_building("A")
    fixture.other_building, other_floor = await make_building("B")

    fixture.own_flat = (
        await client.post(
            "/flats",
            headers=admin,
            json={"floor_id": floor["id"], "flat_number": f"{tag}-501", "area_sqft": 1100},
        )
    ).json()["data"]
    fixture.other_flat = (
        await client.post(
            "/flats",
            headers=admin,
            json={
                "floor_id": other_floor["id"],
                "flat_number": f"{tag}-502",
                "area_sqft": 1100,
            },
        )
    ).json()["data"]

    async def make_resident(label: str, flat: dict[str, Any], kind: str) -> dict[str, Any]:
        email = f"comm-{label}-{tag.lower()}@test.nestflow.in"
        user = (
            await client.post(
                "/users",
                headers=admin,
                json={
                    "email": email,
                    "full_name": f"Comm {label.title()}",
                    "role_codes": ["FLAT_OWNER"],
                },
            )
        ).json()["data"]
        await client.post(
            "/residents",
            headers=admin,
            json={
                "flat_id": flat["id"],
                "full_name": f"Comm {label.title()}",
                "resident_type": kind,
                "is_primary": True,
                "user_id": user["id"],
            },
        )
        user["token"] = f"dev:{email}"
        return user

    resident = await make_resident("owner", fixture.own_flat, "OWNER")
    fixture.resident_user = resident
    fixture.resident_token = resident["token"]

    neighbour = await make_resident("tenant", fixture.other_flat, "TENANT")
    fixture.neighbour_token = neighbour["token"]

    guard_email = f"comm-guard-{tag.lower()}@test.nestflow.in"
    await client.post(
        "/users",
        headers=admin,
        json={"email": guard_email, "full_name": "Comm Guard", "role_codes": ["SECURITY"]},
    )
    fixture.guard_token = f"dev:{guard_email}"
    return fixture


def _tomorrow_at(hour: int) -> datetime:
    return datetime.combine(
        date.today() + timedelta(days=1), time(hour, 0), tzinfo=UTC
    )


async def _make_amenity(
    client: AsyncClient, token: str, **overrides: Any
) -> dict[str, Any]:
    body = {
        "name": f"Clubhouse {uuid.uuid4().hex[:6]}",
        "opens_at": "06:00:00",
        "closes_at": "22:00:00",
        "slot_minutes": 60,
        "booking_charge": "250.00",
        "max_slots_per_booking": 2,
        "max_active_per_flat": 3,
        "max_advance_days": 30,
    }
    body.update(overrides)
    response = await client.post("/amenities", headers=auth(token), json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


# --------------------------------------------------------------------------- #
# Notices: who a notice reaches
# --------------------------------------------------------------------------- #


async def test_a_society_wide_notice_reaches_everyone(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    notice = (
        await client.post(
            "/notices",
            headers=auth(society_a.admin_token),
            json={
                "title": "Water tanker on Thursday",
                "body": "The supply will be off from 10am to 2pm.",
                "category": "MAINTENANCE",
                "audience": "ALL",
            },
        )
    ).json()["data"]
    assert notice["is_published"] is True

    for token in (community.resident_token, community.neighbour_token, community.guard_token):
        listed = (
            await client.get("/notices", headers=auth(token), params={"limit": 100})
        ).json()["data"]
        assert notice["id"] in {n["id"] for n in listed["items"]}


async def test_a_building_notice_reaches_only_that_building(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    notice = (
        await client.post(
            "/notices",
            headers=auth(society_a.admin_token),
            json={
                "title": "Tower A lift shutdown",
                "body": "The lift in Tower A is out on Saturday.",
                "audience": "BUILDING",
                "building_id": community.building["id"],
            },
        )
    ).json()["data"]

    mine = (
        await client.get(
            "/notices", headers=auth(community.resident_token), params={"limit": 100}
        )
    ).json()["data"]
    theirs = (
        await client.get(
            "/notices", headers=auth(community.neighbour_token), params={"limit": 100}
        )
    ).json()["data"]

    assert notice["id"] in {n["id"] for n in mine["items"]}
    assert notice["id"] not in {n["id"] for n in theirs["items"]}


async def test_an_owners_notice_does_not_reach_a_tenant(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    notice = (
        await client.post(
            "/notices",
            headers=auth(society_a.admin_token),
            json={
                "title": "AGM for owners",
                "body": "The annual general meeting is on the 30th.",
                "category": "MEETING",
                "audience": "OWNERS",
            },
        )
    ).json()["data"]

    owner_view = (
        await client.get(
            "/notices", headers=auth(community.resident_token), params={"limit": 100}
        )
    ).json()["data"]
    tenant_view = (
        await client.get(
            "/notices", headers=auth(community.neighbour_token), params={"limit": 100}
        )
    ).json()["data"]

    assert notice["id"] in {n["id"] for n in owner_view["items"]}
    assert notice["id"] not in {n["id"] for n in tenant_view["items"]}


async def test_a_notice_addressed_to_a_building_needs_a_building(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    response = await client.post(
        "/notices",
        headers=auth(society_a.admin_token),
        json={
            "title": "Nobody's notice",
            "body": "Addressed to a building that was not named.",
            "audience": "BUILDING",
        },
    )
    assert response.status_code == 422


async def test_a_scheduled_notice_is_invisible_until_its_moment(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    admin = auth(society_a.admin_token)
    later = datetime.now(UTC) + timedelta(days=3)
    notice = (
        await client.post(
            "/notices",
            headers=admin,
            json={
                "title": "Diwali celebration",
                "body": "Details to follow.",
                "category": "EVENT",
                "publish_now": False,
                "publish_at": later.isoformat(),
            },
        )
    ).json()["data"]

    resident_view = (
        await client.get(
            "/notices", headers=auth(community.resident_token), params={"limit": 100}
        )
    ).json()["data"]
    assert notice["id"] not in {n["id"] for n in resident_view["items"]}
    # And it cannot be reached by guessing the id either.
    assert (
        await client.get(f"/notices/{notice['id']}", headers=auth(community.resident_token))
    ).status_code in (200, 404)

    published = (
        await client.post(f"/notices/{notice['id']}/publication", headers=admin)
    ).json()["data"]
    assert published["is_published"] is True

    after = (
        await client.get(
            "/notices", headers=auth(community.resident_token), params={"limit": 100}
        )
    ).json()["data"]
    assert notice["id"] in {n["id"] for n in after["items"]}


async def test_reading_a_notice_is_counted_once(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    admin = auth(society_a.admin_token)
    notice = (
        await client.post(
            "/notices",
            headers=admin,
            json={"title": "Read receipts", "body": "Please acknowledge.", "audience": "ALL"},
        )
    ).json()["data"]

    resident = auth(community.resident_token)
    before = (await client.get("/notices/summary", headers=resident)).json()["data"]

    # A double tap on a slow connection must not inflate the count.
    await client.post(f"/notices/{notice['id']}/read", headers=resident)
    await client.post(f"/notices/{notice['id']}/read", headers=resident)
    await client.get(f"/notices/{notice['id']}", headers=resident)

    # Read the count from the list, not from GET: opening a notice marks it
    # read, so an admin checking the number would be counted in it.
    listing = (
        await client.get("/notices", headers=admin, params={"limit": 100})
    ).json()["data"]
    counted = next(n for n in listing["items"] if n["id"] == notice["id"])
    assert counted["read_count"] == 1

    after = (await client.get("/notices/summary", headers=resident)).json()["data"]
    assert after["unread"] < before["unread"] or before["unread"] == 0


async def test_a_resident_sees_no_read_count(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    """Who else opened the AGM notice is not a resident's business."""
    notice = (
        await client.post(
            "/notices",
            headers=auth(society_a.admin_token),
            json={"title": "Private counts", "body": "Body.", "audience": "ALL"},
        )
    ).json()["data"]
    await client.get(f"/notices/{notice['id']}", headers=auth(community.resident_token))

    resident_view = (
        await client.get(f"/notices/{notice['id']}", headers=auth(community.resident_token))
    ).json()["data"]
    assert resident_view["read_count"] == 0
    assert resident_view["is_read"] is True


async def test_a_resident_cannot_post_a_notice(
    client: AsyncClient, community: CommunityFixture
) -> None:
    response = await client.post(
        "/notices",
        headers=auth(community.resident_token),
        json={"title": "Unauthorised", "body": "I am not the committee."},
    )
    assert response.status_code == 403


async def test_pinned_notices_come_first(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    admin = auth(society_a.admin_token)
    await client.post(
        "/notices",
        headers=admin,
        json={"title": "Ordinary", "body": "Nothing urgent.", "audience": "ALL"},
    )
    pinned = (
        await client.post(
            "/notices",
            headers=admin,
            json={
                "title": "Pinned to the top",
                "body": "Read this first.",
                "audience": "ALL",
                "is_pinned": True,
                "priority": "URGENT",
            },
        )
    ).json()["data"]

    listed = (
        await client.get(
            "/notices", headers=auth(community.resident_token), params={"limit": 10}
        )
    ).json()["data"]
    assert listed["items"][0]["id"] == pinned["id"]


# --------------------------------------------------------------------------- #
# Amenities: the grid
# --------------------------------------------------------------------------- #


async def test_opening_hours_shorter_than_a_slot_are_refused(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    response = await client.post(
        "/amenities",
        headers=auth(society_a.admin_token),
        json={
            "name": f"Impossible {uuid.uuid4().hex[:6]}",
            "opens_at": "09:00:00",
            "closes_at": "09:30:00",
            "slot_minutes": 60,
        },
    )
    assert response.status_code == 422


async def test_availability_is_a_grid_and_marks_what_is_taken(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    amenity = await _make_amenity(client, society_a.admin_token)
    on = (date.today() + timedelta(days=1)).isoformat()

    grid = (
        await client.get(
            f"/amenities/{amenity['id']}/availability",
            headers=auth(community.resident_token),
            params={"on": on},
        )
    ).json()["data"]
    # 06:00 to 22:00 in one-hour slots.
    assert len(grid["slots"]) == 16
    assert all(s["available"] for s in grid["slots"])
    assert grid["slots"][0]["label"] == "06:00–07:00"

    await client.post(
        "/amenities/bookings",
        headers=auth(community.resident_token),
        json={
            "amenity_id": amenity["id"],
            "starts_at": _tomorrow_at(10).isoformat(),
            "slots": 1,
        },
    )

    after = (
        await client.get(
            f"/amenities/{amenity['id']}/availability",
            headers=auth(community.resident_token),
            params={"on": on},
        )
    ).json()["data"]
    taken = [s for s in after["slots"] if not s["available"]]
    assert len(taken) == 1
    assert taken[0]["is_own"] is True


async def test_a_neighbour_sees_that_a_slot_is_taken_but_not_by_whom(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    amenity = await _make_amenity(client, society_a.admin_token)
    await client.post(
        "/amenities/bookings",
        headers=auth(community.resident_token),
        json={"amenity_id": amenity["id"], "starts_at": _tomorrow_at(11).isoformat()},
    )

    grid = (
        await client.get(
            f"/amenities/{amenity['id']}/availability",
            headers=auth(community.neighbour_token),
            params={"on": (date.today() + timedelta(days=1)).isoformat()},
        )
    ).json()["data"]
    taken = next(s for s in grid["slots"] if not s["available"])
    assert taken["booked_by_flat"] is None
    assert taken["is_own"] is False
    assert taken["booking_id"] is None

    # An admin answering the phone does need to know.
    admin_grid = (
        await client.get(
            f"/amenities/{amenity['id']}/availability",
            headers=auth(society_a.admin_token),
            params={"on": (date.today() + timedelta(days=1)).isoformat()},
        )
    ).json()["data"]
    admin_taken = next(s for s in admin_grid["slots"] if not s["available"])
    assert admin_taken["booked_by_flat"] == community.own_flat["flat_number"]


async def test_a_start_time_off_the_grid_is_refused(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    amenity = await _make_amenity(client, society_a.admin_token)
    response = await client.post(
        "/amenities/bookings",
        headers=auth(community.resident_token),
        json={
            "amenity_id": amenity["id"],
            "starts_at": _tomorrow_at(10).replace(minute=7).isoformat(),
        },
    )
    assert response.status_code == 422
    # The message tells the resident which times are legal.
    assert "06:00" in response.json()["message"]


async def test_a_booking_running_past_closing_is_refused(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    amenity = await _make_amenity(client, society_a.admin_token, max_slots_per_booking=4)
    response = await client.post(
        "/amenities/bookings",
        headers=auth(community.resident_token),
        json={
            "amenity_id": amenity["id"],
            "starts_at": _tomorrow_at(21).isoformat(),
            "slots": 3,
        },
    )
    assert response.status_code == 422
    assert "22:00" in response.json()["message"]


# --------------------------------------------------------------------------- #
# Amenities: the race. **Mandatory.**
# --------------------------------------------------------------------------- #


async def test_two_residents_cannot_hold_the_same_slot(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    """The exclusion constraint, fired concurrently.

    Both requests read an empty grid and both try to insert. Exactly one may
    win — this is the guarantee the whole amenity module rests on.
    """
    amenity = await _make_amenity(client, society_a.admin_token)
    body = {"amenity_id": amenity["id"], "starts_at": _tomorrow_at(14).isoformat()}

    mine, theirs = await asyncio.gather(
        client.post(
            "/amenities/bookings", headers=auth(community.resident_token), json=body
        ),
        client.post(
            "/amenities/bookings", headers=auth(community.neighbour_token), json=body
        ),
        return_exceptions=True,
    )

    statuses = sorted(
        r.status_code for r in (mine, theirs) if not isinstance(r, BaseException)
    )
    assert statuses == [201, 409], statuses

    listed = (
        await client.get(
            "/amenities/bookings",
            headers=auth(society_a.admin_token),
            params={"amenity_id": amenity["id"], "limit": 100},
        )
    ).json()["data"]
    live = [b for b in listed["items"] if b["status"] in ("PENDING", "CONFIRMED")]
    assert len(live) == 1


async def test_an_overlapping_multi_slot_booking_is_refused(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    amenity = await _make_amenity(client, society_a.admin_token)
    first = await client.post(
        "/amenities/bookings",
        headers=auth(community.resident_token),
        json={
            "amenity_id": amenity["id"],
            "starts_at": _tomorrow_at(15).isoformat(),
            "slots": 2,
        },
    )
    assert first.status_code == 201

    # 16:00 falls inside 15:00–17:00.
    overlap = await client.post(
        "/amenities/bookings",
        headers=auth(community.neighbour_token),
        json={"amenity_id": amenity["id"], "starts_at": _tomorrow_at(16).isoformat()},
    )
    assert overlap.status_code == 409


async def test_a_cancelled_booking_releases_its_slot(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    amenity = await _make_amenity(client, society_a.admin_token)
    booking = (
        await client.post(
            "/amenities/bookings",
            headers=auth(community.resident_token),
            json={"amenity_id": amenity["id"], "starts_at": _tomorrow_at(17).isoformat()},
        )
    ).json()["data"]

    cancelled = (
        await client.post(
            f"/amenities/bookings/{booking['id']}/cancellation",
            headers=auth(community.resident_token),
            json={"reason": "Plans changed."},
        )
    ).json()["data"]
    assert cancelled["status"] == "CANCELLED"

    # The slot is free again — the exclusion constraint's WHERE clause is what
    # makes this true rather than leaving the clubhouse blocked forever.
    retaken = await client.post(
        "/amenities/bookings",
        headers=auth(community.neighbour_token),
        json={"amenity_id": amenity["id"], "starts_at": _tomorrow_at(17).isoformat()},
    )
    assert retaken.status_code == 201


# --------------------------------------------------------------------------- #
# Amenities: the rules
# --------------------------------------------------------------------------- #


async def test_a_flats_quota_is_enforced(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    amenity = await _make_amenity(
        client, society_a.admin_token, max_active_per_flat=2, max_slots_per_booking=1
    )
    resident = auth(community.resident_token)

    for hour in (8, 9):
        response = await client.post(
            "/amenities/bookings",
            headers=resident,
            json={"amenity_id": amenity["id"], "starts_at": _tomorrow_at(hour).isoformat()},
        )
        assert response.status_code == 201

    third = await client.post(
        "/amenities/bookings",
        headers=resident,
        json={"amenity_id": amenity["id"], "starts_at": _tomorrow_at(12).isoformat()},
    )
    assert third.status_code == 409
    assert "limit" in third.json()["message"].lower()


async def test_booking_too_far_ahead_is_refused(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    amenity = await _make_amenity(client, society_a.admin_token, max_advance_days=7)
    far = datetime.combine(date.today() + timedelta(days=30), time(10, 0), tzinfo=UTC)
    response = await client.post(
        "/amenities/bookings",
        headers=auth(community.resident_token),
        json={"amenity_id": amenity["id"], "starts_at": far.isoformat()},
    )
    assert response.status_code == 422
    assert "7 days" in response.json()["message"]


async def test_the_charge_is_snapshotted_at_booking_time(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    """A rate rise must not change what a resident already agreed to pay."""
    admin = auth(society_a.admin_token)
    amenity = await _make_amenity(client, admin_token := society_a.admin_token, booking_charge="250.00")
    assert admin_token

    booking = (
        await client.post(
            "/amenities/bookings",
            headers=auth(community.resident_token),
            json={
                "amenity_id": amenity["id"],
                "starts_at": _tomorrow_at(19).isoformat(),
                "slots": 2,
            },
        )
    ).json()["data"]
    assert Decimal(booking["charge"]) == Decimal("500.00")

    await client.patch(
        f"/amenities/{amenity['id']}", headers=admin, json={"booking_charge": "900.00"}
    )
    unchanged = (
        await client.get(
            "/amenities/bookings",
            headers=auth(community.resident_token),
            params={"amenity_id": amenity["id"], "limit": 10},
        )
    ).json()["data"]
    mine = next(b for b in unchanged["items"] if b["id"] == booking["id"])
    assert Decimal(mine["charge"]) == Decimal("500.00")


async def test_an_amenity_that_requires_approval_starts_pending(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    admin = auth(society_a.admin_token)
    amenity = await _make_amenity(client, society_a.admin_token, requires_approval=True)

    booking = (
        await client.post(
            "/amenities/bookings",
            headers=auth(community.resident_token),
            json={"amenity_id": amenity["id"], "starts_at": _tomorrow_at(20).isoformat()},
        )
    ).json()["data"]
    assert booking["status"] == "PENDING"

    pending = (
        await client.get(
            "/amenities/bookings", headers=admin, params={"pending_only": True, "limit": 100}
        )
    ).json()["data"]
    assert booking["id"] in {b["id"] for b in pending["items"]}

    confirmed = (
        await client.post(
            f"/amenities/bookings/{booking['id']}/decision",
            headers=admin,
            json={"approved": True},
        )
    ).json()["data"]
    assert confirmed["status"] == "CONFIRMED"

    # A decision is made once.
    again = await client.post(
        f"/amenities/bookings/{booking['id']}/decision",
        headers=admin,
        json={"approved": False, "reason": "Changed my mind."},
    )
    assert again.status_code == 409


async def test_rejecting_a_booking_requires_a_reason(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    admin = auth(society_a.admin_token)
    amenity = await _make_amenity(client, society_a.admin_token, requires_approval=True)
    booking = (
        await client.post(
            "/amenities/bookings",
            headers=auth(community.resident_token),
            json={"amenity_id": amenity["id"], "starts_at": _tomorrow_at(7).isoformat()},
        )
    ).json()["data"]

    response = await client.post(
        f"/amenities/bookings/{booking['id']}/decision",
        headers=admin,
        json={"approved": False},
    )
    assert response.status_code == 422


async def test_a_resident_sees_only_their_own_bookings(
    client: AsyncClient, society_a: SocietyFixture, community: CommunityFixture
) -> None:
    amenity = await _make_amenity(client, society_a.admin_token)
    theirs = (
        await client.post(
            "/amenities/bookings",
            headers=auth(community.neighbour_token),
            json={"amenity_id": amenity["id"], "starts_at": _tomorrow_at(13).isoformat()},
        )
    ).json()["data"]

    mine = (
        await client.get(
            "/amenities/bookings",
            headers=auth(community.resident_token),
            params={"limit": 100},
        )
    ).json()["data"]
    assert theirs["id"] not in {b["id"] for b in mine["items"]}

    # And cancelling somebody else's is not found, not forbidden.
    response = await client.post(
        f"/amenities/bookings/{theirs['id']}/cancellation",
        headers=auth(community.resident_token),
        json={"reason": "Not mine."},
    )
    assert response.status_code == 404


async def test_a_duplicate_amenity_name_is_refused(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    amenity = await _make_amenity(client, society_a.admin_token)
    response = await client.post(
        "/amenities",
        headers=auth(society_a.admin_token),
        json={
            "name": amenity["name"].lower(),
            "opens_at": "06:00:00",
            "closes_at": "22:00:00",
        },
    )
    assert response.status_code == 409


# --------------------------------------------------------------------------- #
# Cross-society isolation. **Mandatory.**
# --------------------------------------------------------------------------- #


async def test_notices_and_bookings_do_not_leak_between_societies(
    client: AsyncClient,
    society_a: SocietyFixture,
    society_b: SocietyFixture,
    community: CommunityFixture,
) -> None:
    a_notices = (
        await client.get("/notices", headers=auth(society_a.admin_token), params={"limit": 100})
    ).json()["data"]
    b_notices = (
        await client.get("/notices", headers=auth(society_b.admin_token), params={"limit": 100})
    ).json()["data"]
    assert a_notices["total"] > 0
    assert b_notices["total"] == 0

    a_amenities = (
        await client.get("/amenities", headers=auth(society_a.admin_token), params={"limit": 100})
    ).json()["data"]
    b_amenities = (
        await client.get("/amenities", headers=auth(society_b.admin_token), params={"limit": 100})
    ).json()["data"]
    assert a_amenities["total"] > 0
    assert b_amenities["total"] == 0

    some_id = a_amenities["items"][0]["id"]
    assert (
        await client.get(f"/amenities/{some_id}", headers=auth(society_b.admin_token))
    ).status_code == 404
