"""Phase 6: reports and CSV export.

Reports are a shared envelope over ten builders, so the tests are shaped the
same way: a handful of properties asserted across *every* report, and then the
specific arithmetic of the ones that carry money.

The property that matters most is the first one. A report a principal cannot
run must be **absent from the catalogue and 404 from the endpoint** — a menu
item that 403s is a design bug, and a 403 on a report key tells the caller the
report exists.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import SocietyFixture, auth

pytestmark = pytest.mark.asyncio

ALL_KEYS = {
    "collection",
    "defaulters",
    "payments",
    "financial-year",
    "complaints",
    "work",
    "utilities",
    "occupancy",
    "visitors",
    "amenities",
}


@pytest_asyncio.fixture(scope="module", autouse=True)
async def seeded(client: AsyncClient, society_a: SocietyFixture) -> dict[str, Any]:
    """Give the reports something to count.

    This module is self-contained on purpose: running ``pytest
    tests/test_reports.py`` on its own must exercise the same assertions as a
    full-suite run, and a report tested only against an empty society is a
    report tested against nothing.
    """
    admin = auth(society_a.admin_token)
    tag = uuid.uuid4().hex[:5].upper()

    building = (
        await client.post(
            "/buildings", headers=admin, json={"name": f"Rep {tag}", "code": f"R{tag}"}
        )
    ).json()["data"]
    block = (
        await client.get("/blocks", headers=admin, params={"building_id": building["id"]})
    ).json()["data"][0]
    floor = (
        await client.post("/floors", headers=admin, json={"block_id": block["id"], "number": 9})
    ).json()["data"]
    flat = (
        await client.post(
            "/flats",
            headers=admin,
            json={"floor_id": floor["id"], "flat_number": f"{tag}-901", "area_sqft": 1000},
        )
    ).json()["data"]

    await client.post(
        "/complaints",
        headers=admin,
        json={
            "title": f"Report seed {tag}",
            "description": "Something to count.",
            "category": "PLUMBING",
            "flat_id": flat["id"],
        },
    )
    await client.post(
        "/maintenance/tasks",
        headers=admin,
        json={"title": f"Seed task {tag}", "due_on": date.today().isoformat()},
    )
    await client.post(
        "/visitors/gate-entries",
        headers=admin,
        json={"flat_id": flat["id"], "visitor_name": "Report Visitor"},
    )

    amenity = (
        await client.post(
            "/amenities",
            headers=admin,
            json={
                "name": f"Report Hall {tag}",
                "opens_at": "06:00:00",
                "closes_at": "22:00:00",
                "slot_minutes": 60,
                "booking_charge": "100.00",
            },
        )
    ).json()["data"]
    await client.post(
        "/amenities/bookings",
        headers=admin,
        json={
            "amenity_id": amenity["id"],
            "flat_id": flat["id"],
            "starts_at": datetime.combine(
                date.today() + timedelta(days=2), time(9, 0), tzinfo=UTC
            ).isoformat(),
        },
    )

    return {"building": building, "flat": flat, "amenity": amenity}



# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #


async def test_an_admin_sees_every_report(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    catalogue = (
        await client.get("/reports", headers=auth(society_a.admin_token))
    ).json()["data"]
    assert {r["key"] for r in catalogue} == ALL_KEYS
    assert all(r["title"] and r["description"] and r["permission"] for r in catalogue)


async def test_a_resident_cannot_reach_the_reports_module(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    tag = uuid.uuid4().hex[:5]
    email = f"report-resident-{tag}@test.nestflow.in"
    await client.post(
        "/users",
        headers=auth(society_a.admin_token),
        json={"email": email, "full_name": "Report Resident", "role_codes": ["FLAT_OWNER"]},
    )
    resident = auth(f"dev:{email}")

    assert (await client.get("/reports", headers=resident)).status_code == 403
    assert (await client.get("/reports/collection", headers=resident)).status_code == 403


async def test_a_report_a_principal_cannot_run_is_not_found(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    """404, not 403.

    A guard holds ``report.read`` and not ``billing.read_all``, so the
    defaulter list is invisible to them rather than merely refused.
    """
    tag = uuid.uuid4().hex[:5]
    email = f"report-guard-{tag}@test.nestflow.in"
    await client.post(
        "/users",
        headers=auth(society_a.admin_token),
        json={"email": email, "full_name": "Report Guard", "role_codes": ["SECURITY_ADMIN"]},
    )
    guard = auth(f"dev:{email}")

    catalogue = (await client.get("/reports", headers=guard)).json()["data"]
    keys = {r["key"] for r in catalogue}
    assert "visitors" in keys
    assert "defaulters" not in keys

    assert (await client.get("/reports/visitors", headers=guard)).status_code == 200
    assert (await client.get("/reports/defaulters", headers=guard)).status_code == 404


async def test_an_invented_report_key_is_not_found(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    response = await client.get(
        "/reports/there-is-no-such-report", headers=auth(society_a.admin_token)
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Every report obeys the envelope
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", sorted(ALL_KEYS))
async def test_every_report_returns_the_shared_envelope(
    client: AsyncClient, society_a: SocietyFixture, key: str
) -> None:
    response = await client.get(f"/reports/{key}", headers=auth(society_a.admin_token))
    assert response.status_code == 200, response.text
    report = response.json()["data"]

    assert report["key"] == key
    assert report["title"]
    assert report["columns"], "a report with no columns cannot be rendered"
    assert report["row_count"] == len(report["rows"])
    assert report["generated_at"] == date.today().isoformat()

    # Every declared column exists on every row, so the table never renders a
    # hole where a value should be.
    keys = {c["key"] for c in report["columns"]}
    for row in report["rows"]:
        assert keys <= set(row), f"{key}: row is missing {keys - set(row)}"

    # Totals are declared, not inferred.
    totalled = {c["key"] for c in report["columns"] if c["total"]}
    assert set(report["totals"]) == totalled


@pytest.mark.parametrize("key", sorted(ALL_KEYS))
async def test_every_report_exports_as_csv(
    client: AsyncClient, society_a: SocietyFixture, key: str
) -> None:
    response = await client.get(
        f"/reports/{key}/export", headers=auth(society_a.admin_token)
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert f"{key}-" in response.headers["content-disposition"]
    # A report is a snapshot of live data; a cached copy is a wrong copy.
    assert response.headers["cache-control"] == "no-store"

    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows, "even an empty report exports its headers"

    report = (
        await client.get(f"/reports/{key}", headers=auth(society_a.admin_token))
    ).json()["data"]
    assert rows[0] == [c["label"] for c in report["columns"]]


async def test_the_date_range_is_validated(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    response = await client.get(
        "/reports/payments",
        headers=auth(society_a.admin_token),
        params={"from_date": "2026-06-01", "to_date": "2026-01-01"},
    )
    assert response.status_code == 422


async def test_the_row_cap_is_declared(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    """A silently shortened report is a report that lies."""
    report = (
        await client.get(
            "/reports/occupancy", headers=auth(society_a.admin_token), params={"limit": 1}
        )
    ).json()["data"]
    assert report["row_count"] == 1
    assert report["truncated"] is True

    full = (
        await client.get("/reports/occupancy", headers=auth(society_a.admin_token))
    ).json()["data"]
    assert full["truncated"] is False


# --------------------------------------------------------------------------- #
# The arithmetic
# --------------------------------------------------------------------------- #


async def test_the_occupancy_report_agrees_with_the_flats_list(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    admin = auth(society_a.admin_token)
    report = (await client.get("/reports/occupancy", headers=admin)).json()["data"]
    flats = (await client.get("/flats", headers=admin, params={"limit": 1})).json()["data"]

    assert report["summary"]["flats"] == flats["total"]
    assert report["totals"]["flats"] == flats["total"]
    # Every flat is in exactly one occupancy bucket.
    for row in report["rows"]:
        assert row["owner_occupied"] + row["rented"] + row["vacant"] == row["flats"]


async def test_the_complaint_report_agrees_with_the_complaint_summary(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    admin = auth(society_a.admin_token)
    report = (
        await client.get(
            "/reports/complaints", headers=admin, params={"from_date": "2000-01-01"}
        )
    ).json()["data"]
    summary = (await client.get("/complaints/summary", headers=admin)).json()["data"]

    assert report["summary"]["raised"] == summary["total"]
    assert report["totals"]["open"] == summary["open"]


async def test_the_work_report_agrees_with_the_department_summaries(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    admin = auth(society_a.admin_token)
    report = (
        await client.get(
            "/reports/work", headers=admin, params={"from_date": "2000-01-01", "to_date": "2099-01-01"}
        )
    ).json()["data"]

    by_department = {r["department"]: r for r in report["rows"]}
    for route, label in (("maintenance", "Maintenance"), ("housekeeping", "Housekeeping")):
        summary = (await client.get(f"/{route}/summary", headers=admin)).json()["data"]
        row = by_department.get(label)
        if row is None:
            assert summary["total"] == 0
            continue
        assert row["tasks"] == summary["total"]
        assert row["open"] == summary["pending"] + summary["in_progress"]


async def test_the_collection_report_never_shows_more_collected_than_billed(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    report = (
        await client.get("/reports/collection", headers=auth(society_a.admin_token))
    ).json()["data"]
    for row in report["rows"]:
        billed = Decimal(row["billed"])
        collected = Decimal(row["collected"])
        assert collected <= billed
        assert Decimal(row["outstanding"]) == billed - collected
        assert Decimal(row["collection_rate"]) <= Decimal("100")


async def test_the_financial_year_report_labels_an_indian_year(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    """April to March, because that is when an Indian society closes its books."""
    report = (
        await client.get("/reports/financial-year", headers=auth(society_a.admin_token))
    ).json()["data"]

    label = report["summary"]["financial_year"]
    assert label.startswith("FY")
    assert date.fromisoformat(report["summary"]["from"]).month == 4
    assert date.fromisoformat(report["summary"]["to"]).month == 3


async def test_the_amenity_report_counts_the_bookings_that_exist(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    admin = auth(society_a.admin_token)
    report = (
        await client.get(
            "/reports/amenities",
            headers=admin,
            params={"from_date": "2000-01-01", "to_date": "2099-01-01"},
        )
    ).json()["data"]
    amenities = (
        await client.get("/amenities", headers=admin, params={"limit": 100})
    ).json()["data"]

    # One row per amenity, whether or not anybody booked it.
    assert report["row_count"] == amenities["total"]
    assert report["totals"]["bookings"] >= 0


async def test_the_visitor_report_never_counts_more_entries_than_logs(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    report = (
        await client.get(
            "/reports/visitors",
            headers=auth(society_a.admin_token),
            params={"from_date": "2000-01-01"},
        )
    ).json()["data"]
    for row in report["rows"]:
        assert row["entered"] <= row["logged"]
        assert row["denied"] <= row["logged"]


async def test_csv_money_survives_the_round_trip(
    client: AsyncClient, society_a: SocietyFixture
) -> None:
    """A treasurer opens this in Excel; the totals have to add up there too."""
    admin = auth(society_a.admin_token)
    report = (await client.get("/reports/collection", headers=admin)).json()["data"]
    export = (await client.get("/reports/collection/export", headers=admin)).text

    rows = list(csv.reader(io.StringIO(export)))
    labels = rows[0]
    billed_at = labels.index("Billed")

    data_rows = [r for r in rows[1:] if r and r[0] and r[0] != "Total"]
    assert len(data_rows) == report["row_count"]

    exported = sum((Decimal(r[billed_at]) for r in data_rows), Decimal("0"))
    assert exported == Decimal(report["totals"]["billed"])


# --------------------------------------------------------------------------- #
# Isolation. **Mandatory.**
# --------------------------------------------------------------------------- #


async def test_a_report_never_crosses_a_society_boundary(
    client: AsyncClient, society_a: SocietyFixture, society_b: SocietyFixture
) -> None:
    a = (
        await client.get("/reports/occupancy", headers=auth(society_a.admin_token))
    ).json()["data"]
    b = (
        await client.get("/reports/occupancy", headers=auth(society_b.admin_token))
    ).json()["data"]

    a_buildings = {r["building"] for r in a["rows"]}
    b_buildings = {r["building"] for r in b["rows"]}
    assert a_buildings
    assert not (a_buildings & b_buildings)
    assert b["summary"]["flats"] != a["summary"]["flats"] or b["summary"]["flats"] == 0
