"""The society-wide utility aggregate a Society Admin sees.

The admin's headline on Water and Electricity is the whole society added up,
not one flat's meter. That number is only trustworthy if opening readings stay
out of it — see ``society_totals`` for why.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def metered_flat(client: AsyncClient, society_a: SocietyFixture) -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:4].upper()
    building = (
        await client.post(
            "/buildings",
            headers=auth(society_a.admin_token),
            json={"name": f"Meter {suffix}", "code": suffix, "total_floors": 5},
        )
    ).json()["data"]
    block = (
        await client.get(
            "/blocks",
            headers=auth(society_a.admin_token),
            params={"building_id": building["id"]},
        )
    ).json()["data"][0]
    floor = (
        await client.post(
            "/floors",
            headers=auth(society_a.admin_token),
            json={"block_id": block["id"], "number": 2},
        )
    ).json()["data"]
    return (
        await client.post(
            "/flats",
            headers=auth(society_a.admin_token),
            json={
                "floor_id": floor["id"],
                "flat_number": f"M-{uuid.uuid4().hex[:6]}",
                "area_sqft": 1000,
                "flat_type": "2BHK",
            },
        )
    ).json()["data"]


@pytest.mark.parametrize("utility", ["water", "electricity"])
async def test_an_opening_reading_never_lands_in_the_society_total(
    client: AsyncClient,
    society_a: SocietyFixture,
    metered_flat: dict[str, Any],
    utility: str,
) -> None:
    """``consumption`` is generated as ``current - COALESCE(previous, 0)``, so
    a meter's first reading reports its entire cumulative face value. Summed
    across every flat that buries the real rounds — here by 500x."""
    opened_on = date.today() - timedelta(days=60)
    read_on = date.today() - timedelta(days=30)
    headers = auth(society_a.admin_token)

    # An installed meter that already reads 5000, then 20 units used.
    opening = await client.post(
        f"/{utility}/readings",
        headers=headers,
        json={
            "flat_id": metered_flat["id"],
            "reading_date": opened_on.isoformat(),
            "current_reading": "5000",
        },
    )
    assert opening.status_code == 201, opening.text
    assert float(opening.json()["data"]["consumption"]) == 5000, (
        "the generated column behaves as described; the aggregate must compensate"
    )

    real = await client.post(
        f"/{utility}/readings",
        headers=headers,
        json={
            "flat_id": metered_flat["id"],
            "reading_date": read_on.isoformat(),
            "current_reading": "5020",
            "previous_reading": "5000",
        },
    )
    assert real.status_code == 201, real.text

    points = (
        await client.get(
            f"/{utility}/society-trend", headers=headers, params={"months": 36}
        )
    ).json()["data"]
    by_date = {p["reading_date"]: float(p["total"]) for p in points}

    assert opened_on.isoformat() not in by_date, (
        "an opening round has no consumption period and is not a data point"
    )
    assert by_date.get(read_on.isoformat()) == 20, "the real round is counted in full"


@pytest.mark.parametrize("utility", ["water", "electricity"])
async def test_the_society_total_is_the_sum_of_every_flat(
    client: AsyncClient, society_a: SocietyFixture, utility: str
) -> None:
    """The admin headline is a lump sum: each round equals every flat added up."""
    headers = auth(society_a.admin_token)
    read_on = date.today() - timedelta(days=5)

    flats = (
        await client.get("/flats", headers=headers, params={"limit": 3})
    ).json()["data"]["items"]
    if len(flats) < 2:
        pytest.skip("needs at least two flats")

    rows = [
        {
            "flat_id": flat["id"],
            "current_reading": str(1000 + (index + 1) * 10),
            "previous_reading": "1000",
        }
        for index, flat in enumerate(flats)
    ]
    expected = sum((index + 1) * 10 for index in range(len(flats)))

    created = await client.post(
        f"/{utility}/readings/bulk",
        headers=headers,
        json={"reading_date": read_on.isoformat(), "rows": rows},
    )
    assert created.status_code in (200, 201), created.text

    points = (
        await client.get(
            f"/{utility}/society-trend", headers=headers, params={"months": 36}
        )
    ).json()["data"]
    total = next(
        (float(p["total"]) for p in points if p["reading_date"] == read_on.isoformat()),
        None,
    )
    assert total == expected, f"expected the {len(flats)} flats to add up to {expected}"
