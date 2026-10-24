"""Phase 4: utility readings, assets and the resident dashboard.

Three properties matter more than the CRUD, and each has its own section below:

* **Consumption is computed by the database**, not by any caller, so a
  correction to one reading cannot leave a stale figure behind.
* **A meter cannot run backwards.** A transposed entry is caught before it
  becomes a negative charge on a resident's bill.
* **Owner scoping.** A resident holds ``water.read`` and still sees only their
  own meter — and cannot register a vehicle against a neighbour's flat.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio


class UtilityFixture:
    """A society with two flats, one of which a resident login owns."""

    def __init__(self) -> None:
        self.own_flat: dict[str, Any] = {}
        self.other_flat: dict[str, Any] = {}
        self.resident_token: str = ""


@pytest_asyncio.fixture(scope="module")
async def util(client: AsyncClient, society_a: SocietyFixture) -> UtilityFixture:
    admin = auth(society_a.admin_token)
    fixture = UtilityFixture()
    tag = uuid.uuid4().hex[:5].upper()

    building = (
        await client.post(
            "/buildings", headers=admin, json={"name": f"Util {tag}", "code": f"U{tag}"}
        )
    ).json()["data"]
    block = (
        await client.get("/blocks", headers=admin, params={"building_id": building["id"]})
    ).json()["data"][0]
    floor = (
        await client.post(
            "/floors", headers=admin, json={"block_id": block["id"], "number": 1}
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
                    "area_sqft": 900,
                },
            )
        ).json()["data"]
        setattr(fixture, f"{label}_flat", flat)

    email = f"util-{tag.lower()}@test.nestflow.in"
    user = (
        await client.post(
            "/users",
            headers=admin,
            json={"email": email, "full_name": "Util Resident", "role_codes": ["FLAT_OWNER"]},
        )
    ).json()["data"]
    fixture.resident_token = f"dev:{email}"

    await client.post(
        "/residents",
        headers=admin,
        json={
            "flat_id": fixture.own_flat["id"],
            "full_name": "Util Resident",
            "resident_type": "OWNER",
            "is_primary": True,
            "user_id": user["id"],
        },
    )
    return fixture


def _day(offset: int) -> str:
    return (date.today() - timedelta(days=offset)).isoformat()


# --------------------------------------------------------------------------- #
# Consumption is the database's arithmetic, not the caller's
# --------------------------------------------------------------------------- #


async def test_consumption_is_derived_from_the_readings(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    admin = auth(society_a.admin_token)
    response = await client.post(
        "/water/readings",
        headers=admin,
        json={
            "flat_id": util.own_flat["id"],
            "reading_date": _day(120),
            "previous_reading": "1000.000",
            "current_reading": "1042.500",
        },
    )
    assert response.status_code == 201, response.text
    assert Decimal(response.json()["data"]["consumption"]) == Decimal("42.500")


async def test_consumption_is_never_accepted_from_the_client(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    """A caller claiming a consumption must not be able to set one."""
    response = await client.post(
        "/water/readings",
        headers=auth(society_a.admin_token),
        json={
            "flat_id": util.other_flat["id"],
            "reading_date": _day(119),
            "previous_reading": "500.000",
            "current_reading": "520.000",
            "consumption": "9999.000",
        },
    )
    assert response.status_code == 201
    assert Decimal(response.json()["data"]["consumption"]) == Decimal("20.000")


async def test_correcting_a_reading_recomputes_consumption(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    admin = auth(society_a.admin_token)
    created = (
        await client.post(
            "/water/readings",
            headers=admin,
            json={
                "flat_id": util.own_flat["id"],
                "reading_date": _day(118),
                "previous_reading": "1042.500",
                "current_reading": "1080.000",
            },
        )
    ).json()["data"]
    assert Decimal(created["consumption"]) == Decimal("37.500")

    updated = await client.patch(
        f"/water/readings/{created['id']}",
        headers=admin,
        json={"current_reading": "1070.000", "remarks": "Misread the last digit."},
    )
    assert updated.status_code == 200, updated.text
    assert Decimal(updated.json()["data"]["consumption"]) == Decimal("27.500")


async def test_a_missing_previous_reading_carries_the_last_one_forward(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    """A reader enters one number; the series stays continuous."""
    response = await client.post(
        "/water/readings",
        headers=auth(society_a.admin_token),
        json={
            "flat_id": util.own_flat["id"],
            "reading_date": _day(117),
            "current_reading": "1100.000",
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert Decimal(data["previous_reading"]) == Decimal("1070.000")
    assert Decimal(data["consumption"]) == Decimal("30.000")


# --------------------------------------------------------------------------- #
# A meter cannot run backwards
# --------------------------------------------------------------------------- #


async def test_a_reading_below_the_previous_one_is_refused(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    response = await client.post(
        "/water/readings",
        headers=auth(society_a.admin_token),
        json={
            "flat_id": util.own_flat["id"],
            "reading_date": _day(116),
            "previous_reading": "2000.000",
            "current_reading": "1900.000",
        },
    )
    assert response.status_code == 422


async def test_a_reading_below_the_carried_forward_value_is_refused(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    """The last recorded value is the floor even when the caller omits it."""
    response = await client.post(
        "/water/readings",
        headers=auth(society_a.admin_token),
        json={
            "flat_id": util.own_flat["id"],
            "reading_date": _day(115),
            "current_reading": "900.000",
        },
    )
    assert response.status_code == 422
    assert "below the last recorded value" in response.text


async def test_a_future_dated_reading_is_refused(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    response = await client.post(
        "/water/readings",
        headers=auth(society_a.admin_token),
        json={
            "flat_id": util.own_flat["id"],
            "reading_date": (date.today() + timedelta(days=1)).isoformat(),
            "current_reading": "1200.000",
        },
    )
    assert response.status_code == 422


async def test_two_readings_for_one_flat_on_one_day_are_refused(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    admin = auth(society_a.admin_token)
    body = {
        "flat_id": util.own_flat["id"],
        "reading_date": _day(114),
        "current_reading": "1150.000",
    }
    assert (await client.post("/water/readings", headers=admin, json=body)).status_code == 201
    clash = await client.post("/water/readings", headers=admin, json=body)
    assert clash.status_code == 409
    assert "already exists" in clash.json()["message"]


# --------------------------------------------------------------------------- #
# Bulk entry
# --------------------------------------------------------------------------- #


async def test_bulk_entry_records_a_whole_round(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    response = await client.post(
        "/electricity/readings/bulk",
        headers=auth(society_a.admin_token),
        json={
            "reading_date": _day(100),
            "period_key": "2026-01",
            "rows": [
                {"flat_id": util.own_flat["id"], "current_reading": "4200.000"},
                {"flat_id": util.other_flat["id"], "current_reading": "3100.000"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["created"] == 2


async def test_rerunning_a_round_tops_it_up_rather_than_failing(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    """A reader who lost signal halfway must be able to finish the round."""
    admin = auth(society_a.admin_token)
    reading_date = _day(99)
    first = await client.post(
        "/electricity/readings/bulk",
        headers=admin,
        json={
            "reading_date": reading_date,
            "rows": [{"flat_id": util.own_flat["id"], "current_reading": "4260.000"}],
        },
    )
    assert first.json()["data"]["created"] == 1

    second = await client.post(
        "/electricity/readings/bulk",
        headers=admin,
        json={
            "reading_date": reading_date,
            "rows": [
                {"flat_id": util.own_flat["id"], "current_reading": "4260.000"},
                {"flat_id": util.other_flat["id"], "current_reading": "3150.000"},
            ],
        },
    )
    body = second.json()["data"]
    assert body["created"] == 1
    assert body["skipped"] == 1


async def test_a_batch_with_one_bad_row_saves_nothing(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    """Partial application of a batch would leave the round half-entered with
    no way to tell which flats took."""
    admin = auth(society_a.admin_token)
    reading_date = _day(98)
    response = await client.post(
        "/electricity/readings/bulk",
        headers=admin,
        json={
            "reading_date": reading_date,
            "rows": [
                {"flat_id": util.own_flat["id"], "current_reading": "4300.000"},
                {"flat_id": util.other_flat["id"], "current_reading": "1.000"},
            ],
        },
    )
    assert response.status_code == 422

    listed = await client.get(
        "/electricity/readings",
        headers=admin,
        params={"flat_id": util.own_flat["id"], "from_date": reading_date, "to_date": reading_date},
    )
    assert listed.json()["data"]["total"] == 0


async def test_a_flat_cannot_appear_twice_in_one_batch(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    response = await client.post(
        "/water/readings/bulk",
        headers=auth(society_a.admin_token),
        json={
            "reading_date": _day(97),
            "rows": [
                {"flat_id": util.own_flat["id"], "current_reading": "1300.000"},
                {"flat_id": util.own_flat["id"], "current_reading": "1400.000"},
            ],
        },
    )
    assert response.status_code == 422


async def test_a_flat_from_another_society_is_refused(
    client: AsyncClient,
    society_a: SocietyFixture,
    society_b: SocietyFixture,
    util: UtilityFixture,
) -> None:
    """The flat id is real — in the wrong database."""
    response = await client.post(
        "/water/readings",
        headers=auth(society_b.admin_token),
        json={
            "flat_id": util.own_flat["id"],
            "reading_date": _day(96),
            "current_reading": "10.000",
        },
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Owner scoping
# --------------------------------------------------------------------------- #


async def test_a_resident_sees_only_their_own_meter(
    client: AsyncClient, util: UtilityFixture
) -> None:
    response = await client.get("/water/readings", headers=auth(util.resident_token))
    assert response.status_code == 200
    flat_ids = {r["flat_id"] for r in response.json()["data"]["items"]}
    assert flat_ids <= {util.own_flat["id"]}


async def test_a_resident_cannot_read_a_neighbours_trend(
    client: AsyncClient, util: UtilityFixture
) -> None:
    response = await client.get(
        f"/water/trend/{util.other_flat['id']}", headers=auth(util.resident_token)
    )
    # 404 rather than 403: probing must not confirm the flat exists.
    assert response.status_code == 404


async def test_a_resident_can_read_their_own_trend(
    client: AsyncClient, util: UtilityFixture
) -> None:
    response = await client.get(
        f"/water/trend/{util.own_flat['id']}", headers=auth(util.resident_token)
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["unit"] == "kL"
    assert data["points"]
    assert data["stats"]["readings"] >= 1


async def test_a_resident_cannot_record_a_reading(
    client: AsyncClient, util: UtilityFixture
) -> None:
    response = await client.post(
        "/water/readings",
        headers=auth(util.resident_token),
        json={
            "flat_id": util.own_flat["id"],
            "reading_date": _day(95),
            "current_reading": "9999.000",
        },
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# Parking
# --------------------------------------------------------------------------- #


async def test_parking_allotment_and_release(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    admin = auth(society_a.admin_token)
    tag = uuid.uuid4().hex[:6].upper()
    slot = (
        await client.post(
            "/parking/slots",
            headers=admin,
            json={"slot_number": f"P-{tag}", "slot_type": "FOUR_WHEELER", "monthly_charge": "500"},
        )
    ).json()["data"]
    assert slot["flat_id"] is None

    allotted = await client.post(
        f"/parking/slots/{slot['id']}/allotment",
        headers=admin,
        json={"flat_id": util.own_flat["id"]},
    )
    assert allotted.status_code == 200
    assert allotted.json()["data"]["flat_id"] == util.own_flat["id"]

    clash = await client.post(
        f"/parking/slots/{slot['id']}/allotment",
        headers=admin,
        json={"flat_id": util.other_flat["id"]},
    )
    assert clash.status_code == 409

    released = await client.post(
        f"/parking/slots/{slot['id']}/allotment", headers=admin, json={"flat_id": None}
    )
    assert released.json()["data"]["flat_id"] is None


async def test_slot_numbers_are_unique_case_insensitively(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    admin = auth(society_a.admin_token)
    tag = uuid.uuid4().hex[:6]
    first = await client.post(
        "/parking/slots", headers=admin, json={"slot_number": f"b-{tag}"}
    )
    assert first.status_code == 201
    clash = await client.post(
        "/parking/slots", headers=admin, json={"slot_number": f"B-{tag}"}
    )
    assert clash.status_code == 409


async def test_a_resident_sees_only_their_own_slot(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    admin = auth(society_a.admin_token)
    tag = uuid.uuid4().hex[:6].upper()
    for label, flat_id in (("own", util.own_flat["id"]), ("nbr", util.other_flat["id"])):
        slot = (
            await client.post(
                "/parking/slots", headers=admin, json={"slot_number": f"S{label}-{tag}"}
            )
        ).json()["data"]
        await client.post(
            f"/parking/slots/{slot['id']}/allotment", headers=admin, json={"flat_id": flat_id}
        )

    response = await client.get("/parking/slots", headers=auth(util.resident_token))
    assert response.status_code == 200
    assert {s["flat_id"] for s in response.json()["data"]["items"]} <= {util.own_flat["id"]}


# --------------------------------------------------------------------------- #
# Vehicles
# --------------------------------------------------------------------------- #


async def test_a_resident_registers_a_vehicle_against_their_own_flat(
    client: AsyncClient, util: UtilityFixture
) -> None:
    tag = uuid.uuid4().hex[:4].upper()
    response = await client.post(
        "/vehicles",
        headers=auth(util.resident_token),
        json={
            "flat_id": util.own_flat["id"],
            "registration_number": f"MH12 {tag}",
            "vehicle_type": "FOUR_WHEELER",
            "make": "Maruti",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["registration_number"] == f"MH12 {tag}"


async def test_a_resident_cannot_register_a_vehicle_against_a_neighbours_flat(
    client: AsyncClient, util: UtilityFixture
) -> None:
    response = await client.post(
        "/vehicles",
        headers=auth(util.resident_token),
        json={
            "flat_id": util.other_flat["id"],
            "registration_number": f"MH12 {uuid.uuid4().hex[:4].upper()}",
            "vehicle_type": "TWO_WHEELER",
        },
    )
    assert response.status_code == 404


async def test_a_registration_number_belongs_to_one_flat(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    """The gate must be able to resolve a plate to exactly one flat."""
    admin = auth(society_a.admin_token)
    plate = f"MH14 {uuid.uuid4().hex[:4].upper()}"
    first = await client.post(
        "/vehicles",
        headers=admin,
        json={
            "flat_id": util.own_flat["id"],
            "registration_number": plate,
            "vehicle_type": "FOUR_WHEELER",
        },
    )
    assert first.status_code == 201

    clash = await client.post(
        "/vehicles",
        headers=admin,
        json={
            "flat_id": util.other_flat["id"],
            "registration_number": plate.lower(),
            "vehicle_type": "FOUR_WHEELER",
        },
    )
    assert clash.status_code == 409


async def test_removing_a_vehicle_frees_its_plate(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    admin = auth(society_a.admin_token)
    plate = f"MH15 {uuid.uuid4().hex[:4].upper()}"
    vehicle = (
        await client.post(
            "/vehicles",
            headers=admin,
            json={
                "flat_id": util.own_flat["id"],
                "registration_number": plate,
                "vehicle_type": "TWO_WHEELER",
            },
        )
    ).json()["data"]

    assert (await client.delete(f"/vehicles/{vehicle['id']}", headers=admin)).status_code == 200

    # The plate can be registered again, to a different flat this time.
    again = await client.post(
        "/vehicles",
        headers=admin,
        json={
            "flat_id": util.other_flat["id"],
            "registration_number": plate,
            "vehicle_type": "TWO_WHEELER",
        },
    )
    assert again.status_code == 201


async def test_a_resident_sees_only_their_own_vehicles(
    client: AsyncClient, util: UtilityFixture
) -> None:
    response = await client.get("/vehicles", headers=auth(util.resident_token))
    assert response.status_code == 200
    assert {v["flat_id"] for v in response.json()["data"]["items"]} <= {util.own_flat["id"]}


# --------------------------------------------------------------------------- #
# Pets
# --------------------------------------------------------------------------- #


async def test_a_resident_registers_a_pet(client: AsyncClient, util: UtilityFixture) -> None:
    response = await client.post(
        "/pets",
        headers=auth(util.resident_token),
        json={
            "flat_id": util.own_flat["id"],
            "name": "Simba",
            "pet_type": "DOG",
            "breed": "Indie",
            "vaccination_expiry": (date.today() - timedelta(days=3)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["vaccination_due"] is True


async def test_a_resident_cannot_register_a_pet_for_a_neighbour(
    client: AsyncClient, util: UtilityFixture
) -> None:
    response = await client.post(
        "/pets",
        headers=auth(util.resident_token),
        json={"flat_id": util.other_flat["id"], "name": "Not mine", "pet_type": "CAT"},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #


async def test_the_resident_dashboard_is_scoped_to_its_own_flats(
    client: AsyncClient, util: UtilityFixture
) -> None:
    response = await client.get("/dashboard/resident", headers=auth(util.resident_token))
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    assert [f["id"] for f in data["flats"]] == [util.own_flat["id"]]
    assert data["water"] is not None
    assert data["water"]["points"]
    assert data["vehicles"] >= 1
    assert data["pets"] >= 1
    assert Decimal(data["outstanding"]) >= 0


async def test_the_utility_dashboard_is_admin_only(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    assert (
        await client.get("/dashboard/utilities", headers=auth(util.resident_token))
    ).status_code == 403

    response = await client.get("/dashboard/utilities", headers=auth(society_a.admin_token))
    assert response.status_code == 200
    data = response.json()["data"]
    assert "water" in data and "electricity" in data
    assert data["parking"]["total"] >= 1


async def test_readings_do_not_leak_between_societies(
    client: AsyncClient,
    society_a: SocietyFixture,
    society_b: SocietyFixture,
    util: UtilityFixture,
) -> None:
    a_ids = {
        r["id"]
        for r in (
            await client.get(
                "/water/readings", headers=auth(society_a.admin_token), params={"limit": 100}
            )
        ).json()["data"]["items"]
    }
    b_ids = {
        r["id"]
        for r in (
            await client.get(
                "/water/readings", headers=auth(society_b.admin_token), params={"limit": 100}
            )
        ).json()["data"]["items"]
    }
    assert a_ids
    assert not (a_ids & b_ids)


async def test_a_residents_manage_permission_does_not_widen_their_reads(
    client: AsyncClient, society_a: SocietyFixture, util: UtilityFixture
) -> None:
    """A FLAT_OWNER holds ``vehicle.manage`` and ``pet.manage`` so they can
    register their own car and dog. Reading that as society-wide authority
    would hand every resident the full vehicle and pet register — including
    which flat each plate belongs to.
    """
    admin = auth(society_a.admin_token)
    tag = uuid.uuid4().hex[:4].upper()
    await client.post(
        "/vehicles",
        headers=admin,
        json={
            "flat_id": util.other_flat["id"],
            "registration_number": f"MH16 {tag}",
            "vehicle_type": "FOUR_WHEELER",
        },
    )
    await client.post(
        "/pets",
        headers=admin,
        json={"flat_id": util.other_flat["id"], "name": f"Neighbour {tag}", "pet_type": "CAT"},
    )

    resident = auth(util.resident_token)
    vehicles = (await client.get("/vehicles", headers=resident, params={"limit": 100})).json()
    pets = (await client.get("/pets", headers=resident, params={"limit": 100})).json()

    assert {v["flat_id"] for v in vehicles["data"]["items"]} == {util.own_flat["id"]}
    assert {p["flat_id"] for p in pets["data"]["items"]} == {util.own_flat["id"]}

    # And the admin, who is genuinely society-wide, still sees both flats.
    all_vehicles = (
        await client.get("/vehicles", headers=admin, params={"limit": 100})
    ).json()
    assert util.other_flat["id"] in {v["flat_id"] for v in all_vehicles["data"]["items"]}
